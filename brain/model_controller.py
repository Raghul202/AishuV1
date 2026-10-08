"""
brain/model_controller.py — AI Model Controller with smart ranked routing.

Providers supported:
  - OpenRouter   (FREE_MODELS)        — primary, ranked + cooldown
  - Groq         (GROQ_MODELS)        — fast LPU inference, OpenAI-compatible
  - Cloudflare   (CLOUDFLARE_MODELS)  — edge inference, 10K Neurons/day free
  - Gemini       (GEMINI_MODELS)      — Google AI Studio free tier
  - HuggingFace  (HF_PARTNER_MODELS)  — partner/uncensored route only

Routing order per get_reply() call:
  1. last_good_model (any provider, fast-path)
  2. OpenRouter FREE_MODELS (ranked by priority_score)
  3. Groq models (in config order, very fast)
  4. Cloudflare models (in config order, edge)
  5. Gemini models (in config order, large context)

get_reply_partner() still tries HF first, then falls back to get_reply().
"""

import random
import re
import time
import threading
from typing import Optional

import requests

from config.settings import (
    FREE_MODELS, OPENROUTER_KEY, OPENROUTER_HEADERS, AI_MAX_TOKENS,
    AI_TIMEOUT, AI_TEMPERATURE, AI_REPLY_DEADLINE, DATABASE_FILE,
    HF_PARTNER_MODELS, HF_API_KEY,
    GEMINI_API_KEY, GEMINI_MODELS,
    GROQ_API_KEY, GROQ_MODELS,
    CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN, CLOUDFLARE_MODELS,
    NVIDIA_API_KEY, NVIDIA_NIM_MODELS, OPENROUTER_RATE_LIMITED_MODELS,
)
from core.schemas import ModelRankRecord, FAIL_API_DOWN, FAIL_NO_MODEL, FAIL_TIMEOUT
from core.memory.database import get_database
from utilities.logger import get_logger

log = get_logger("brain.model_controller")

# ── Tuning constants ───────────────────────────────────────────────────────────

CHAT_MODEL_TIMEOUT       = 5       # seconds — tight timeout for live chat
COOLDOWN_429_SECONDS     = 15 * 60 # 15 min cooldown after 429
COOLDOWN_FAIL_SECONDS    = 5  * 60 # 5 min soft cooldown after repeated failures
FAIL_THRESHOLD_FOR_COOLDOWN = 3    # consecutive failures before soft cooldown
RANKING_STALE_HOURS      = 24.0
SAVE_INTERVAL            = 30.0    # min seconds between disk saves

# ── OpenRouter tier boundaries (mirrors settings.py) ──────────────────────────
_TIER1 = FREE_MODELS[:5]
_TIER2 = FREE_MODELS[5:12]
_TIER3 = FREE_MODELS[12:]

_TIER_IDX: dict[str, int] = {}
for _m in _TIER1: _TIER_IDX[_m] = 0
for _m in _TIER2: _TIER_IDX[_m] = 1
for _m in _TIER3: _TIER_IDX[_m] = 2

# ── Provider tags (prepended to model name for tracking) ──────────────────────
_GROQ_PREFIX  = "groq/"
_CF_PREFIX    = "cf/"
_GEM_PREFIX   = "gemini/"
_NIM_PREFIX   = "nim/"
_LEAKED_REASONING_RE = re.compile(
    r"(?:^|\n)\s*(?:<think>|we are in (?:a |the )?(?:dm|server) context|according to (?:the )?(?:state|instructions)|"
    r"let'?s think|options:|example:|to respond as aishu|the user said)", re.IGNORECASE,
)


class ModelController:
    """
    Manages all LLM API calls across OpenRouter, Groq, Cloudflare, and Gemini
    with smart ranked routing, per-model cooldowns, and lazy disk saves.
    """

    def __init__(self):
        self._local = threading.local()
        self._state_lock = threading.RLock()
        self._db = get_database(DATABASE_FILE)

        # model name → ModelRankRecord (keyed by full provider/model string)
        self._rankings: dict[str, ModelRankRecord] = {}
        self._custom_models: list[str] = []

        # In-memory cooldowns: model → monotonic timestamp when cooldown expires
        self._cooldowns: dict[str, float] = {}

        # Consecutive failure counters (reset on success)
        self._consec_failures: dict[str, int] = {}

        # Last model that returned a successful reply (any provider)
        self._last_good_model: Optional[str] = None

        # Timestamp of last disk save
        self._last_save: float = 0.0

        self._load_rankings()

        nim_total = len({model for models in NVIDIA_NIM_MODELS.values() for model in models})
        total = nim_total + len(FREE_MODELS) + len(GROQ_MODELS) + len(CLOUDFLARE_MODELS) + len(GEMINI_MODELS) + len(self._custom_models)
        log.info(
            f"ModelController ready — {total} models across 5 providers "
            f"({nim_total} NVIDIA NIM, {len(FREE_MODELS)} OpenRouter, {len(GROQ_MODELS)} Groq, "
            f"{len(CLOUDFLARE_MODELS)} Cloudflare, {len(GEMINI_MODELS)} Gemini, {len(self._custom_models)} Custom), "
            f"{len(self._rankings)} ranked"
        )

    # ─── Session helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _create_pooled_session(headers: dict = None) -> requests.Session:
        s = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=25, max_retries=1)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        if headers:
            s.headers.update(headers)
        return s

    def _get_session(self) -> requests.Session:
        """OpenRouter session (thread-local)."""
        if not hasattr(self._local, "session"):
            self._local.session = self._create_pooled_session({
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type":  "application/json",
                "HTTP-Referer":  "https://github.com/aishu-bot",
                "X-Title":       "Aishu Discord Bot",
            })
        return self._local.session

    def _get_hf_session(self) -> requests.Session:
        """HuggingFace session (thread-local)."""
        if not hasattr(self._local, "hf_session"):
            self._local.hf_session = self._create_pooled_session({
                "Authorization": f"Bearer {HF_API_KEY}",
                "Content-Type":  "application/json",
            })
        return self._local.hf_session

    def _get_groq_session(self) -> requests.Session:
        """Groq session (thread-local)."""
        if not hasattr(self._local, "groq_session"):
            self._local.groq_session = self._create_pooled_session({
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type":  "application/json",
            })
        return self._local.groq_session

    def _get_cf_session(self) -> requests.Session:
        """Cloudflare Workers AI session (thread-local)."""
        if not hasattr(self._local, "cf_session"):
            self._local.cf_session = self._create_pooled_session({
                "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
                "Content-Type":  "application/json",
            })
        return self._local.cf_session

    def _get_nim_session(self) -> requests.Session:
        """NVIDIA NIM uses the OpenAI chat-completions wire format."""
        if not hasattr(self._local, "nim_session"):
            self._local.nim_session = self._create_pooled_session({
                "Authorization": f"Bearer {NVIDIA_API_KEY}",
                "Content-Type": "application/json",
            })
        return self._local.nim_session

    def _get_gem_session(self) -> requests.Session:
        """Gemini session (thread-local)."""
        if not hasattr(self._local, "gem_session"):
            self._local.gem_session = self._create_pooled_session()
        return self._local.gem_session

    def _begin_reply_deadline(self) -> bool:
        if getattr(self._local, "reply_deadline", None) is not None:
            return False
        self._local.reply_deadline = time.monotonic() + AI_REPLY_DEADLINE
        return True

    def _end_reply_deadline(self, owner: bool) -> None:
        if owner and hasattr(self._local, "reply_deadline"):
            del self._local.reply_deadline

    def _has_reply_time(self) -> bool:
        deadline = getattr(self._local, "reply_deadline", None)
        return deadline is None or time.monotonic() < deadline

    def _request_timeout(self, default: float) -> float:
        deadline = getattr(self._local, "reply_deadline", None)
        if deadline is None:
            return default
        return max(0.1, min(default, deadline - time.monotonic()))
    # ─── Persistent rankings ───────────────────────────────────────────────────

    def _load_rankings(self):
        try:
            raw = self._db.get_state("model_rankings", {})
            for model, d in raw.items():
                self._rankings[model] = ModelRankRecord.from_dict(d)
            log.debug(f"Loaded {len(self._rankings)} model rank records")
        except Exception as e:
            log.warning(f"Could not load model rankings: {e}")

    def _save_rankings(self, force: bool = False):
        with self._state_lock:
            now = time.monotonic()
            if not force and (now - self._last_save) < SAVE_INTERVAL:
                return
            try:
                snapshot = {m: r.to_dict() for m, r in self._rankings.items()}
                self._db.set_state("model_rankings", snapshot)
                self._last_save = now
            except Exception as e:
                log.error(f"Failed to save model rankings: {e}")

    def _get_record(self, model: str) -> ModelRankRecord:
        with self._state_lock:
            if model not in self._rankings:
                self._rankings[model] = ModelRankRecord(model=model)
            return self._rankings[model]

    # ─── Cooldown helpers ──────────────────────────────────────────────────────

    def _is_in_cooldown(self, model: str) -> bool:
        return time.monotonic() < self._cooldowns.get(model, 0.0)

    def _set_cooldown(self, model: str, seconds: float):
        self._cooldowns[model] = time.monotonic() + seconds
        short = model.split("/")[-1][:35]
        log.warning(f"🧊 [{short}] cooldown set for {seconds/60:.0f} min")

    def _clear_cooldown(self, model: str):
        self._cooldowns.pop(model, None)
        self._consec_failures[model] = 0

    def _bump_consec_failures(self, model: str):
        count = self._consec_failures.get(model, 0) + 1
        self._consec_failures[model] = count
        if count >= FAIL_THRESHOLD_FOR_COOLDOWN:
            self._set_cooldown(model, COOLDOWN_FAIL_SECONDS)
            log.warning(
                f"[{model.split('/')[-1][:35]}] "
                f"{count} consecutive failures — soft cooldown applied"
            )

    # ─── Smart ordered OpenRouter model list ──────────────────────────────────

    def _ordered_models(self) -> list[str]:
        """
        Return OpenRouter FREE_MODELS sorted best → worst,
        excluding last_good_model and cooled-down models.
        """
        result = []
        for model in FREE_MODELS:
            rec = self._get_record(model)
            if rec.manually_disabled:
                continue
            if self._is_in_cooldown(model):
                continue
            if model == self._last_good_model:
                continue
            result.append(model)

        def sort_key(m: str) -> tuple:
            rec    = self._rankings.get(m)
            score  = rec.priority_score if rec else 5000.0
            tier   = _TIER_IDX.get(m, 2)
            jitter = random.uniform(0, 200) if tier == 2 else 0.0
            return (score + jitter, tier)

        result.sort(key=sort_key)
        return result

    def _ordered_nim_models(self, task: str) -> list[str]:
        """Return task-appropriate NIM models with fresh probe data first."""
        configured = NVIDIA_NIM_MODELS.get(task, ())
        unique = list(dict.fromkeys(configured))
        return sorted(
            unique,
            key=lambda model: (
                self._rankings.get(_NIM_PREFIX + model).priority_score
                if _NIM_PREFIX + model in self._rankings else 5000.0,
                unique.index(model),
            ),
        )

    def probe_candidates(self) -> list[str]:
        """Every enabled route /refreshmodel is expected to validate."""
        candidates: list[str] = []
        if NVIDIA_API_KEY:
            for models in NVIDIA_NIM_MODELS.values():
                candidates.extend(_NIM_PREFIX + model for model in models)
        if OPENROUTER_HEADERS.get("Authorization") != "Bearer ":
            candidates.extend(FREE_MODELS)
            candidates.extend(OPENROUTER_RATE_LIMITED_MODELS)
        if GROQ_API_KEY:
            candidates.extend(_GROQ_PREFIX + model for model in GROQ_MODELS)
        if CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN:
            candidates.extend(_CF_PREFIX + model for model in CLOUDFLARE_MODELS)
        if GEMINI_API_KEY:
            candidates.extend(_GEM_PREFIX + model for model in GEMINI_MODELS)
        candidates.extend(self._custom_models)
        return list(dict.fromkeys(candidates))

    def probe_model(self, key: str) -> dict:
        """Probe one configured route with a minimal response and persist health."""
        self._cooldowns.pop(key, None)
        self._consec_failures[key] = 0
        started = time.monotonic()
        reply = self._dispatch(key, [{"role": "user", "content": "Reply with exactly: OK"}])
        elapsed = (time.monotonic() - started) * 1000
        rec = self._get_record(key)
        ok = bool(reply and not _LEAKED_REASONING_RE.search(reply))
        rec.add_probe_result(round(elapsed, 1) if ok else None, reply or rec.last_error or "no response")
        return {
            "name": key,
            "status": "healthy" if ok else ("cooldown" if self._is_in_cooldown(key) else "failed"),
            "response_time": round(elapsed / 1000, 3) if ok else 0.0,
            "error": "" if ok else (rec.last_error or "no usable response"),
        }

    # ─── Core API callers ──────────────────────────────────────────────────────

    @staticmethod
    def _task_kind(messages: list) -> str:
        text = str(messages[-1].get("content", "")).casefold() if messages else ""
        if any(token in text for token in ("```", "code", "python", "javascript", "typescript", "bug", "function", "error", "stack trace")):
            return "coding"
        if any(token in text for token in ("analyze", "analyse", "reason", "compare", "explain why", "step by step", "logic", "math")):
            return "reasoning"
        return "chat"

    def _call_nim_model(self, model: str, messages: list) -> Optional[str]:
        if not self._has_reply_time(): return None
        if not NVIDIA_API_KEY:
            return None
        key, rec, start = _NIM_PREFIX + model, self._get_record(_NIM_PREFIX + model), time.monotonic()
        if self._is_in_cooldown(key) or rec.manually_disabled:
            return None
        try:
            response = self._get_nim_session().post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                json={"model": model, "messages": messages, "max_tokens": AI_MAX_TOKENS, "temperature": AI_TEMPERATURE},
                timeout=self._request_timeout(CHAT_MODEL_TIMEOUT),
            )
            if response.status_code == 429:
                self._set_cooldown(key, COOLDOWN_429_SECONDS)
                return None
            if response.status_code != 200:
                rec.record_failure(f"HTTP {response.status_code}")
                self._bump_consec_failures(key)
                return None
            data = response.json()
            choices = data.get("choices") or []
            content = (choices[0].get("message", {}).get("content") or "").strip() if choices else ""
            if not content or _LEAKED_REASONING_RE.search(content):
                rec.record_failure("empty content" if not content else "reasoning leaked into content")
                self._bump_consec_failures(key)
                return None
            latency = (time.monotonic() - start) * 1000
            rec.record_success(latency); self._clear_cooldown(key); self._last_good_model = key
            self._save_rankings()
            return content
        except requests.exceptions.Timeout:
            rec.record_failure(FAIL_TIMEOUT); self._bump_consec_failures(key)
        except requests.exceptions.RequestException as exc:
            rec.record_failure(str(exc)[:80]); self._bump_consec_failures(key)
        except (ValueError, KeyError, IndexError) as exc:
            rec.record_failure(f"bad response: {exc}"); self._bump_consec_failures(key)
        return None

    def _call_model(
        self,
        model: str,
        messages: list,
        timeout: float = CHAT_MODEL_TIMEOUT,
    ) -> Optional[str]:
        """Call one OpenRouter model. Returns reply text or None."""
        rec   = self._get_record(model)
        if not self._has_reply_time(): return None
        start = time.monotonic()
        short = model.split("/")[-1][:35]

        if rec.manually_disabled:
            return None

        try:
            response = self._get_session().post(
                "https://openrouter.ai/api/v1/chat/completions",
                json={
                    "model":       model,
                    "messages":    messages,
                    "max_tokens":  AI_MAX_TOKENS,
                    "temperature": AI_TEMPERATURE,
                },
                timeout=self._request_timeout(timeout),
            )

            if response.status_code == 429:
                self._set_cooldown(model, COOLDOWN_429_SECONDS)
                log.warning(f"🚫 [OR:{short}] 429 — cooldown applied")
                return None
            if response.status_code >= 500:
                rec.record_failure(f"HTTP {response.status_code}")
                self._bump_consec_failures(model)
                return None
            if response.status_code != 200:
                rec.record_failure(f"HTTP {response.status_code}")
                self._bump_consec_failures(model)
                return None

            data = response.json()
            if "error" in data:
                code = data["error"].get("code", "?")
                msg  = data["error"].get("message", "unknown")
                if code == 429 or "rate" in str(msg).lower():
                    self._set_cooldown(model, COOLDOWN_429_SECONDS)
                    return None
                rec.record_failure(f"API error {code}: {msg}")
                self._bump_consec_failures(model)
                return None

            choices = data.get("choices")
            if not choices:
                rec.record_failure("no choices")
                self._bump_consec_failures(model)
                return None

            content = (choices[0].get("message", {}).get("content") or "").strip()
            if not content:
                rec.record_failure("empty content")
                self._bump_consec_failures(model)
                return None

            latency = (time.monotonic() - start) * 1000
            rec.record_success(latency)
            self._clear_cooldown(model)
            self._last_good_model = model
            log.info(f"✓ [OR:{short}] {latency:.0f}ms")
            self._save_rankings()
            return content

        except requests.exceptions.Timeout:
            rec.record_failure(FAIL_TIMEOUT)
            self._bump_consec_failures(model)
            log.warning(f"✗ [OR:{short}] timeout ({timeout}s)")
            return None
        except requests.exceptions.ConnectionError:
            rec.record_failure("connection error")
            self._bump_consec_failures(model)
            log.warning(f"✗ [OR:{short}] connection error")
            return None
        except Exception as e:
            rec.record_failure(str(e)[:80])
            self._bump_consec_failures(model)
            log.error(f"✗ [OR:{short}] unexpected: {e}")
            return None

    def _call_groq_model(self, model: str, messages: list) -> Optional[str]:
        if not self._has_reply_time(): return None
        """Call one Groq model (OpenAI-compatible). Returns reply text or None."""
        if not GROQ_API_KEY:
            return None

        # Skip STT-only models
        if model in ("whisper-large-v3", "whisper-large-v3-turbo"):
            return None

        key   = _GROQ_PREFIX + model
        rec   = self._get_record(key)
        start = time.monotonic()
        short = model[:35]

        if self._is_in_cooldown(key):
            return None

        try:
            response = self._get_groq_session().post(
                "https://api.groq.com/openai/v1/chat/completions",
                json={
                    "model":       model,
                    "messages":    messages,
                    "max_tokens":  AI_MAX_TOKENS,
                    "temperature": AI_TEMPERATURE,
                },
                timeout=self._request_timeout(CHAT_MODEL_TIMEOUT),
            )

            if response.status_code == 429:
                self._set_cooldown(key, COOLDOWN_429_SECONDS)
                log.warning(f"🚫 [Groq:{short}] 429 — cooldown applied")
                return None
            if response.status_code != 200:
                rec.record_failure(f"HTTP {response.status_code}")
                self._bump_consec_failures(key)
                log.warning(f"✗ [Groq:{short}] HTTP {response.status_code}")
                return None

            data    = response.json()
            choices = data.get("choices")
            if not choices:
                rec.record_failure("no choices")
                self._bump_consec_failures(key)
                return None

            content = (choices[0].get("message", {}).get("content") or "").strip()
            if not content:
                rec.record_failure("empty content")
                self._bump_consec_failures(key)
                return None

            latency = (time.monotonic() - start) * 1000
            rec.record_success(latency)
            self._clear_cooldown(key)
            self._last_good_model = key
            log.info(f"✓ [Groq:{short}] {latency:.0f}ms")
            self._save_rankings()
            return content

        except requests.exceptions.Timeout:
            rec.record_failure(FAIL_TIMEOUT)
            self._bump_consec_failures(key)
            log.warning(f"✗ [Groq:{short}] timeout")
            return None
        except Exception as e:
            rec.record_failure(str(e)[:80])
            self._bump_consec_failures(key)
            log.error(f"✗ [Groq:{short}] {e}")
            return None

    def _call_cf_model(self, model: str, messages: list) -> Optional[str]:
        if not self._has_reply_time(): return None
        """Call one Cloudflare Workers AI model. Returns reply text or None."""
        if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_API_TOKEN:
            return None

        key   = _CF_PREFIX + model
        rec   = self._get_record(key)
        start = time.monotonic()
        short = model.split("/")[-1][:35]

        if self._is_in_cooldown(key):
            return None

        try:
            url      = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/{model}"
            response = self._get_cf_session().post(
                url,
                json={
                    "messages":    messages,
                    "max_tokens":  AI_MAX_TOKENS,
                    "temperature": AI_TEMPERATURE,
                },
                timeout=self._request_timeout(CHAT_MODEL_TIMEOUT),
            )

            if response.status_code == 429:
                self._set_cooldown(key, COOLDOWN_429_SECONDS)
                log.warning(f"🚫 [CF:{short}] 429 — cooldown applied")
                return None
            if response.status_code != 200:
                rec.record_failure(f"HTTP {response.status_code}")
                self._bump_consec_failures(key)
                log.warning(f"✗ [CF:{short}] HTTP {response.status_code}")
                return None

            data = response.json()
            # Cloudflare wraps response in {"result": {"response": "..."}}
            result  = data.get("result", {})
            content = (result.get("response") or "").strip()

            # Some CF models return OpenAI-style choices
            if not content:
                choices = result.get("choices") or data.get("choices")
                if choices:
                    content = (choices[0].get("message", {}).get("content") or "").strip()

            if not content:
                rec.record_failure("empty content")
                self._bump_consec_failures(key)
                return None

            latency = (time.monotonic() - start) * 1000
            rec.record_success(latency)
            self._clear_cooldown(key)
            self._last_good_model = key
            log.info(f"✓ [CF:{short}] {latency:.0f}ms")
            self._save_rankings()
            return content

        except requests.exceptions.Timeout:
            rec.record_failure(FAIL_TIMEOUT)
            self._bump_consec_failures(key)
            log.warning(f"✗ [CF:{short}] timeout")
            return None
        except Exception as e:
            rec.record_failure(str(e)[:80])
            self._bump_consec_failures(key)
            log.error(f"✗ [CF:{short}] {e}")
            return None

    def _call_gemini_model(self, model: str, messages: list) -> Optional[str]:
        if not self._has_reply_time(): return None
        """
        Call one Gemini model via the REST API (no SDK dependency).
        Converts OpenAI-style messages to Gemini format.
        Returns reply text or None.
        """
        if not GEMINI_API_KEY:
            return None

        key   = _GEM_PREFIX + model
        rec   = self._get_record(key)
        start = time.monotonic()
        short = model[:35]

        if self._is_in_cooldown(key):
            return None

        # Convert messages: system → prepend to first user turn
        gemini_contents = []
        system_text     = ""
        for msg in messages:
            role    = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_text = content
                continue
            gemini_role = "user" if role == "user" else "model"
            if system_text and gemini_role == "user":
                text = f"{system_text}\n\n{content}".strip()
                system_text = ""
            else:
                text = content
            gemini_contents.append({
                "role": gemini_role,
                "parts": [{"text": text}]
            })

        if not gemini_contents:
            return None

        try:
            url      = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={GEMINI_API_KEY}"
            )
            response = self._get_gem_session().post(
                url,
                json={
                    "contents":         gemini_contents,
                    "generationConfig": {
                        "maxOutputTokens": AI_MAX_TOKENS,
                        "temperature":     AI_TEMPERATURE,
                    },
                },
                timeout=self._request_timeout(CHAT_MODEL_TIMEOUT),
            )

            if response.status_code == 429:
                self._set_cooldown(key, COOLDOWN_429_SECONDS)
                log.warning(f"🚫 [Gem:{short}] 429 — cooldown applied")
                return None
            if response.status_code != 200:
                rec.record_failure(f"HTTP {response.status_code}")
                self._bump_consec_failures(key)
                log.warning(f"✗ [Gem:{short}] HTTP {response.status_code}")
                return None

            data = response.json()
            try:
                content = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except (KeyError, IndexError):
                rec.record_failure("malformed response")
                self._bump_consec_failures(key)
                return None

            if not content:
                rec.record_failure("empty content")
                self._bump_consec_failures(key)
                return None

            latency = (time.monotonic() - start) * 1000
            rec.record_success(latency)
            self._clear_cooldown(key)
            self._last_good_model = key
            log.info(f"✓ [Gem:{short}] {latency:.0f}ms")
            self._save_rankings()
            return content

        except requests.exceptions.Timeout:
            rec.record_failure(FAIL_TIMEOUT)
            self._bump_consec_failures(key)
            log.warning(f"✗ [Gem:{short}] timeout")
            return None
        except Exception as e:
            rec.record_failure(str(e)[:80])
            self._bump_consec_failures(key)
            log.error(f"✗ [Gem:{short}] {e}")
            return None

    # ─── HuggingFace (partner route only) ─────────────────────────────────────

    def _call_hf_model(self, model: str, messages: list) -> Optional[str]:
        if not self._has_reply_time(): return None
        """Call a HuggingFace model via the Inference API."""
        start = time.monotonic()
        short = model.split("/")[-1][:25]
        try:
            response = self._get_hf_session().post(
                "https://router.huggingface.co/v1/chat/completions",
                json={
                    "model":       model,
                    "messages":    messages,
                    "max_tokens":  AI_MAX_TOKENS,
                    "temperature": AI_TEMPERATURE,
                    "stream":      False,
                },
                timeout=self._request_timeout(AI_TIMEOUT + 10),
            )
            if response.status_code == 429:
                log.warning(f"✗ [HF:{short}] 429 rate-limited")
                return None
            if response.status_code != 200:
                log.warning(f"✗ [HF:{short}] HTTP {response.status_code}")
                return None

            data = response.json()
            if "error" in data:
                log.warning(f"✗ [HF:{short}] error: {str(data['error'])[:80]}")
                return None

            choices = data.get("choices")
            if not choices:
                return None

            content = (choices[0].get("message", {}).get("content") or "").strip()
            if not content:
                return None

            log.info(f"✓ [HF:{short}] {(time.monotonic()-start)*1000:.0f}ms")
            return content

        except requests.exceptions.Timeout:
            log.warning(f"✗ [HF:{short}] timeout")
            return None
        except Exception as e:
            log.error(f"✗ [HF:{short}] {e}")
            return None

    # ─── Main entry points ─────────────────────────────────────────────────────

    def get_reply(self, messages: list) -> tuple:
        """Route a reply within one bounded, end-to-end provider deadline."""
        owner = self._begin_reply_deadline()
        try:
            return self._get_reply(messages)
        finally:
            self._end_reply_deadline(owner)

    def _get_reply(self, messages: list) -> tuple:
        """
        Try all providers in order until one responds.

        Order:
          1. last_good_model (any provider, fast-path)
          2. OpenRouter FREE_MODELS (priority-ranked)
          3. Groq GROQ_MODELS (fast LPU, in config order)
          4. Cloudflare CLOUDFLARE_MODELS (edge, in config order)
          5. Gemini GEMINI_MODELS (large context, in config order)

        Returns (reply_text, model_used, latency_ms, failure_kind).
        """
        start = time.monotonic()

        # A completed refresh has stronger evidence than static provider order.
        # Use its best healthy model on the next turn, then retain it as the
        # low-latency fast path until it fails or enters cooldown.
        ranked = self.best_model()
        if ranked and ranked in self._rankings and not self._is_in_cooldown(ranked):
            reply = self._dispatch(ranked, messages)
            if reply:
                return (reply, ranked, (time.monotonic() - start) * 1000, "")

        # Use the healthy NVIDIA route first. A small task classifier avoids
        # spending expensive reasoning capacity on a casual conversation.
        if NVIDIA_API_KEY:
            kind = self._task_kind(messages)
            for model in self._ordered_nim_models(kind):
                reply = self._call_nim_model(model, messages)
                if reply:
                    return (reply, _NIM_PREFIX + model, (time.monotonic() - start) * 1000, "")

        # ── 1. Fast-path: last known-good model ──────────────────────────────
        lgm = self._last_good_model
        if lgm and not self._is_in_cooldown(lgm):
            reply = self._dispatch(lgm, messages)
            if reply:
                return (reply, lgm, (time.monotonic() - start) * 1000, "")

        # Try only a small, ranked set per request.  Exhausting every configured
        # model makes a transient provider outage painfully slow for Discord users.
        for model in (self._ordered_models()[:3] if OPENROUTER_HEADERS.get("Authorization") != "Bearer " else []):
            reply = self._call_model(model, messages)
            if reply:
                return (reply, model, (time.monotonic() - start) * 1000, "")

        # ── 3. Groq ───────────────────────────────────────────────────────────
        if GROQ_API_KEY:
            for model in GROQ_MODELS[:3]:
                reply = self._call_groq_model(model, messages)
                if reply:
                    key = _GROQ_PREFIX + model
                    return (reply, key, (time.monotonic() - start) * 1000, "")

        # ── 4. Cloudflare ─────────────────────────────────────────────────────
        if CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN:
            for model in CLOUDFLARE_MODELS[:3]:
                reply = self._call_cf_model(model, messages)
                if reply:
                    key = _CF_PREFIX + model
                    return (reply, key, (time.monotonic() - start) * 1000, "")

        # ── 5. Gemini ─────────────────────────────────────────────────────────
        if GEMINI_API_KEY:
            for model in GEMINI_MODELS[:2]:
                reply = self._call_gemini_model(model, messages)
                if reply:
                    key = _GEM_PREFIX + model
                    return (reply, key, (time.monotonic() - start) * 1000, "")

        # Known free models that were rate-limited in the supplied probe are a
        # final, single-attempt fallback only. Their 429 response adds a cooldown.
        if OPENROUTER_HEADERS.get("Authorization") != "Bearer ":
            for model in OPENROUTER_RATE_LIMITED_MODELS:
                reply = self._call_model(model, messages)
                if reply:
                    return (reply, model, (time.monotonic() - start) * 1000, "")

        log.error("All providers and models exhausted")
        return ("", "", 0.0, FAIL_NO_MODEL)

    def _dispatch(self, key: str, messages: list) -> Optional[str]:
        """
        Route a keyed model string to the right caller.
        Used by the last_good_model fast-path which may be from any provider.
        """
        if key.startswith(_GROQ_PREFIX):
            return self._call_groq_model(key[len(_GROQ_PREFIX):], messages)
        if key.startswith(_CF_PREFIX):
            return self._call_cf_model(key[len(_CF_PREFIX):], messages)
        if key.startswith(_GEM_PREFIX):
            return self._call_gemini_model(key[len(_GEM_PREFIX):], messages)
        if key.startswith(_NIM_PREFIX):
            return self._call_nim_model(key[len(_NIM_PREFIX):], messages)
        # Default: OpenRouter
        return self._call_model(key, messages)

    def get_reply_partner(self, messages: list) -> tuple:
        """Partner routing with the same bounded end-to-end deadline."""
        owner = self._begin_reply_deadline()
        try:
            return self._get_reply_partner(messages)
        finally:
            self._end_reply_deadline(owner)

    def _get_reply_partner(self, messages: list) -> tuple:
        """
        Partner-tier route: HuggingFace uncensored models first,
        then falls back to get_reply() across all providers.
        """
        if not HF_API_KEY or HF_API_KEY.startswith("PASTE") or HF_API_KEY == "your_hf_key_here":
            log.warning("HF_API_KEY not set — using standard routing for partner")
            return self.get_reply(messages)

        start = time.monotonic()
        for model in HF_PARTNER_MODELS:
            reply = self._call_hf_model(model, messages)
            if reply:
                return (reply, f"hf/{model}", (time.monotonic() - start) * 1000, "")

        log.warning("All HF partner models failed — falling back to standard routing")
        return self.get_reply(messages)

    # ─── Probe (called by /refreshmodel) ──────────────────────────────────────

    def probe_all_models(self) -> list:
        """
        Test every model across all providers.
        Updates rankings and saves to disk.
        Returns sorted list of result dicts.
        """
        log.info("Starting full model probe across all providers...")
        results   = []

        for key in self.probe_candidates():
            outcome = self.probe_model(key)
            results.append({
                "model": key,
                "status": "✅ active" if outcome["status"] == "healthy" else "❌ failed",
                "latency_ms": outcome["response_time"] * 1000 if outcome["response_time"] else None,
                "short_name": key.split("/")[-1][:35],
            })

        self._save_rankings(force=True)
        results.sort(key=lambda x: (x["latency_ms"] is None, x["latency_ms"] or 9999))
        active_count = sum(1 for r in results if "✅" in r["status"])
        log.info(f"Probe done — {active_count}/{len(results)} active")
        return results

    # ─── Status / management ───────────────────────────────────────────────────

    def get_status_report(self) -> list:
        used = [r.to_dict() for r in self._rankings.values()
                if r.successes + r.failures > 0]
        return sorted(used, key=lambda x: (-x["success_rate"], x["avg_latency_ms"]))

    def best_model(self) -> str:
        candidates = [
            r for r in self._rankings.values()
            if r.successes >= 1
            and r.success_rate >= 0.8
            and r.is_active
            and not self._is_in_cooldown(r.model)
        ]
        if not candidates:
            return ""
        return min(candidates, key=lambda r: r.priority_score).model

    def get_cooldown_status(self) -> list[dict]:
        now = time.monotonic()
        return sorted(
            [{"model": m, "remaining_secs": round(u - now)}
             for m, u in self._cooldowns.items() if u > now],
            key=lambda x: -x["remaining_secs"]
        )

    def disable_model(self, model: str):
        rec = self._get_record(model)
        rec.manually_disabled = True
        self._save_rankings(force=True)
        log.info(f"Model manually disabled: {model}")

    def enable_model(self, model: str):
        rec = self._get_record(model)
        rec.manually_disabled = False
        rec.is_active         = True
        self._clear_cooldown(model)
        self._save_rankings(force=True)
        log.info(f"Model re-enabled: {model}")

    def add_custom_model(self, model_key: str) -> bool:
        """Add a custom model string (e.g. 'groq/llama-3.1-8b-instant' or 'openrouter/model-name')."""
        key = model_key.strip()
        if not key or key in self._custom_models:
            return False
        self._custom_models.append(key)
        self._db.set_state("custom_models", self._custom_models)
        rec = self._get_record(key)
        rec.is_active = True
        self._save_rankings(force=True)
        log.info(f"Custom model added: {key}")
        return True

    def remove_custom_model(self, model_key: str) -> bool:
        """Remove a custom model string."""
        key = model_key.strip()
        if key in self._custom_models:
            self._custom_models.remove(key)
            self._db.set_state("custom_models", self._custom_models)
            log.info(f"Custom model removed: {key}")
            return True
        return False

    def get_all_models_status(self) -> list[dict]:
        """Return comprehensive list of all configured models with health, provider, latency, and status."""
        out = []
        now = time.monotonic()
        for key in self.probe_candidates():
            rec = self._get_record(key)
            provider = "OpenRouter"
            if key.startswith(_GROQ_PREFIX):
                provider = "Groq"
            elif key.startswith(_CF_PREFIX):
                provider = "Cloudflare"
            elif key.startswith(_GEM_PREFIX):
                provider = "Gemini"
            elif key.startswith(_NIM_PREFIX):
                provider = "NVIDIA NIM"
            elif key.startswith("hf/"):
                provider = "HuggingFace"

            in_cd = self._is_in_cooldown(key)
            status = "disabled" if rec.manually_disabled else ("cooldown" if in_cd else ("active" if rec.is_active and rec.successes > 0 else "untested"))
            out.append({
                "key": key,
                "short_name": key.split("/")[-1],
                "provider": provider,
                "is_custom": key in self._custom_models,
                "enabled": not rec.manually_disabled,
                "status": status,
                "success_rate": round(rec.success_rate * 100, 1),
                "avg_latency_ms": round(rec.avg_latency_ms, 0) if rec.avg_latency_ms else 0,
                "last_error": rec.last_error or "",
                "in_cooldown": in_cd,
                "is_best": (key == self.best_model() or key == self._last_good_model),
            })
        return out


# Global singleton
model_controller = ModelController()
