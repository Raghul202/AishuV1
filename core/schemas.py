"""
core/schemas.py — Typed data schemas for all major AIshu system objects.

Every persistent or inter-module object has a canonical schema here.
Schemas are plain dataclasses with serialization helpers for JSON.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _new_id() -> str:
    return str(uuid.uuid4())[:8]


# ══════════════════════════════════════════════════════════════════
#  ENUMS (as string constants — no import overhead)
# ══════════════════════════════════════════════════════════════════

MOOD_LABELS = ["excited", "flirty", "happy", "soft", "playful", "neutral", "shy", "bored", "annoyed", "sad", "angry"]

REL_TIERS = ["stranger", "friend", "close_friend", "high_trust", "special_person", "partner"]

REL_TIER_LABELS = {
    "stranger":       "🤍 Stranger",
    "friend":         "💚 Friend",
    "close_friend":   "💙 Close Friend",
    "high_trust":     "💜 High Trust",
    "special_person": "💕 Special Person",
    "partner":        "💞 Life Partner",
}

def score_to_rel_tier(score: float) -> str:
    if score >= 300: return "partner"
    if score >= 120: return "special_person"
    if score >= 80:  return "high_trust"
    if score >= 50:  return "close_friend"
    if score >= 20:  return "friend"
    return "stranger"


# ══════════════════════════════════════════════════════════════════
#  MEMORY SCHEMAS
# ══════════════════════════════════════════════════════════════════

@dataclass
class MemoryItem:
    """A single stored LTM/UTM memory entry with metadata."""
    content:       str
    layer:         str   = "ltm"          # stm | utm | ltm
    source:        str   = "inferred"     # user_stated | inferred | promoted | manual
    category:      str   = "fact"         # fact | pref | topic | emotional_anchor
    importance:    int   = 5              # 1–10
    confidence:    float = 0.7            # 0.0–1.0
    mention_count: int   = 1
    created_at:    str   = field(default_factory=_now_iso)
    updated_at:    str   = field(default_factory=_now_iso)
    item_id:       str   = field(default_factory=_new_id)
    tags:          list  = field(default_factory=list)

    def touch(self):
        """Called each time this memory surfaces again."""
        self.mention_count += 1
        self.updated_at     = _now_iso()
        self.importance     = min(10, self.importance + 1)
        self.confidence     = min(1.0, self.confidence + 0.1)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryItem":
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


@dataclass
class MemoryOptimizationRecord:
    """Snapshot of what memory was selected for a single API call."""
    user_id:          int
    request_id:       str
    selected_facts:   list = field(default_factory=list)
    selected_prefs:   list = field(default_factory=list)
    selected_topics:  list = field(default_factory=list)
    selected_utm:     list = field(default_factory=list)
    relevance_scores: dict = field(default_factory=dict)
    total_tokens_est: int  = 0
    memory_truncated: bool = False
    created_at:       str  = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)


# ══════════════════════════════════════════════════════════════════
#  MOOD SCHEMA
# ══════════════════════════════════════════════════════════════════

@dataclass
class MoodState:
    """Full structured mood state with dimensions beyond score+label."""
    mood:          str   = "happy"     # mood label
    score:         int   = 20          # -100 to +100 (fresh default: happy)
    intensity:     float = 0.4         # 0.0–1.0, how strongly it shows
    valence:       float = 0.3         # -1.0 to +1.0, positive vs negative feel
    energy:        float = 0.7         # 0.0–1.0, how expressive/active
    stability:     float = 0.7         # 0.0–1.0, resistance to change
    last_change:   str   = field(default_factory=_now_iso)
    last_trigger:  str   = ""          # what caused the last mood shift

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MoodState":
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


# ══════════════════════════════════════════════════════════════════
#  RELATIONSHIP SCHEMA
# ══════════════════════════════════════════════════════════════════

@dataclass
class RelationshipState:
    """Full per-user-per-guild relationship state."""
    user_id:        int
    guild_id:       int
    username:       str
    # Core score
    score:          float = 0.0
    # Dimensional attributes (0–100)
    trust:          float = 0.0
    comfort:        float = 0.0
    warmth:         float = 0.0
    respect:        float = 50.0
    # Behavioral modifiers (0–1)
    attachment:             float = 0.0
    jealousy_sensitivity:   float = 0.3
    # Interaction counters
    interaction_count:      int   = 0
    positive_count:         int   = 0
    negative_count:         int   = 0
    # Spam protection
    last_score_update:      float = 0.0   # monotonic
    updates_this_minute:    int   = 0
    minute_window_start:    float = 0.0
    # Timestamps
    first_interaction:      str   = field(default_factory=_now_iso)
    last_interaction:       str   = ""

    @property
    def tier(self) -> str:
        return score_to_rel_tier(self.score)

    @property
    def tier_label(self) -> str:
        return REL_TIER_LABELS.get(self.tier, "🤍 Stranger")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RelationshipState":
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)

    @classmethod
    def new(cls, user_id: int, guild_id: int, username: str) -> "RelationshipState":
        return cls(user_id=user_id, guild_id=guild_id, username=username)


# ══════════════════════════════════════════════════════════════════
#  MODEL RANKING SCHEMA
# ══════════════════════════════════════════════════════════════════

@dataclass
class ModelRankRecord:
    """Persistent performance tracking for one AI model."""
    model:              str
    successes:          int   = 0
    failures:           int   = 0
    total_latency_ms:   float = 0.0
    last_success_at:    str   = ""
    last_failure_at:    str   = ""
    last_error:         str   = ""
    probe_results:      list  = field(default_factory=list)  # last 10 probes
    is_active:          bool  = True
    manually_disabled:  bool  = False
    created_at:         str   = field(default_factory=_now_iso)
    updated_at:         str   = field(default_factory=_now_iso)

    @property
    def total(self) -> int:
        return self.successes + self.failures

    @property
    def success_rate(self) -> float:
        return (self.successes / self.total) if self.total else 1.0

    @property
    def avg_latency_ms(self) -> float:
        return (self.total_latency_ms / self.successes) if self.successes else 9999.0

    @property
    def priority_score(self) -> float:
        """Lower = better candidate. Used to sort models."""
        if not self.is_active or self.manually_disabled:
            return 99999.0
        return self.avg_latency_ms * (2.0 - self.success_rate)

    def record_success(self, latency_ms: float):
        self.successes        += 1
        self.total_latency_ms += latency_ms
        self.last_success_at   = _now_iso()
        self.is_active         = True
        self.updated_at        = _now_iso()

    def record_failure(self, error: str = ""):
        self.failures        += 1
        self.last_failure_at  = _now_iso()
        self.last_error       = error
        self.updated_at       = _now_iso()
        # Mark inactive after enough data shows it's broken
        if self.failures >= 5 and self.success_rate < 0.2:
            self.is_active = False

    def add_probe_result(self, latency_ms: Optional[float], response: str):
        self.probe_results.append({
            "ts": _now_iso(), "latency_ms": latency_ms,
            "active": latency_ms is not None, "response": response[:30],
        })
        self.probe_results = self.probe_results[-10:]  # keep last 10

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ModelRankRecord":
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


# ══════════════════════════════════════════════════════════════════
#  GUILD CONFIG SCHEMA
# ══════════════════════════════════════════════════════════════════

@dataclass
class GuildConfig:
    """Full per-guild configuration."""
    guild_id:          int
    guild_name:        str  = ""
    # Channels
    auto_reply_channel:    Optional[int] = None
    enabled_channels:      list = field(default_factory=list)   # empty = all
    log_channel_id:        Optional[int] = None
    # Behavior
    memory_enabled:        bool  = True
    relationship_mode:     str   = "normal"   # normal | friends_only | disabled
    response_style_override: str = ""
    # Rate limits
    cooldown_seconds:      float = 3.0
    max_messages_per_window: int = 6
    rate_window_seconds:   float = 10.0
    # Admin
    admin_role_ids:    list = field(default_factory=list)
    mod_role_ids:      list = field(default_factory=list)
    # Feature toggles
    leaderboard_enabled: bool = True
    profile_enabled:     bool = True
    afk_enabled:         bool = True
    # Meta
    created_at:    str = field(default_factory=_now_iso)
    updated_at:    str = field(default_factory=_now_iso)

    def touch(self):
        self.updated_at = _now_iso()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GuildConfig":
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)

    @classmethod
    def default(cls, guild_id: int, guild_name: str = "") -> "GuildConfig":
        return cls(guild_id=guild_id, guild_name=guild_name)


# ══════════════════════════════════════════════════════════════════
#  PIPELINE SCHEMAS
# ══════════════════════════════════════════════════════════════════

@dataclass
class RoutePacket:
    """Normalized representation of an incoming message for routing."""
    request_id:   str
    user_id:      int
    username:     str
    display_name: str
    text:         str
    guild_id:     int  = 0
    channel_id:   int  = 0
    is_dm:        bool = False
    is_mention:   bool = False
    timestamp:    str  = field(default_factory=_now_iso)

    @classmethod
    def create(cls, user_id: int, username: str, display_name: str,
               text: str, guild_id: int = 0, channel_id: int = 0,
               is_dm: bool = False, is_mention: bool = False) -> "RoutePacket":
        return cls(
            request_id=_new_id(), user_id=user_id, username=username,
            display_name=display_name, text=text, guild_id=guild_id,
            channel_id=channel_id, is_dm=is_dm, is_mention=is_mention,
        )


@dataclass
class PromptContextPacket:
    """All assembled context for building the system prompt."""
    request_id:          str
    personality_block:   str = ""
    relationship_block:  str = ""
    memory_block:        str = ""
    server_block:        str = ""
    reasoning_hint:      str = ""
    response_guidelines: str = ""
    estimated_tokens:    int = 0
    token_budget:        int = 2000
    memory_truncated:    bool = False


@dataclass
class ExecutionResult:
    """The full result of one pipeline execution."""
    request_id:  str
    success:     bool
    chunks:      list = field(default_factory=list)
    model_used:  str  = ""
    latency_ms:  float = 0.0
    failure_kind: str  = ""    # empty if success
    failure_reason: str = ""   # internal, not shown to user
    timestamp:   str  = field(default_factory=_now_iso)

    @classmethod
    def ok(cls, request_id: str, chunks: list, model: str, latency: float) -> "ExecutionResult":
        return cls(request_id=request_id, success=True, chunks=chunks,
                   model_used=model, latency_ms=latency)

    @classmethod
    def fail(cls, request_id: str, kind: str, reason: str,
             fallback_chunks: list) -> "ExecutionResult":
        return cls(request_id=request_id, success=False, chunks=fallback_chunks,
                   failure_kind=kind, failure_reason=reason)


# ══════════════════════════════════════════════════════════════════
#  FAILURE RESULT SCHEMA
# ══════════════════════════════════════════════════════════════════

# Failure kind constants
FAIL_API_DOWN           = "api_down"
FAIL_NO_MODEL           = "no_model"
FAIL_TIMEOUT            = "timeout"
FAIL_PERMISSION_DENIED  = "permission_denied"
FAIL_MEMORY_UNAVAILABLE = "memory_unavailable"
FAIL_PARSE_FAIL         = "parse_fail"
FAIL_PARTIAL            = "partial_failure"
FAIL_RATE_LIMITED       = "rate_limited"

# Mood-aware fallback messages per failure kind
_FALLBACK_MESSAGES: dict = {
    FAIL_API_DOWN: {
        "excited": "wait hold on— something broke 😅 try again?",
        "flirty":  "hey wait something broke on my end 😅 say that again~",
        "happy":   "hmm, my brain froze for a sec. say that again?",
        "soft":    "oh... something went wrong 🥹 try again?",
        "playful": "lol my brain glitched, try again?",
        "neutral": "sorry, having trouble thinking right now... try again?",
        "shy":     "s-something went wrong... try again? 🥺",
        "bored":   "failed. try again i guess",
        "annoyed": "ugh it broke. later.",
        "sad":     "sorry... something went wrong 😔",
        "angry":   "not working.",
        "_default":"something went wrong, try again? 😅",
    },
    FAIL_TIMEOUT: {
        "excited": "ugh wait it timed out 😭 one more time?",
        "flirty":  "hmm it timed out 😅 you were saying~?",
        "happy":   "ugh timed out 😅 one more time?",
        "soft":    "timed out... try again? 🥹",
        "playful": "okay that's rude, it timed out lol — again?",
        "neutral": "that took too long... try again? 😅",
        "shy":     "um... it timed out 🥺 sorry",
        "bored":   "timed out. try again.",
        "annoyed": "too slow. try again.",
        "sad":     "timed out... sorry 😔",
        "angry":   "timed out. whatever.",
        "_default":"timed out, sorry — try again?",
    },
    FAIL_RATE_LIMITED: {
        "excited": "woah woah one at a time 😭",
        "flirty":  "hey slow down~ one thing at a time 😘",
        "happy":   "slow down a little! give me a second 😅",
        "soft":    "slow down a little... 🥹",
        "playful": "woah woah one at a time 😭",
        "neutral": "slow down a little! give me a second 😅",
        "shy":     "w-wait slow down a bit 🥺",
        "bored":   "ok slow down.",
        "annoyed": "too fast. wait.",
        "sad":     "slow down a little... 😔",
        "angry":   "stop spamming.",
        "_default":"slow down! give me a sec",
    },
    FAIL_PERMISSION_DENIED: {
        "_default": "you don't have permission for that 🚫",
    },
    FAIL_MEMORY_UNAVAILABLE: {
        "_default": "can't access memory right now, but i'm still here! just chat normally",
    },
    FAIL_NO_MODEL: {
        "_default": "all my thinking parts are offline right now 😓 try again in a bit?",
    },
}

def get_failure_message(kind: str, mood: str = "neutral") -> str:
    """Return a mood-appropriate user-facing message for a failure kind."""
    kind_map = _FALLBACK_MESSAGES.get(kind, {})
    return kind_map.get(mood) or kind_map.get("_default", "something went wrong, try again? 😅")
