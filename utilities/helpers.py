"""
utilities/helpers.py — Shared text processing utilities.
Used across multiple modules for message analysis and formatting.
"""

import re

# ─── Filler detection ────────────────────────────────────────────────────────
_FILLER_RE = re.compile(
    r"^(hi|hey|hello|sup|yo|ok|okay|k|kk|sure|yep|yup|nah|nope|yes|no|"
    r"lol|lmao|haha|hehe|xd|thanks|thx|ty|thank you|bye|cya|gn|brb|afk|"
    r"👍|😂|💀|🔥|😭|✅|hmm|mhm|uh|um)[!?\s.,]*$",
    re.IGNORECASE,
)

# ─── Preference/like/dislike patterns ───────────────────────────────────────
_PREF_RE = re.compile(
    r"\b(i (love|like|enjoy|hate|dislike|prefer|adore|play|watch|read|"
    r"listen to|use|work (with|on)|study)|my (favorite|favourite|fav) .{2,25} is\b)",
    re.IGNORECASE,
)

# ─── Personal fact patterns ──────────────────────────────────────────────────
_FACT_RE = re.compile(
    r"\b(my (name|age|job|hobby|pet|city|country|school|major|pronouns) is\b|"
    r"i'?m (\d{1,2}) years? old|i (have|own|got) (a |an )\w|"
    r"i (was born|grew up|live|moved) (in|at|to)\b)",
    re.IGNORECASE,
)

# ─── Question starters ───────────────────────────────────────────────────────
_Q_STARTERS = (
    "what ", "how ", "why ", "when ", "where ", "who ",
    "can you ", "do you ", "explain ", "is it ", "are you ",
)


def is_filler(text: str) -> bool:
    """True if the message is just a filler word/emoji with no real content."""
    t = text.strip()
    return len(t) < 3 or bool(_FILLER_RE.match(t))


def is_question(text: str) -> bool:
    """True if the message looks like a question."""
    tl = text.strip().lower()
    return tl.endswith("?") or tl.startswith(_Q_STARTERS)


def is_preference(text: str) -> bool:
    """True if the message contains a preference or like/dislike statement."""
    return bool(_PREF_RE.search(text))


def is_personal_fact(text: str) -> bool:
    """True if the message contains a personal fact."""
    return bool(_FACT_RE.search(text))


SAFE_LIMIT = 1800   # comfortably under Discord's 2000-char limit

def split_naturally(text: str, max_chunk: int = SAFE_LIMIT) -> list[str]:
    """
    Split a reply into Discord-safe chunks, NEVER truncating text.

    Priority:
      1. Split on paragraph boundaries (double newline)
      2. Split on single newline
      3. Split on sentence boundaries (.  !  ?)
      4. Hard split by character as last resort

    The full original text is always preserved across all chunks.
    Store the full reply in memory, not the split pieces.
    """
    if not text:
        return [""]

    # Fast path — fits in one message
    if len(text) <= max_chunk:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_chunk:
            chunks.append(remaining)
            break

        # 1. Try paragraph split (double newline)
        split_pos = remaining.rfind("\n\n", 0, max_chunk)
        if split_pos > 0:
            chunks.append(remaining[:split_pos])
            remaining = remaining[split_pos + 2:]  # skip the \n\n
            continue

        # 2. Try single newline
        split_pos = remaining.rfind("\n", 0, max_chunk)
        if split_pos > 0:
            chunks.append(remaining[:split_pos])
            remaining = remaining[split_pos + 1:]  # skip the \n
            continue

        # 3. Try sentence boundary — find best split point (keeps punct+space intact)
        best = -1
        best_end = -1
        for punct in ("! ", "? ", ". "):
            pos = remaining.rfind(punct, 0, max_chunk)
            if pos > best:
                best     = pos
                best_end = pos + len(punct)
        if best > 0:
            chunks.append(remaining[:best_end])
            remaining = remaining[best_end:]
            continue

        # 4. Hard character split (last resort — never drops text)
        chunks.append(remaining[:max_chunk])
        remaining = remaining[max_chunk:]

    return [c for c in chunks if c]


def clean_mention(text: str, bot_id: int) -> str:
    """Remove bot mention from message text."""
    return text.replace(f"<@{bot_id}>", "").replace(f"<@!{bot_id}>", "").strip()


def mood_to_emoji(mood: str) -> str:
    """Return the emoji for a given mood string."""
    return {
        "excited": "🤩",
        "flirty":  "😘",
        "happy":   "😊",
        "soft":    "🥹",
        "playful": "😏",
        "neutral": "😐",
        "shy":     "🥺",
        "bored":   "😑",
        "annoyed": "😒",
        "sad":     "😢",
        "angry":   "😠",
    }.get(mood, "🌸")


def relationship_tier(score: float) -> str:
    """Convert relationship score to a tier label."""
    if score >= 300:
        return "partner"
    elif score >= 120:
        return "special_person"
    elif score >= 80:
        return "high_trust"
    elif score >= 50:
        return "close_friend"
    elif score >= 20:
        return "friend"
    else:
        return "stranger"


def relationship_label(score: float) -> str:
    """Human-readable relationship label."""
    tier = relationship_tier(score)
    return {
        "partner":        "💞 Life Partner",
        "special_person": "💕 Special Person",
        "high_trust":     "💜 High Trust",
        "close_friend":   "💙 Close Friend",
        "friend":         "💚 Friend",
        "stranger":       "🤍 Stranger",
    }.get(tier, "🤍 Stranger")


def get_theme_color() -> int:
    """Return configured embed hex color integer or default pink."""
    try:
        from core.memory.memory_manager import memory_manager
        if memory_manager and memory_manager.db:
            raw = memory_manager.db.get_state("embed_color", "#FFB7C5")
            if isinstance(raw, str) and raw.startswith("#"):
                return int(raw.lstrip("#"), 16)
    except Exception:
        pass
    return 0xFFB7C5
