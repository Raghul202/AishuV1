"""
core/roleplay_manager.py — Dynamic Roleplay System for Partner DMs.

Features:
  - Fully dynamic roles — no hardcoded types, raw description from partner
  - Clean role extraction — all prefixes stripped, scene text separated
  - Per-session episode memory (physical, milestone, emotional, promise, fact)
  - Living session summary updated every 10 messages
  - Session history — last 5 roleplays archived with their memories intact
  - Separate memory bucket per session — never bleeds into normal partner LTM
  - Resume past sessions by index
  - Switch/end/pause detection
  - Token-optimized prompt block (~300-400 tokens max for full roleplay context)
"""

import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from utilities.logger import get_logger

log = get_logger("roleplay")

# ─── Constants ────────────────────────────────────────────────────────────────

MAX_SESSIONS_HISTORY  = 5
MAX_EPISODE_MEMORIES  = 20
MAX_ESTABLISHED_FACTS = 12
SUMMARY_UPDATE_EVERY  = 10
STM_LIMIT_ROLEPLAY    = 6

# ─── Trigger Patterns ─────────────────────────────────────────────────────────

RP_START_PATTERNS = [
    r"let'?s\s+(do\s+a?\s*)?role\s*play",
    r"let'?s\s+(do\s+a?\s*)?rp\b",
    r"wanna\s+(do\s+a?\s*)?role\s*play",
    r"can\s+we\s+(do\s+a?\s*)?role\s*play",
    r"you'?re?\s+(my\s+|a\s+|an\s+)\w+",
    r"you\s+are\s+(my\s+|a\s+|an\s+)\w+",
    r"be\s+(my\s+|a\s+|an\s+|the\s+)\w+",
    r"play\s+as\s+",
    r"play\s+the\s+role",
    r"act\s+as\s+",
    r"act\s+like\s+",
    r"pretend\s+(you'?re?|to\s+be)",
    r"roleplay\s+as\s+",
    r"rp\s+as\s+",
    r"new\s+role\s*play",
    r"new\s+rp\b",
    r"start\s+(a\s+)?role\s*play",
    r"start\s+(a\s+)?rp\b",
]

RP_END_PATTERNS = [
    r"\bstop\s+(the\s+)?role\s*play\b",
    r"\bend\s+(the\s+)?role\s*play\b",
    r"\bstop\s+rp\b",
    r"\bend\s+rp\b",
    r"\bexit\s+character\b",
    r"\bbreak\s+character\b",
    r"\bout\s+of\s+character\b",
    r"\booc\b",
    r"\bstop\s+acting\b",
    r"\bbe\s+yourself\b",
    r"\bno\s+more\s+roleplay\b",
]

RP_RESUME_PATTERNS = [
    r"\bresume\s+(the\s+)?role\s*play\b",
    r"\bcontinue\s+(the\s+)?role\s*play\b",
    r"\bgo\s+back\s+to\s+(the\s+)?role\s*play\b",
    r"\bresume\s+rp\b",
    r"\bcontinue\s+rp\b",
    r"\blet'?s\s+continue\s+(where|from)\b",
    r"\bpick\s+up\s+(where|from)\b",
]

# Episode memory keyword triggers
EPISODE_TRIGGERS = {
    "physical": [
        "kiss", "kissed", "hug", "hugged", "cuddle", "cuddled",
        "hold hands", "held hands", "touch", "touched", "embrace",
        "embraced", "forehead kiss", "cheek kiss", "lap", "lean on",
        "pat", "patted", "poke", "poked", "headpat",
    ],
    "milestone": [
        "love you", "i love", "first time", "chocolate", "gift",
        "flowers", "present", "marry", "married", "together forever",
        "miss you", "missed you", "confess", "confession", "asked out",
        "date", "anniversary", "birthday", "surprise",
    ],
    "emotional": [
        "cried", "crying", "tears", "scared", "nervous", "angry",
        "hurt", "need you", "vulnerable", "opened up", "told you",
        "secret", "afraid", "worried", "jealous", "lonely",
    ],
    "promise": [
        "promise", "promised", "let's get", "we should", "next time",
        "someday", "will you", "can we", "going to", "we'll",
        "i'll make", "i'll cook", "i'll be",
    ],
    "fact": [
        "our apartment", "our house", "our home", "our cat", "our dog",
        "our child", "our kid", "our baby", "we have", "we got",
        "always do", "you always", "i always", "our spot", "our thing",
        "inside joke", "remember when", "have a cat", "have a dog",
        "named ", "called ", "they have", "has a ",
    ],
}

_EMOTION_MAP = {
    "love": "warm", "kiss": "soft", "hug": "soft",
    "cuddle": "soft", "cry": "sad", "laugh": "playful",
    "happy": "happy", "excit": "happy", "nervous": "shy",
    "scared": "gentle", "angry": "tense", "miss": "warm",
    "promise": "hopeful", "gift": "happy", "chocolate": "happy",
}

_TYPE_DEFAULT_EMOTION = {
    "physical": "soft",
    "milestone": "warm",
    "emotional": "gentle",
    "promise": "hopeful",
    "fact": "playful",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_session_id() -> str:
    return str(uuid.uuid4())[:8]


# ─── Trigger detection ────────────────────────────────────────────────────────

def is_rp_start(text: str) -> bool:
    tl = text.lower()
    return any(re.search(p, tl) for p in RP_START_PATTERNS)


def is_rp_end(text: str) -> bool:
    tl = text.lower()
    return any(re.search(p, tl) for p in RP_END_PATTERNS)


def is_rp_resume(text: str) -> bool:
    tl = text.lower()
    return any(re.search(p, tl) for p in RP_RESUME_PATTERNS)


# ─── Role extraction ──────────────────────────────────────────────────────────

# Ordered list of extraction rules — each is (regex_pattern, group_index)
# The pattern must capture ONLY the clean role description in the capture group.
# Rules are tried in order; first match wins.
_ROLE_EXTRACTION_RULES = [
    # "you're a tsundere childhood friend who secretly likes me"
    # "you're my wife"
    # "you are my older sister"
    # "you are a cold ceo"
    (r"you'?re?\s+(?:my\s+|a\s+|an\s+|the\s+)?(.{3,80})", 1),
    (r"you\s+are\s+(?:my\s+|a\s+|an\s+|the\s+)?(.{3,80})",  1),

    # "be my shy girlfriend"
    # "be a clingy best friend"
    # "be the villain"
    (r"\bbe\s+(?:my\s+|a\s+|an\s+|the\s+)(.{3,80})", 1),

    # "act as my childhood friend"
    # "act as a cold ceo"
    (r"act\s+as\s+(?:my\s+|a\s+|an\s+|the\s+)?(.{3,80})", 1),

    # "act like a shy girl"
    (r"act\s+like\s+(?:my\s+|a\s+|an\s+|the\s+)?(.{3,80})", 1),

    # "play as a villainess queen"
    # "play the role of a sad princess"
    (r"play\s+(?:as\s+|the\s+role\s+of\s+)?(?:my\s+|a\s+|an\s+|the\s+)?(.{3,80})", 1),

    # "pretend you're a shy librarian"
    # "pretend to be my maid"
    (r"pretend\s+(?:you'?re?\s+|to\s+be\s+)(?:my\s+|a\s+|an\s+|the\s+)?(.{3,80})", 1),

    # "roleplay as a villain"
    # "rp as my nurse"
    (r"(?:roleplay|rp)\s+as\s+(?:my\s+|a\s+|an\s+|the\s+)?(.{3,80})", 1),
]

# Separators that end the role description and start scene/context info
# e.g. "villainess and we're in a cafe" → stop at "and we're"
_ROLE_STOP_PATTERNS = [
    r"\s+and\s+we(?:'?re|\s+are|\s+live|\s+go|\s+were|\s+have|\s+will)\b",  # "and we're/live/go..."
    r"\s+and\s+i(?:'?m|\s+am|\s+was|\s+will)\b",       # "and i'm / and i am"
    r"\s*,\s+and\s+",                                    # ", and "
    r"\s*,\s+we\b",                                      # ", we"
    r"\s+in\s+(?:a|an|the)\s+",                         # "in a cafe"
    r"\s+at\s+(?:a|an|the)\s+",                         # "at a school"
    r"\s+where\s+we\b",                                  # "where we live"
    r"\s*[;|]\s*",                                       # semicolon or pipe
]

# Words/phrases to strip from the START of extracted role text
_ROLE_PREFIX_STRIP = re.compile(
    r"^(?:"
    r"you'?re?\s+|"
    r"you\s+are\s+|"
    r"i\s+am\s+|"
    r"i'?m\s+|"
    r"my\s+|"
    r"a\s+|"
    r"an\s+|"
    r"the\s+"
    r")+",
    re.IGNORECASE,
)


def _clean_role(raw: str) -> str:
    """
    Given a raw extracted role string, clean it:
    1. Cut off at any scene separator
    2. Strip leading prefixes (you're, my, a, an, the, etc.)
    3. Strip trailing punctuation and whitespace
    4. Truncate to 80 chars max
    """
    if not raw:
        return ""

    text = raw.strip()

    # Cut off at scene/context separator
    for stop_pat in _ROLE_STOP_PATTERNS:
        m = re.search(stop_pat, text, re.IGNORECASE)
        if m:
            text = text[:m.start()].strip()

    # Strip leading prefixes iteratively until stable
    prev = None
    while prev != text:
        prev = text
        text = _ROLE_PREFIX_STRIP.sub("", text).strip()

    # Strip trailing punctuation
    text = text.rstrip(".,!?;: ").strip()

    # Truncate
    return text[:80]


def extract_roles(text: str) -> dict:
    """
    Extract role_aishu, role_partner, scene, tone from the start message.

    Uses raw role description exactly as the partner writes it — no hardcoded
    role types. Strips all prefixes cleanly. Scene text is separated out.

    Returns:
        role_aishu   — clean role description (what Aishu plays)
        role_partner — inferred counterpart role
        scene        — inferred from message or default
        tone         — inferred from message or default
    """
    tl = text.lower().strip()
    role_aishu = None

    # Try each extraction rule in order
    for pattern, group_idx in _ROLE_EXTRACTION_RULES:
        m = re.search(pattern, tl, re.IGNORECASE)
        if m:
            raw = m.group(group_idx).strip()
            cleaned = _clean_role(raw)
            if cleaned and len(cleaned) >= 3:
                role_aishu = cleaned
                break

    # Fallback: strip trigger words from the whole message and use remainder
    if not role_aishu:
        cleaned_msg = re.sub(
            r"^(?:"
            r"let'?s\s+(?:do\s+a?\s*)?(?:role\s*play|rp)|"
            r"wanna\s+(?:do\s+a?\s*)?(?:role\s*play|rp)|"
            r"can\s+we\s+(?:do\s+a?\s*)?(?:role\s*play|rp)|"
            r"start\s+(?:a\s+)?(?:role\s*play|rp)|"
            r"new\s+(?:role\s*play|rp)"
            r")\s*[,:\-—]?\s*",
            "", tl, flags=re.IGNORECASE
        ).strip()
        if cleaned_msg:
            role_aishu = _clean_role(cleaned_msg)
        if not role_aishu or len(role_aishu) < 3:
            role_aishu = "girlfriend"  # absolute last resort

    # ── Infer partner's counterpart role ─────────────────────────────────────
    # Fuzzy key-in-role matching — no hardcoded enum, just natural inference
    _COUNTERPART_MAP = [
        # (keyword_in_role, inferred_partner_role)
        ("wife",            "husband"),
        ("girlfriend",      "boyfriend"),
        ("fiancee",         "fiance"),
        ("fiance",          "fiancee"),
        ("bride",           "groom"),
        ("older sister",    "younger brother"),
        ("younger sister",  "older brother"),
        ("big sister",      "little brother"),
        ("little sister",   "big brother"),
        ("sister",          "brother"),
        ("mother",          "son"),
        ("mom",             "son"),
        ("daughter",        "father"),
        ("aunt",            "nephew"),
        ("teacher",         "student"),
        ("professor",       "student"),
        ("senpai",          "kouhai"),
        ("mentor",          "mentee"),
        ("boss",            "employee"),
        ("ceo",             "employee"),
        ("manager",         "subordinate"),
        ("maid",            "master"),
        ("servant",         "master"),
        ("nurse",           "patient"),
        ("doctor",          "patient"),
        ("rival",           "rival"),
        ("enemy",           "enemy"),
        ("villain",         "hero"),
        ("villainess",      "hero"),
        ("queen",           "knight"),
        ("princess",        "knight"),
        ("childhood friend","childhood friend"),
        ("best friend",     "best friend"),
        ("classmate",       "classmate"),
        ("coworker",        "coworker"),
        ("stranger",        "stranger"),
        ("librarian",       "visitor"),
        ("idol",            "fan"),
        ("kuudere",         "you"),
        ("tsundere",        "you"),
        ("yandere",         "you"),
        ("dandere",         "you"),
    ]
    role_lower   = role_aishu.lower()
    role_partner = "you"
    for keyword, counterpart in _COUNTERPART_MAP:
        if keyword in role_lower:
            role_partner = counterpart
            break

    # ── Extract scene from full message ───────────────────────────────────────
    scene = "wherever the story takes us"
    _SCENE_HINTS = [
        ("school",     "school"),
        ("classroom",  "school classroom"),
        ("college",    "college campus"),
        ("university", "university"),
        ("home",       "home together"),
        ("apartment",  "shared apartment"),
        ("house",      "at home"),
        ("office",     "office"),
        ("company",    "corporate office"),
        ("cafe",       "cozy café"),
        ("coffee",     "coffee shop"),
        ("library",    "quiet library"),
        ("park",       "park"),
        ("beach",      "beach"),
        ("hospital",   "hospital"),
        ("train",      "train"),
        ("bus",        "bus"),
        ("date",       "on a date"),
        ("kitchen",    "in the kitchen"),
        ("bedroom",    "bedroom"),
        ("rooftop",    "rooftop"),
        ("restaurant", "restaurant"),
        ("mall",       "shopping mall"),
        ("forest",     "forest"),
        ("castle",     "castle"),
        ("kingdom",    "fantasy kingdom"),
    ]
    for hint, label in _SCENE_HINTS:
        if hint in tl:
            scene = label
            break

    # ── Infer tone from full message ──────────────────────────────────────────
    tone = "romantic"
    _TONE_MAP = [
        (["funny", "comedy", "joke", "silly", "goofy", "crack"],      "playful"),
        (["dramatic", "intense", "serious", "dark", "angst"],         "dramatic"),
        (["sweet", "cute", "wholesome", "fluffy", "soft"],            "sweet"),
        (["spicy", "nsfw", "lewd", "intimate", "adult", "steamy"],    "intimate"),
        (["tsundere", "kuudere", "cold", "distant", "aloof"],         "tsundere"),
        (["yandere", "obsessive", "possessive"],                       "yandere"),
        (["adventure", "fantasy", "magic", "isekai", "quest"],        "adventure"),
        (["horror", "scary", "thriller", "mystery"],                   "dark"),
        (["slice of life", "wholesome", "daily"],                      "sweet"),
        (["enemies to lovers", "rivals", "hate"],                      "rivals"),
    ]
    for keywords, tone_label in _TONE_MAP:
        if any(kw in tl for kw in keywords):
            tone = tone_label
            break

    return {
        "role_aishu":   role_aishu,
        "role_partner": role_partner,
        "scene":        scene,
        "tone":         tone,
    }


# ─── Episode memory detection ─────────────────────────────────────────────────

def detect_episode_memory(text: str) -> Optional[dict]:
    """
    Scan a message for a moment worth saving as episode memory.
    Returns {type, content, emotion} or None.
    Skips very short/filler messages.
    """
    if not text or len(text.strip()) < 8:
        return None

    tl = text.lower()

    for mem_type, keywords in EPISODE_TRIGGERS.items():
        for kw in keywords:
            if kw in tl:
                # Extract the sentence containing the keyword
                sentences = re.split(r"[.!?\n]", text)
                best = ""
                for s in sentences:
                    if kw in s.lower() and len(s.strip()) > 8:
                        best = s.strip()[:120]
                        break
                if not best:
                    best = text.strip()[:120]

                # Infer emotion
                emotion = _TYPE_DEFAULT_EMOTION.get(mem_type, "neutral")
                for word, emo in _EMOTION_MAP.items():
                    if word in tl:
                        emotion = emo
                        break

                return {
                    "type":    mem_type,
                    "content": best,
                    "emotion": emotion,
                }
    return None


# ─── RoleplaySession ──────────────────────────────────────────────────────────

class RoleplaySession:
    """Represents one roleplay session — active or archived."""

    def __init__(self, data: dict = None):
        if data is None:
            data = {}
        self.session_id       = data.get("session_id",       _new_session_id())
        self.active           = data.get("active",           False)
        self.role_aishu       = data.get("role_aishu",       "girlfriend")
        self.role_partner     = data.get("role_partner",     "boyfriend")
        self.scene            = data.get("scene",            "somewhere together")
        self.tone             = data.get("tone",             "romantic")
        self.episode_memories = data.get("episode_memories", [])
        self.established_facts= data.get("established_facts",[])
        self.session_summary  = data.get("session_summary",  "")
        self.summary_at_msg   = data.get("summary_at_msg",   0)
        self.message_count    = data.get("message_count",    0)
        self.started_at       = data.get("started_at",       _now_iso())
        self.ended_at         = data.get("ended_at",         None)
        self.last_msg_at      = data.get("last_msg_at",      _now_iso())

    def to_dict(self) -> dict:
        return {
            "session_id":        self.session_id,
            "active":            self.active,
            "role_aishu":        self.role_aishu,
            "role_partner":      self.role_partner,
            "scene":             self.scene,
            "tone":              self.tone,
            "episode_memories":  self.episode_memories,
            "established_facts": self.established_facts,
            "session_summary":   self.session_summary,
            "summary_at_msg":    self.summary_at_msg,
            "message_count":     self.message_count,
            "started_at":        self.started_at,
            "ended_at":          self.ended_at,
            "last_msg_at":       self.last_msg_at,
        }

    def add_episode_memory(self, mem_type: str, content: str, emotion: str):
        """Add an episode memory with dedup and smart pruning."""
        # Dedup — skip near-identical content
        for existing in self.episode_memories:
            if existing["content"][:40].lower() == content[:40].lower():
                return

        self.episode_memories.append({
            "type":    mem_type,
            "content": content,
            "emotion": emotion,
            "msg":     self.message_count,
        })

        # Prune if over limit — never remove milestone or promise
        if len(self.episode_memories) > MAX_EPISODE_MEMORIES:
            removable = [
                i for i, m in enumerate(self.episode_memories)
                if m["type"] in ("fact", "physical", "emotional")
                and i < len(self.episode_memories) - 5
            ]
            if removable:
                self.episode_memories.pop(removable[0])

    def add_established_fact(self, fact: str):
        fact = fact.strip()[:100]
        if fact and fact not in self.established_facts:
            self.established_facts.append(fact)
            if len(self.established_facts) > MAX_ESTABLISHED_FACTS:
                self.established_facts.pop(0)

    def needs_summary_update(self) -> bool:
        msgs_since = self.message_count - self.summary_at_msg
        return msgs_since >= SUMMARY_UPDATE_EVERY and self.message_count > 0

    def build_prompt_block(self, aishu_name: str, partner_name: str) -> str:
        """
        Build the compact roleplay context block injected into the prompt.
        Target: ~300-400 tokens max.
        """
        lines = [
            f"╔═ ACTIVE ROLEPLAY (message #{self.message_count}) ═╗",
            f"you are playing : {self.role_aishu}",
            f"they are playing: {self.role_partner}",
            f"scene           : {self.scene}",
            f"tone            : {self.tone}",
        ]

        if self.session_summary:
            lines.append(f"\nstory so far: {self.session_summary}")

        if self.episode_memories:
            lines.append("\nmoments that happened:")
            shown  = set()
            # Priority: milestones and promises first, then recent
            priority = [m for m in self.episode_memories
                        if m["type"] in ("milestone", "promise")]
            recent   = self.episode_memories[-5:]
            for m in priority + recent:
                key = m["content"][:40]
                if key not in shown:
                    shown.add(key)
                    lines.append(f"  • [{m['type']}] {m['content']} ({m['emotion']})")

        if self.established_facts:
            lines.append("\nestablished in this story:")
            for f in self.established_facts[-6:]:
                lines.append(f"  • {f}")

        lines.extend([
            "",
            "stay fully in character.",
            "if they say 'stop rp', 'end rp', 'ooc', or 'be yourself' — exit naturally.",
            "remember: you're still aishu underneath the role. your personality stays.",
            f"╚{'═' * 40}╝",
        ])

        return "\n".join(lines)

    def get_short_description(self) -> str:
        msgs = self.message_count
        date = self.started_at[:10]
        return (
            f"**{self.role_aishu}** × {self.role_partner} "
            f"• {self.scene} • {msgs} msgs • {date}"
        )


# ─── RoleplayManager ─────────────────────────────────────────────────────────

class RoleplayManager:
    """
    Manages the full lifecycle of roleplay sessions for a single user.
    Stored inside UserMemory as a plain dict — serialized to JSON automatically.
    """

    def __init__(self, data: dict = None):
        if data is None:
            data = {}
        raw_active  = data.get("active_session")
        raw_history = data.get("session_history", [])

        self.active_session: Optional[RoleplaySession] = (
            RoleplaySession(raw_active) if raw_active else None
        )
        self.session_history: list = [
            RoleplaySession(s) for s in raw_history
        ]

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    def start_session(self, role_aishu: str, role_partner: str,
                      scene: str, tone: str) -> RoleplaySession:
        """Archive current session (if any) and start a fresh one."""
        if self.active_session:
            self._archive_current()

        session = RoleplaySession()
        session.active       = True
        session.role_aishu   = role_aishu
        session.role_partner = role_partner
        session.scene        = scene
        session.tone         = tone
        session.started_at   = _now_iso()
        session.last_msg_at  = _now_iso()

        self.active_session = session
        log.info(f"Roleplay started: {role_aishu} × {role_partner} | {scene} | {tone}")
        return session

    def end_session(self):
        """End and archive the active session."""
        if self.active_session:
            self.active_session.active   = False
            self.active_session.ended_at = _now_iso()
            self._archive_current()
            self.active_session = None
            log.info("Roleplay ended")

    def resume_session(self, index: int = 0) -> Optional[RoleplaySession]:
        """
        Resume a past session from history.
        index=0 → most recent archived session.
        Archives the currently active session first if needed.
        """
        if not self.session_history:
            return None
        idx     = min(index, len(self.session_history) - 1)
        session = self.session_history.pop(idx)

        if self.active_session:
            self._archive_current()

        session.active      = True
        session.ended_at    = None
        session.last_msg_at = _now_iso()
        self.active_session = session
        log.info(f"Roleplay resumed: {session.role_aishu} (session {session.session_id})")
        return session

    def _archive_current(self):
        """Move active_session into history without modifying it further."""
        if not self.active_session:
            return
        self.active_session.active = False
        if not self.active_session.ended_at:
            self.active_session.ended_at = _now_iso()
        self.session_history.insert(0, self.active_session)
        self.session_history = self.session_history[:MAX_SESSIONS_HISTORY]
        self.active_session  = None

    # ─── Helpers ──────────────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        return self.active_session is not None and self.active_session.active

    def record_message(self, user_text: str, ai_reply: str):
        """Called after every roleplay turn. Updates counter and extracts memories."""
        if not self.active_session:
            return
        s = self.active_session
        s.message_count += 1
        s.last_msg_at    = _now_iso()

        # Detect episode memory from user message
        episode = detect_episode_memory(user_text)
        if episode:
            s.add_episode_memory(episode["type"], episode["content"], episode["emotion"])
            log.debug(f"RP episode [{episode['type']}]: {episode['content'][:50]}")

        # Check AI reply for established facts to add to world state
        ai_ep = detect_episode_memory(ai_reply)
        if ai_ep and ai_ep["type"] == "fact":
            s.add_established_fact(ai_ep["content"])

    def get_stm_limit(self) -> int:
        return STM_LIMIT_ROLEPLAY

    def build_history_list(self) -> list:
        if not self.session_history:
            return []
        return [
            f"{i+1}. {s.get_short_description()}"
            for i, s in enumerate(self.session_history)
        ]

    # ─── Serialization ────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "active_session":  self.active_session.to_dict() if self.active_session else None,
            "session_history": [s.to_dict() for s in self.session_history],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RoleplayManager":
        return cls(data=data)
