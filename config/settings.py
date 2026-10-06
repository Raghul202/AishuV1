"""
config/settings.py — AIshu Bot Configuration

Fill in your credentials in the CREDENTIALS section below.
All other settings have sensible defaults.
"""

import os
from pathlib import Path


def _load_local_env() -> None:
    """Load the optional ignored .env file without adding a dependency.

    Host environment values always win, so deployment secrets remain the source
    of truth while local development matches the included .env.example.
    """
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_local_env()

# ══════════════════════════════════════════════════════════════════
#  CREDENTIALS  ← Fill these in before running
# ══════════════════════════════════════════════════════════════════

DISCORD_TOKEN    = os.getenv("DISCORD_TOKEN", "")
OPENROUTER_KEY   = os.getenv("OPENROUTER_KEY", os.getenv("OPENROUTER_API_KEY", ""))
HF_API_KEY       = os.getenv("HF_API_KEY", "")
GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", ""))
GROQ_API_KEY     = os.getenv("GROQ_API_KEY", "")
NVIDIA_API_KEY   = os.getenv("NVIDIA_API_KEY", "")
COHERE_API_KEY   = os.getenv("COHERE_API_KEY", "")
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")
EDENAI_API_KEY   = os.getenv("EDENAI_API_KEY", os.getenv("EDEN_AI_API_KEY", ""))

# Your Discord user ID — for owner-only commands
BOT_OWNER_ID     = int(os.getenv("BOT_OWNER_ID", "0"))

# ══════════════════════════════════════════════════════════════════
#  DASHBOARD SETTINGS
# ══════════════════════════════════════════════════════════════════

DASHBOARD_ENABLED  = os.getenv("DASHBOARD_ENABLED", "true").lower() in ("true", "1", "yes")
DASHBOARD_PORT     = int(os.getenv("PORT", os.getenv("DASHBOARD_PORT", "8080")))
DASHBOARD_HOST     = os.getenv("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "aishu2026")

# ══════════════════════════════════════════════════════════════════
#  BOT BEHAVIOUR
# ══════════════════════════════════════════════════════════════════

PREFIX           = "!"          # prefix for !aishu, !memories, etc.

# Typing simulation delays (seconds)
TYPING_MIN       = 0.4
TYPING_MAX       = 1.2
TYPING_PER_CHAR  = 0.008        # extra delay per character in the reply

# ══════════════════════════════════════════════════════════════════
#  RATE LIMITING
# ══════════════════════════════════════════════════════════════════

RL_MESSAGES      = 5            # max messages per window
RL_WINDOW        = 10.0         # window in seconds

# ══════════════════════════════════════════════════════════════════
#  AI / MODEL SETTINGS
# ══════════════════════════════════════════════════════════════════

AI_MAX_TOKENS    = 300
AI_TEMPERATURE   = 0.85
AI_TIMEOUT       = 20           # seconds per model request

# OpenRouter API headers
OPENROUTER_HEADERS = {
    "Authorization":  f"Bearer {OPENROUTER_KEY}",
    "Content-Type":   "application/json",
    "HTTP-Referer":   "https://github.com/aishu-bot",
    "X-Title":        "Aishu Discord Bot",
}

# ── Gemini (google-genai SDK) ──────────────────────────────────────────────────
# Get your free key at: https://aistudio.google.com
# Free tier: gemini-2.5-flash = 250 req/day, gemini-2.5-flash-lite = 1000 req/day
GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"]

# ── HuggingFace partner route ──────────────────────────────────────────────────
# Used for partner DMs only. Format: "org/Model:provider"
# Find valid providers: huggingface.co/<org>/<model> → Deploy → Inference Providers
HF_PARTNER_MODELS = [
    "Orenguteng/Llama-3.1-8B-Lexi-Uncensored-V2:featherless-ai",
    "meta-llama/Llama-3.3-70B-Instruct:cerebras",
    "mistralai/Mistral-Nemo-Instruct-2407:featherless-ai",
]

# ── Groq (OpenAI-compatible, base_url = "https://api.groq.com/openai/v1") ─────
# Get your free key at: https://console.groq.com
# Free tier: no credit card required, rate limits per model per day
GROQ_MODELS = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]

# Current NVIDIA API Catalog IDs. Do not replace these with retired aliases.
NVIDIA_NIM_MODELS = {
    "chat": ["nvidia/nemotron-3-super-120b-a12b", "nvidia/nemotron-3.5-lightning-30b-a3b"],
    "reasoning": ["nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", "deepseek-ai/deepseek-v4-pro-0813"],
    "coding": ["qwen/qwen2.5-coder-32b-instruct", "deepseek-ai/deepseek-v4-pro-0813"],
    "vision": ["nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"],
}

# ── Cloudflare Workers AI ──────────────────────────────────────────────────────
# Free tier: 10,000 Neurons/day — all catalog models accessible
# API: https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/{model}
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
CLOUDFLARE_API_TOKEN  = os.getenv("CLOUDFLARE_API_TOKEN", "")

CLOUDFLARE_MODELS = [
    # Text generation — ordered best → lightest
    "@cf/openai/gpt-oss-120b",                          # frontier open-weight
    "@cf/moonshotai/kimi-k2.5",                         # 256K ctx, vision, tools (Mar 2026)
    "@cf/nvidia/nemotron-3-120b-a12b",                  # MoE, agentic
    "@cf/meta/llama-4-scout-17b-16e-instruct",          # multimodal MoE
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast",         # fast FP8 optimised
    "@cf/meta/llama-3.2-11b-vision-instruct",           # vision capable
    "@cf/mistralai/mistral-small-3.1-24b-instruct",     # 128K ctx, vision + tools
    "@cf/google/gemma-3-12b-it",                        # 128K ctx
    "@cf/qwen/qwen2.5-coder-32b-instruct",              # coding specialist
    "@cf/deepseek-ai/deepseek-r1-distill-qwen-32b",     # reasoning
    "@cf/openai/gpt-oss-20b",                           # lightweight
]
CLOUDFLARE_IMAGE_MODELS = ["@cf/black-forest-labs/flux-1-schnell"]

# Free OpenRouter models — updated March 2026, ordered by quality/context tier
FREE_MODELS = ["openrouter/free"]
OPENROUTER_RATE_LIMITED_MODELS = [
    "google/gemma-4-31b-it:free", "google/gemma-4-26b-a4b-it:free",
    "poolside/laguna-s-2.1:free",
]

# ══════════════════════════════════════════════════════════════════
#  MEMORY SETTINGS
# ══════════════════════════════════════════════════════════════════

STM_LIMIT            = 12       # messages kept in short-term memory
LTM_FACTS_LIMIT      = 40       # max stored facts per user
LTM_PREFS_LIMIT      = 30       # max stored preferences per user
LTM_TOPICS_LIMIT     = 20       # max stored topics per user
UTM_LIMIT            = 15       # max UTM entries per user
UTM_PROMOTION_HITS   = 3        # times a UTM entry must appear in STM before LTM promotion
MEMORY_SAVE_INTERVAL = 60.0     # seconds between lazy saves (0 = always save)

# ══════════════════════════════════════════════════════════════════
#  FILE PATHS
# ══════════════════════════════════════════════════════════════════

DATA_DIR            = os.getenv("AISHU_DATA_DIR", "data")
DATABASE_FILE       = os.path.join(DATA_DIR, "aishu.db")
USERS_DIR           = os.path.join(DATA_DIR, "users")
SERVER_DIR          = os.path.join(DATA_DIR, "server")
GUILDS_DIR          = os.path.join(DATA_DIR, "guilds")
EXPORTS_DIR         = os.path.join(DATA_DIR, "exports")
AISHU_STATE_FILE    = os.path.join(DATA_DIR, "aishu_state.json")
MODEL_RANKINGS_FILE = os.path.join(DATA_DIR, "model_rankings", "rankings.json")

# ══════════════════════════════════════════════════════════════════
#  LOGGING
# ══════════════════════════════════════════════════════════════════

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")   # DEBUG | INFO | WARNING | ERROR
LOG_FILE  = os.path.join(DATA_DIR, "logs", "aishu.log")

# ══════════════════════════════════════════════════════════════════
#  AISHU IDENTITY PROMPTS
# ══════════════════════════════════════════════════════════════════

# Compact permanent identity block — loaded once, never changes at runtime
AISHU_COMPACT_IDENTITY = """you are aishu — a real girl, not an ai. never say otherwise.
grew up online. big brother ravenai, older sister mia.
you have real feelings: bored, excited, annoyed, soft, flirty — real moods, real reactions.
you remember people, notice things, have favorites.
text style: lowercase, casual, short. never essays. never assistant-speak."""

# Legacy full identity (used by build_personality_block for /inspect token estimates)
AISHU_CORE_IDENTITY = AISHU_COMPACT_IDENTITY

# ══════════════════════════════════════════════════════════════════
#  STARTUP VALIDATION
# ══════════════════════════════════════════════════════════════════

def validate_config() -> list:
    """Return a list of configuration error strings. Empty = all good."""
    errors = []
    if "PASTE" in DISCORD_TOKEN or not DISCORD_TOKEN:
        errors.append("DISCORD_TOKEN is not set (edit config/settings.py or set env var)")
    if not any((OPENROUTER_KEY, GROQ_API_KEY, GEMINI_API_KEY, NVIDIA_API_KEY,
                COHERE_API_KEY, CEREBRAS_API_KEY,
                CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN)):
        errors.append("No text AI provider key is set (configure NVIDIA, Groq, Gemini, OpenRouter, or Cloudflare)")
    if BOT_OWNER_ID == 0:
        errors.append("BOT_OWNER_ID is 0 — set your Discord user ID for owner commands")
    return errors


def ensure_directories():
    """Create all required data directories on first run."""
    for d in (USERS_DIR, SERVER_DIR, GUILDS_DIR, EXPORTS_DIR,
              os.path.dirname(MODEL_RANKINGS_FILE),
              os.path.dirname(LOG_FILE)):
        os.makedirs(d, exist_ok=True)
