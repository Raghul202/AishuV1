"""
core/memory/user_memory.py — Per-user memory with promotion rules, importance scoring,
and dynamic roleplay session management.
"""

import re
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from config.settings import (
    STM_LIMIT, LTM_FACTS_LIMIT, LTM_PREFS_LIMIT,
    LTM_TOPICS_LIMIT, UTM_LIMIT, MEMORY_SAVE_INTERVAL, UTM_PROMOTION_HITS,
)
from core.schemas import MemoryItem
from core.roleplay_manager import RoleplayManager
from utilities.helpers import is_filler, is_question, is_preference, is_personal_fact
from utilities.logger import get_logger

log = get_logger("memory.user")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class UserMemory:
    __slots__ = (
        "user_id", "username", "display_name", "first_seen",
        "message_count", "last_seen",
        "stm",
        "_ltm_facts",
        "_ltm_prefs",
        "_ltm_topics",
        "_utm",
        # Partner private memory
        "_partner_stm",
        "_partner_ltm_facts",
        "_partner_ltm_prefs",
        # Roleplay system
        "_roleplay",
        # Streak tracking
        "current_streak",
        "longest_streak",
        "last_streak_date",
        "_dirty", "_last_save", "_path", "_storage",
    )

    def __init__(self, user_id: int, data: dict, path: str = "", storage=None):
        self._path      = path
        self._storage   = storage
        self._dirty     = False
        self._last_save = 0.0
        now             = _now_iso()

        self.user_id       = user_id
        self.username      = data.get("username", str(user_id))
        self.display_name  = data.get("display_name", str(user_id))
        self.first_seen    = data.get("first_seen", now)
        self.last_seen     = data.get("last_seen", now)
        self.message_count = data.get("message_count", 0)

        self.current_streak   = data.get("current_streak", 0)
        self.longest_streak   = data.get("longest_streak", 0)
        self.last_streak_date = data.get("last_streak_date", "")

        self.stm   = deque(data.get("stm", []), maxlen=STM_LIMIT)
        self._utm  = list(data.get("utm", []))[-UTM_LIMIT:]

        self._ltm_facts  = self._load_memory_items(data.get("ltm_facts",  []))
        self._ltm_prefs  = self._load_memory_items(data.get("ltm_prefs",  []))
        self._ltm_topics = self._load_memory_items(data.get("ltm_topics", []))

        self._partner_stm       = deque(data.get("partner_stm", []), maxlen=STM_LIMIT)
        self._partner_ltm_facts = self._load_memory_items(data.get("partner_ltm_facts", []))
        self._partner_ltm_prefs = self._load_memory_items(data.get("partner_ltm_prefs", []))

        # Roleplay system
        rp_data      = data.get("roleplay", {})
        self._roleplay = RoleplayManager.from_dict(rp_data)

    # ─── Compat properties ────────────────────────────────────────────────────

    @property
    def ltm_facts(self) -> list:
        return [m.content for m in self._ltm_facts]

    @property
    def ltm_prefs(self) -> list:
        return [m.content for m in self._ltm_prefs]

    @property
    def ltm_topics(self) -> list:
        return [m.content for m in self._ltm_topics]

    @property
    def utm(self) -> list:
        return self._utm

    @property
    def roleplay(self) -> RoleplayManager:
        return self._roleplay

    # ─── MemoryItem loading ───────────────────────────────────────────────────

    @staticmethod
    def _load_memory_items(raw: list) -> list:
        items = []
        for entry in raw:
            if isinstance(entry, str):
                items.append(MemoryItem(content=entry))
            elif isinstance(entry, dict) and "content" in entry:
                items.append(MemoryItem.from_dict(entry))
        return items

    # ─── Serialization ────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "user_id":          self.user_id,
            "username":         self.username,
            "display_name":     self.display_name,
            "first_seen":       self.first_seen,
            "last_seen":        self.last_seen,
            "message_count":    self.message_count,
            "current_streak":   self.current_streak,
            "longest_streak":   self.longest_streak,
            "last_streak_date": self.last_streak_date,
            "stm":              list(self.stm),
            "utm":              self._utm,
            "ltm_facts":        [m.to_dict() for m in self._ltm_facts],
            "ltm_prefs":        [m.to_dict() for m in self._ltm_prefs],
            "ltm_topics":       [m.to_dict() for m in self._ltm_topics],
            "partner_stm":       list(self._partner_stm),
            "partner_ltm_facts": [m.to_dict() for m in self._partner_ltm_facts],
            "partner_ltm_prefs": [m.to_dict() for m in self._partner_ltm_prefs],
            "roleplay":          self._roleplay.to_dict(),
        }

    def save(self, force: bool = False):
        now = time.monotonic()
        if not force and (not self._dirty or now - self._last_save < MEMORY_SAVE_INTERVAL):
            return
        try:
            if self._storage is None:
                raise RuntimeError("No persistence backend configured")
            self._storage.save_user(self.to_dict())
            self._dirty     = False
            self._last_save = now
        except Exception as e:
            log.error(f"Failed to save memory for {self.user_id}: {e}")

    def flush(self):
        self.save(force=True)

    def mark_dirty(self):
        self._dirty = True

    # ─── Identity ─────────────────────────────────────────────────────────────

    def update_identity(self, username: str, display_name: str):
        changed = False
        if self.username != username:
            self.username = username; changed = True
        if self.display_name != display_name:
            self.display_name = display_name; changed = True
        if changed:
            self._dirty = True

    def touch(self):
        self.last_seen      = _now_iso()
        self.message_count += 1
        self._dirty         = True

    def update_streak(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.last_streak_date == today:
            return
        if self.last_streak_date:
            from datetime import date
            try:
                last = date.fromisoformat(self.last_streak_date)
                curr = date.fromisoformat(today)
                diff = (curr - last).days
                self.current_streak = self.current_streak + 1 if diff == 1 else 1
            except ValueError:
                self.current_streak = 1
        else:
            self.current_streak = 1
        if self.current_streak > self.longest_streak:
            self.longest_streak = self.current_streak
        self.last_streak_date = today
        self._dirty = True

    # ─── STM ──────────────────────────────────────────────────────────────────

    def push_stm(self, role: str, content: str):
        self.stm.append({"role": role, "content": content})
        self._dirty = True

    def get_stm_list(self) -> list:
        return list(self.stm)

    # ─── Partner STM ──────────────────────────────────────────────────────────

    def push_partner_stm(self, role: str, content: str):
        self._partner_stm.append({"role": role, "content": content})
        self._dirty = True

    def get_partner_stm_list(self) -> list:
        """
        Return partner STM, trimmed to roleplay limit if a roleplay is active.
        This is the main STM trimming hook for roleplay token optimization.
        """
        full = list(self._partner_stm)
        if self._roleplay.is_active:
            limit = self._roleplay.get_stm_limit()
            return full[-limit:] if len(full) > limit else full
        return full

    def extract_and_store_partner(self, text: str):
        if is_filler(text):
            return
        t = text.strip()[:200]
        if is_preference(t):
            self._add_to_list(
                self._partner_ltm_prefs, t, LTM_PREFS_LIMIT,
                source="partner_dm", category="pref", importance=7,
            )
        if is_personal_fact(t):
            self._add_to_list(
                self._partner_ltm_facts, t, LTM_FACTS_LIMIT,
                source="partner_dm", category="fact", importance=8,
            )

    # ─── UTM ──────────────────────────────────────────────────────────────────

    def _add_utm(self, text: str):
        t = text.strip()[:200]
        normalized = " ".join(t.casefold().split())
        if not normalized:
            return
        for index, existing in enumerate(self._utm):
            if " ".join(existing.casefold().split()) == normalized:
                # Keep recent conversational context fresh without storing a duplicate.
                self._utm.append(self._utm.pop(index))
                self._dirty = True
                return
        self._utm.append(t)
        if len(self._utm) > UTM_LIMIT:
            self._utm.pop(0)
        self._dirty = True

    # ─── LTM helpers ──────────────────────────────────────────────────────────

    def _find_existing(self, items: list, content: str) -> Optional[MemoryItem]:
        cl = " ".join(content.casefold().split())
        for item in items:
            existing = " ".join(item.content.casefold().split())
            if existing == cl:
                return item
            if len(cl) >= 16 and len(cl) < 100 and (cl in existing or existing in cl):
                return item
        return None

    def _add_to_list(self, items: list, content: str, limit: int,
                     source: str = "inferred", category: str = "fact",
                     importance: int = 5) -> bool:
        existing = self._find_existing(items, content)
        if existing:
            existing.touch()
            self._dirty = True
            return True
        item = MemoryItem(
            content=content[:200], layer="ltm", source=source,
            category=category, importance=importance,
        )
        items.append(item)
        if len(items) > limit:
            items.sort(key=lambda m: (m.importance, m.mention_count))
            items.pop(0)
        self._dirty = True
        return True

    def add_fact(self, content: str, importance: int = 7, source: str = "user_stated") -> bool:
        """Add a specific fact to long-term memory."""
        t = content.strip()[:200]
        if not t:
            return False
        return self._add_to_list(
            self._ltm_facts, t, LTM_FACTS_LIMIT,
            source=source, category="fact", importance=importance,
        )

    def add_pref(self, content: str, importance: int = 6, source: str = "user_stated") -> bool:
        """Add a specific preference to long-term memory."""
        t = content.strip()[:200]
        if not t:
            return False
        return self._add_to_list(
            self._ltm_prefs, t, LTM_PREFS_LIMIT,
            source=source, category="pref", importance=importance,
        )

    # ─── LTM extraction ───────────────────────────────────────────────────────

    def extract_and_store(self, text: str):
        if is_filler(text):
            return
        t = text.strip()[:200]
        stored = False
        if is_preference(t):
            stored = self._add_to_list(
                self._ltm_prefs, t, LTM_PREFS_LIMIT,
                source="user_stated", category="pref", importance=6,
            )
        if is_personal_fact(t):
            stored = self._add_to_list(
                self._ltm_facts, t, LTM_FACTS_LIMIT,
                source="user_stated", category="fact", importance=7,
            ) or stored
        if is_question(t) and len(t) > 20:
            self._add_to_list(
                self._ltm_topics, t, LTM_TOPICS_LIMIT,
                source="inferred", category="topic", importance=4,
            )
        if t and not is_filler(t):
            self._add_utm(t)

    # ─── UTM → LTM ────────────────────────────────────────────────────────────

    def promote_utm_to_ltm(self, text: str, source: str = "promoted"):
        if text not in self._utm:
            return
        category   = "pref" if is_preference(text) else "fact"
        importance = 6 if source == "promoted" else 5
        self._add_to_list(
            self._ltm_facts if category == "fact" else self._ltm_prefs,
            text, LTM_FACTS_LIMIT if category == "fact" else LTM_PREFS_LIMIT,
            source=source, category=category, importance=importance,
        )
        self._dirty = True

    # ─── Memory queries ───────────────────────────────────────────────────────

    def has_long_term_memory(self) -> bool:
        return bool(self._ltm_facts or self._ltm_prefs or self._ltm_topics)

    def get_important_memories(self, limit: int = 5) -> list:
        all_items = self._ltm_facts + self._ltm_prefs + self._ltm_topics
        all_items.sort(key=lambda m: (m.importance, m.mention_count), reverse=True)
        return [m.content for m in all_items[:limit]]

    def build_memory_context(self) -> str:
        parts = []
        if self._ltm_facts:
            parts.append("Facts: " + "; ".join(m.content for m in self._ltm_facts[-6:]))
        if self._ltm_prefs:
            parts.append("Likes/dislikes: " + "; ".join(m.content for m in self._ltm_prefs[-5:]))
        if self._ltm_topics:
            parts.append("Topics: " + "; ".join(m.content for m in self._ltm_topics[-4:]))
        return "\n".join(parts)

    # ─── Memory management ────────────────────────────────────────────────────

    def forget_keyword(self, keyword: str) -> bool:
        kw = keyword.lower()
        removed = False
        for lst in (self._ltm_facts, self._ltm_prefs, self._ltm_topics):
            before = len(lst)
            lst[:] = [m for m in lst if kw not in m.content.lower()]
            if len(lst) < before:
                removed = True
        before_utm = len(self._utm)
        self._utm[:] = [x for x in self._utm if kw not in x.lower()]
        if len(self._utm) < before_utm:
            removed = True
        if removed:
            self._dirty = True
        return removed

    def clear_all_memory(self):
        self.stm.clear()
        self._utm.clear()
        self._ltm_facts.clear()
        self._ltm_prefs.clear()
        self._ltm_topics.clear()
        self._partner_stm.clear()
        self._partner_ltm_facts.clear()
        self._partner_ltm_prefs.clear()
        self._dirty = True

    def clear_stm(self):
        self.stm.clear()
        self._dirty = True

    def export_dict(self) -> dict:
        return self.to_dict()
