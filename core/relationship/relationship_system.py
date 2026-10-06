"""
core/relationship/relationship_system.py — AIshu's relationship engine.

Each user has a rich RelationshipState per guild covering:
  score, trust, comfort, warmth, respect, attachment, jealousy_sensitivity

Score changes have spam protection, decay logic, and forgiveness.
High-tier relationships influence reply style at the prompt level.
"""

import time
import json
import os
from typing import Optional

from core.schemas import RelationshipState, score_to_rel_tier, REL_TIER_LABELS, _now_iso
from utilities.logger import get_logger

log = get_logger("relationship")

# ─── Score weight constants ───────────────────────────────────────────────────
W_NORMAL    =  1.0   # regular message
W_LONG_MSG  =  1.5   # message > 80 chars
W_QUESTION  =  1.0   # asking a question
W_FACT      =  3.0   # sharing a personal fact
W_POSITIVE  =  1.5   # kind/warm sentiment
W_NEGATIVE  = -3.0   # rude/hostile message
W_SPAM      = -2.0   # rate-limited behavior

# ─── Thresholds ───────────────────────────────────────────────────────────────
SPECIAL_PERSON_THRESHOLD = 120.0
ANTI_SPAM_WINDOW         = 60.0    # seconds
ANTI_SPAM_MAX_UPDATES    = 8       # max score updates per minute per user
DECAY_DAYS_THRESHOLD     = 30      # inactive days before slow decay starts
DECAY_AMOUNT_PER_DAY     = 0.5     # score lost per inactive day (very gentle)
FORGIVENESS_BASE         = 5.0     # score recovered per positive interaction after negative


class RelationshipSystem:
    """
    Manages all per-user-per-guild relationship states.
    Stored as part of AishuState (serialized to aishu_state.json).
    """

    def __init__(self, data: dict = None):
        # {guild_id_str: {user_id_str: RelationshipState.to_dict()}}
        self._raw: dict = data or {}
        # In-memory cache of RelationshipState objects
        self._cache: dict = {}
        self.dirty: bool = False

    # ─── Internal helpers ─────────────────────────────────────────────────────

    def _key(self, guild_id: int, user_id: int) -> tuple:
        return (str(guild_id or 0), str(user_id))

    def _get_state(self, guild_id: int, user_id: int) -> Optional[RelationshipState]:
        gk, uk = self._key(guild_id, user_id)
        cache_key = (gk, uk)
        if cache_key in self._cache:
            return self._cache[cache_key]
        guild_data = self._raw.get(gk, {})
        if uk in guild_data:
            rs = RelationshipState.from_dict(guild_data[uk])
            self._cache[cache_key] = rs
            return rs
        return None

    def _set_state(self, rs: RelationshipState):
        gk, uk = self._key(rs.guild_id, rs.user_id)
        if gk not in self._raw:
            self._raw[gk] = {}
        self._raw[gk][uk]          = rs.to_dict()
        self._cache[(gk, uk)]      = rs
        self.dirty                 = True

    # ─── Anti-spam ────────────────────────────────────────────────────────────

    def _check_spam(self, rs: RelationshipState) -> bool:
        """
        Return True if this update should be blocked (spam protection).
        Resets the window counter if the window has elapsed.
        """
        now = time.monotonic()
        if now - rs.minute_window_start > ANTI_SPAM_WINDOW:
            rs.minute_window_start = now
            rs.updates_this_minute = 0
        rs.updates_this_minute += 1
        return rs.updates_this_minute > ANTI_SPAM_MAX_UPDATES

    # ─── Score update ─────────────────────────────────────────────────────────

    def update(self, guild_id: int, user_id: int, username: str, delta: float):
        """
        Update relationship score and dimensional attributes.
        Anti-spam protected — too many updates in 60s = blocked.
        """
        rs = self._get_state(guild_id, user_id)
        if rs is None:
            rs = RelationshipState.new(user_id, guild_id or 0, username)
            # Register new user immediately so spam window is tracked correctly
            self._set_state(rs)

        rs.username = username  # keep fresh

        if self._check_spam(rs):
            log.debug(f"Relationship update blocked (spam) for {username}")
            self._set_state(rs)  # persist updated spam counters
            return

        # Apply delta
        old_score  = rs.score
        rs.score   = round(max(0.0, rs.score + delta), 2)
        rs.last_interaction = _now_iso()
        rs.interaction_count += 1

        if delta > 0:
            rs.positive_count += 1
            # Build trust and comfort slowly
            rs.trust    = min(100.0, rs.trust    + delta * 0.3)
            rs.comfort  = min(100.0, rs.comfort  + delta * 0.2)
            rs.warmth   = min(100.0, rs.warmth   + delta * 0.25)
            # Forgiveness recovery if previously had negative interactions
            if rs.negative_count > 0 and delta >= 2.0:
                rs.respect = min(100.0, rs.respect + FORGIVENESS_BASE)
        elif delta < 0:
            rs.negative_count += 1
            rs.respect  = max(0.0,   rs.respect  + delta * 0.5)
            rs.warmth   = max(0.0,   rs.warmth   + delta * 0.3)
            rs.comfort  = max(0.0,   rs.comfort  + delta * 0.15)

        # Attachment grows slowly at high trust levels
        if rs.trust > 70 and rs.interaction_count > 20:
            rs.attachment = min(1.0, rs.attachment + 0.01)

        # Jealousy sensitivity increases with attachment
        rs.jealousy_sensitivity = min(0.9, 0.3 + rs.attachment * 0.5)

        rs.last_score_update = time.monotonic()
        self._set_state(rs)

        if score_to_rel_tier(old_score) != score_to_rel_tier(rs.score):
            log.info(f"Relationship tier change for {username}: {score_to_rel_tier(old_score)} → {rs.tier}")

    # ─── Score delta calculation ──────────────────────────────────────────────

    @staticmethod
    def calculate_delta(text: str, is_question: bool = False,
                        sentiment: str = "neutral") -> float:
        """Calculate the score delta from a single message."""
        delta = W_NORMAL
        if len(text) > 80:
            delta += W_LONG_MSG
        if is_question:
            delta += W_QUESTION
        if sentiment == "positive":
            delta += W_POSITIVE
        elif sentiment == "negative":
            delta += W_NEGATIVE
        return delta

    # ─── Getters ──────────────────────────────────────────────────────────────

    def get_score(self, guild_id: int, user_id: int) -> float:
        rs = self._get_state(guild_id, user_id)
        return rs.score if rs else 0.0

    def get_tier(self, guild_id: int, user_id: int) -> str:
        return score_to_rel_tier(self.get_score(guild_id, user_id))

    def get_label(self, guild_id: int, user_id: int) -> str:
        return REL_TIER_LABELS.get(self.get_tier(guild_id, user_id), "🤍 Stranger")

    def get_state(self, guild_id: int, user_id: int) -> Optional[RelationshipState]:
        return self._get_state(guild_id, user_id)

    def is_special_person(self, guild_id: int, user_id: int) -> bool:
        return self.get_score(guild_id, user_id) >= SPECIAL_PERSON_THRESHOLD

    def is_top_user(self, guild_id: int, user_id: int) -> bool:
        lb = self.get_leaderboard(guild_id, 1)
        return lb[0][0] == user_id if lb else False

    # ─── Leaderboard ──────────────────────────────────────────────────────────

    def get_leaderboard(self, guild_id: int, limit: int = 10) -> list:
        gk    = str(guild_id or 0)
        guild = self._raw.get(gk, {})
        ranked = sorted(guild.items(), key=lambda x: x[1].get("score", 0), reverse=True)
        return [(int(uid), d.get("username", uid), d.get("score", 0.0))
                for uid, d in ranked[:limit]]

    def get_top_user(self, guild_id: int) -> Optional[int]:
        lb = self.get_leaderboard(guild_id, 1)
        return lb[0][0] if lb else None

    # ─── Prompt context ───────────────────────────────────────────────────────

    def describe_relationship(self, guild_id: int, user_id: int) -> str:
        """Natural language description for the AI prompt."""
        rs   = self._get_state(guild_id, user_id)
        tier = self.get_tier(guild_id, user_id)
        descriptions = {
            "partner": (
                "This is your life partner — the deepest bond you have with anyone. "
                "You love them completely. There are no walls, no filters, no holding back. "
                "You are fully yourself with them in every way."
            ),
            "special_person": (
                "This person is extremely important to you — someone you've grown very close to. "
                "You care about them deeply. You notice small things they say. "
                "When they talk to others a lot, you feel a little left out."
            ),
            "high_trust": (
                "You trust this person a lot. You're genuinely comfortable with them. "
                "You're open with them and enjoy their company."
            ),
            "close_friend": (
                "This person is a close friend. You know them well and enjoy talking to them. "
                "Your conversations flow naturally."
            ),
            "friend": (
                "This person is a friend — you've talked enough to feel comfortable. "
                "You're warm but still getting to know them."
            ),
            "stranger": (
                "You don't know this person very well yet. Be friendly but a little cautious."
            ),
        }
        desc = descriptions.get(tier, "")

        # Add dimensional color at high tiers
        if rs and tier in ("partner", "special_person", "high_trust"):
            if rs.attachment > 0.5:
                desc += " You feel genuinely attached to them."
            if rs.jealousy_sensitivity > 0.6:
                desc += " You prefer when the conversation stays between you two."

        return desc

    # ─── Decay ────────────────────────────────────────────────────────────────

    def apply_decay(self, guild_id: int, user_id: int):
        """
        Gently decay score for inactive users.
        Only kicks in after DECAY_DAYS_THRESHOLD days of inactivity.
        """
        rs = self._get_state(guild_id, user_id)
        if not rs or not rs.last_interaction:
            return
        try:
            from datetime import datetime, timezone
            last = datetime.fromisoformat(rs.last_interaction)
            now  = datetime.now(timezone.utc)
            days = (now - last).days
            if days >= DECAY_DAYS_THRESHOLD:
                decay = min(5.0, (days - DECAY_DAYS_THRESHOLD) * DECAY_AMOUNT_PER_DAY)
                rs.score = max(0.0, rs.score - decay)
                self._set_state(rs)
        except Exception:
            pass

    # ─── Serialization ────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        # Sync cache back to raw before saving
        for (gk, uk), rs in self._cache.items():
            if gk not in self._raw:
                self._raw[gk] = {}
            self._raw[gk][uk] = rs.to_dict()
        return self._raw

    @classmethod
    def from_dict(cls, data: dict) -> "RelationshipSystem":
        return cls(data=data or {})
