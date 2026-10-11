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
from utilities.helpers import (
    is_filler, is_question, is_preference, is_personal_fact, is_one_to_one_dm,
)
from utilities.logger import get_logger

log = get_logger("memory.user")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class UserMemory:
    __slots__ = (
        "user_id", "username", "display_name", "first_seen",
        "message_count", "last_seen",
        "stm", "_conversation_stm",
        "_ltm_facts",
        "_ltm_prefs",
        "_ltm_topics",
        "_utm", "_utm_public",
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
        "_dirty", "_last_save", "_path", "_storage", "_clear_conversations",
    )

    def __init__(self, user_id: int, data: dict, path: str = "", storage=None):
        self._path      = path
        self._storage   = storage
        self._dirty     = False
        self._last_save = 0.0
        self._clear_conversations = False
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

        saved_streams = data.get("conversation_stm")
        if isinstance(saved_streams, dict):
            self._conversation_stm = {
                str(scope): deque(messages, maxlen=STM_LIMIT)
                for scope, messages in saved_streams.items()
            }
        else:
            self._conversation_stm = {
                "normal": deque(data.get("stm", []), maxlen=STM_LIMIT),
                "partner": deque(data.get("partner_stm", []), maxlen=STM_LIMIT),
            }
        self.stm = self._conversation_stm.setdefault(
            "normal", deque(maxlen=STM_LIMIT))
        self._partner_stm = self._conversation_stm.setdefault(
            "partner", deque(maxlen=STM_LIMIT))
        for scope in ("public", "private", "partner_normal"):
            self._conversation_stm.setdefault(scope, deque(maxlen=STM_LIMIT))
        self._utm  = list(data.get("utm", []))[-UTM_LIMIT:]
        self._utm_public = [
            item for item in data.get("utm_public", []) if item in self._utm
        ][-UTM_LIMIT:]

        self._ltm_facts  = self._load_memory_items(data.get("ltm_facts",  []))
        self._ltm_prefs  = self._load_memory_items(data.get("ltm_prefs",  []))
        self._ltm_topics = self._load_memory_items(data.get("ltm_topics", []))

        self._partner_ltm_facts = self._load_memory_items(data.get("partner_ltm_facts", []))
        self._partner_ltm_prefs = self._load_memory_items(data.get("partner_ltm_prefs", []))

        # Roleplay system
        rp_data      = data.get("roleplay", {})
        self._roleplay = RoleplayManager.from_dict(rp_data)

    # ─── Compat properties ────────────────────────────────────────────────────

    @property
    def ltm_facts(self) -> list:
        return [m.content for m in self.ordinary_memory_items(self._ltm_facts)]

    @property
    def ltm_prefs(self) -> list:
        return [m.content for m in self.ordinary_memory_items(self._ltm_prefs)]

    @property
    def ltm_topics(self) -> list:
        return [m.content for m in self.ordinary_memory_items(self._ltm_topics)]

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
            "conversation_stm":  {
                scope: list(messages)
                for scope, messages in self._conversation_stm.items()
            },
            "clear_conversations": self._clear_conversations,
            "utm":              self._utm,
            "utm_public":       self._utm_public,
            "ltm_facts":        [m.to_dict() for m in self._ltm_facts],
            "ltm_prefs":        [m.to_dict() for m in self._ltm_prefs],
            "ltm_topics":       [m.to_dict() for m in self._ltm_topics],
            "partner_stm":       list(self._partner_stm),
            "partner_ltm_facts": [m.to_dict() for m in self._partner_ltm_facts],
            "partner_ltm_prefs": [m.to_dict() for m in self._partner_ltm_prefs],
            "roleplay":          self._roleplay.to_dict(),
        }

    def save(self, force: bool = False) -> bool:
        now = time.monotonic()
        if not force and (not self._dirty or now - self._last_save < MEMORY_SAVE_INTERVAL):
            return True
        try:
            if self._storage is None:
                raise RuntimeError("No persistence backend configured")
            self._storage.save_user(self.to_dict())
            self._dirty     = False
            self._last_save = now
            self._clear_conversations = False
            return True
        except Exception as e:
            log.error(f"Failed to save memory for {self.user_id}: {e}")
            return False

    def flush(self) -> bool:
        return self.save(force=True)

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

    def push_stm(self, role: str, content: str, scope: str = "normal"):
        stream = self._conversation_stm.setdefault(
            scope, deque(maxlen=STM_LIMIT))
        stream.append({"role": role, "content": content})
        if scope == "normal":
            self.stm = stream
        elif scope == "partner":
            self._partner_stm = stream
        self._dirty = True

    def get_stm_list(self, scope: str = "normal") -> list:
        messages = list(self._conversation_stm.get(scope, ()))
        if scope != "normal":
            return messages
        return self._without_partner_duplicate_turns(messages)

    @staticmethod
    def _normalized_memory_text(content: str) -> str:
        return " ".join(content.casefold().split())

    def _partner_private_memory_keys(self) -> set[str]:
        keys = {
            self._normalized_memory_text(item.content)
            for item in (*self._partner_ltm_facts, *self._partner_ltm_prefs)
        }
        for message in self._partner_stm:
            if message.get("role") == "user":
                content = message.get("content", "")
                keys.add(self._normalized_memory_text(content))
                keys.add(self._normalized_memory_text(content[:200]))
        return keys

    def is_partner_private_memory(self, content: str) -> bool:
        """Identify legacy normal memories duplicated from retained partner data."""
        normalized = self._normalized_memory_text(content)
        return normalized in self._partner_private_memory_keys()

    def ordinary_memory_items(self, items: list) -> list:
        partner_private = self._partner_private_memory_keys()
        return [
            item for item in items
            if (
                self._normalized_memory_text(item.content) not in partner_private
                or (
                    "visibility:public" in item.tags
                    and "visibility:private" not in item.tags
                )
            )
        ]

    def ordinary_utm(self, items: list[str]) -> list[str]:
        partner_private = self._partner_private_memory_keys()
        public_items = {
            self._normalized_memory_text(item) for item in self._utm_public
        }
        return [
            item for item in items
            if (
                self._normalized_memory_text(item) not in partner_private
                or self._normalized_memory_text(item) in public_items
            )
        ]

    def _without_partner_duplicate_turns(self, messages: list) -> list:
        partner_turns = set()
        partner_messages = list(self._partner_stm)
        for index in range(len(partner_messages) - 1):
            user_message, assistant_message = partner_messages[index:index + 2]
            if (user_message.get("role") == "user"
                    and assistant_message.get("role") == "assistant"):
                partner_turns.add((
                    user_message.get("content", ""),
                    assistant_message.get("content", ""),
                ))

        filtered = []
        index = 0
        while index < len(messages):
            if index + 1 < len(messages):
                user_message, assistant_message = messages[index:index + 2]
                if (user_message.get("role") == "user"
                        and assistant_message.get("role") == "assistant"
                        and (
                            user_message.get("content", ""),
                            assistant_message.get("content", ""),
                        ) in partner_turns):
                    index += 2
                    continue
            filtered.append(messages[index])
            index += 1
        return filtered

    # ─── Partner STM ──────────────────────────────────────────────────────────

    def push_partner_stm(self, role: str, content: str):
        self.push_stm(role, content, scope="partner")

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
                visibility="private",
            )
        if is_personal_fact(t):
            self._add_to_list(
                self._partner_ltm_facts, t, LTM_FACTS_LIMIT,
                source="partner_dm", category="fact", importance=8,
                visibility="private",
            )

    # ─── UTM ──────────────────────────────────────────────────────────────────

    def _add_utm(self, text: str, visibility: str = "private"):
        t = text.strip()[:200]
        normalized = " ".join(t.casefold().split())
        if not normalized:
            return
        for index, existing in enumerate(self._utm):
            if " ".join(existing.casefold().split()) == normalized:
                # Keep recent conversational context fresh without storing a duplicate.
                existing_value = self._utm.pop(index)
                self._utm.append(existing_value)
                if visibility == "public" and normalized not in {
                    " ".join(value.casefold().split()) for value in self._utm_public
                }:
                    self._utm_public.append(existing_value)
                self._dirty = True
                return
        self._utm.append(t)
        if visibility == "public":
            self._utm_public.append(t)
        if len(self._utm) > UTM_LIMIT:
            removed = self._utm.pop(0)
            self._utm_public[:] = [value for value in self._utm_public if value != removed]
        self._utm_public[:] = self._utm_public[-UTM_LIMIT:]
        self._dirty = True

    def get_public_utm(self) -> list[str]:
        return self.ordinary_utm(list(self._utm_public))

    def get_utm_for_context(self, include_private: bool) -> list[str]:
        items = self._utm[-UTM_LIMIT:] if include_private else self._utm_public
        return self.ordinary_utm(list(items))

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
                     importance: int = 5, visibility: str = "private") -> bool:
        existing = self._find_existing(items, content)
        if existing:
            existing.touch()
            self._dirty = True
            return True
        item = MemoryItem(
            content=content[:200], layer="ltm", source=source,
            category=category, importance=importance,
            tags=[f"visibility:{visibility}"],
        )
        items.append(item)
        if len(items) > limit:
            items.sort(key=lambda m: (m.importance, m.mention_count))
            items.pop(0)
        self._dirty = True
        return True

    def remember_public(self, content: str, category: str) -> bool:
        """Save an explicit /remember item and confirm its shareable visibility."""
        if category not in {"fact", "pref"}:
            raise ValueError(f"Unsupported memory category: {category}")
        text = content.strip()[:200]
        if not text:
            return False
        target = self._ltm_prefs if category == "pref" else self._ltm_facts
        normalized = self._normalized_memory_text(text)
        item = next(
            (candidate for candidate in target
             if self._normalized_memory_text(candidate.content) == normalized),
            None,
        )
        if item is None:
            # A fuzzy match may contain additional private detail. Do not widen
            # its visibility or create a near-duplicate from the shorter request.
            if self._find_existing(target, text):
                return False
            limit = LTM_PREFS_LIMIT if category == "pref" else LTM_FACTS_LIMIT
            if not self._add_to_list(
                target, text, limit, source="user_stated", category=category,
                importance=9, visibility="public",
            ):
                return False
            item = next(
                (candidate for candidate in target
                 if self._normalized_memory_text(candidate.content) == normalized),
                None,
            )
        elif "visibility:public" not in item.tags or "visibility:private" in item.tags:
            item.tags = [
                tag for tag in item.tags
                if tag not in {"visibility:private", "visibility:public"}
            ]
            item.tags.append("visibility:public")
            item.touch()
            self._dirty = True

        if (item is None or "visibility:public" not in item.tags
                or "visibility:private" in item.tags):
            return False
        if not self.flush():
            return False
        return (
            item in target
            and "visibility:public" in item.tags
            and "visibility:private" not in item.tags
        )

    def set_memory_visibility(self, content: str, visibility: str) -> bool:
        """Explicitly reclassify an exact user memory after user confirmation."""
        if visibility not in {"private", "public"}:
            raise ValueError(f"Unsupported memory visibility: {visibility}")
        target = self._ltm_prefs if is_preference(content) else self._ltm_facts
        normalized = " ".join(content.casefold().split())
        item = next(
            (candidate for candidate in target
             if " ".join(candidate.content.casefold().split()) == normalized),
            None,
        )
        if item is None:
            return False
        item.tags = [
            tag for tag in item.tags
            if tag not in {"visibility:private", "visibility:public"}
        ]
        item.tags.append(f"visibility:{visibility}")
        self._dirty = True
        return True

    def add_fact(self, content: str, importance: int = 7, source: str = "user_stated",
                 visibility: str = "private") -> bool:
        """Add a specific fact to long-term memory."""
        t = content.strip()[:200]
        if not t:
            return False
        return self._add_to_list(
            self._ltm_facts, t, LTM_FACTS_LIMIT,
            source=source, category="fact", importance=importance,
            visibility=visibility,
        )

    def add_pref(self, content: str, importance: int = 6, source: str = "user_stated",
                 visibility: str = "private") -> bool:
        """Add a specific preference to long-term memory."""
        t = content.strip()[:200]
        if not t:
            return False
        return self._add_to_list(
            self._ltm_prefs, t, LTM_PREFS_LIMIT,
            source=source, category="pref", importance=importance,
            visibility=visibility,
        )

    # ─── LTM extraction ───────────────────────────────────────────────────────

    def extract_and_store(self, text: str, visibility: str = "private"):
        if is_filler(text):
            return
        t = text.strip()[:200]
        stored = False
        if is_preference(t):
            stored = self._add_to_list(
                self._ltm_prefs, t, LTM_PREFS_LIMIT,
                source="user_stated", category="pref", importance=6,
                visibility=visibility,
            )
        if is_personal_fact(t):
            stored = self._add_to_list(
                self._ltm_facts, t, LTM_FACTS_LIMIT,
                source="user_stated", category="fact", importance=7,
                visibility=visibility,
            ) or stored
        if is_question(t) and len(t) > 20:
            self._add_to_list(
                self._ltm_topics, t, LTM_TOPICS_LIMIT,
                source="inferred", category="topic", importance=4,
                visibility=visibility,
            )
        if t and not is_filler(t):
            self._add_utm(t, visibility=visibility)

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
            visibility="public" if text in self._utm_public else "private",
        )
        self._dirty = True

    # ─── Memory queries ───────────────────────────────────────────────────────

    def has_long_term_memory(self) -> bool:
        return bool(self._ltm_facts or self._ltm_prefs or self._ltm_topics)

    def get_important_memories(self, limit: int = 5) -> list:
        all_items = self.ordinary_memory_items(
            self._ltm_facts + self._ltm_prefs + self._ltm_topics
        )
        all_items.sort(key=lambda m: (m.importance, m.mention_count), reverse=True)
        return [m.content for m in all_items[:limit]]

    def build_memory_context(self, include_private: bool = False) -> str:
        parts = []
        for label, items, limit in (
            ("Facts", self._ltm_facts, 6),
            ("Likes/dislikes", self._ltm_prefs, 5),
            ("Topics", self._ltm_topics, 4),
        ):
            items = self.ordinary_memory_items(items)
            visible = items if include_private else [
                item for item in items
                if "visibility:public" in item.tags
                and "visibility:private" not in item.tags
            ]
            if visible:
                parts.append(f"{label}: " + "; ".join(
                    item.content for item in visible[-limit:]))
        return "\n".join(parts)

    # ─── Memory management ────────────────────────────────────────────────────

    def forget_keyword(self, keyword: str) -> bool:
        kw = keyword.lower()
        removed = False
        for lst in (
            self._ltm_facts, self._ltm_prefs, self._ltm_topics,
            self._partner_ltm_facts, self._partner_ltm_prefs,
        ):
            before = len(lst)
            lst[:] = [m for m in lst if kw not in m.content.lower()]
            if len(lst) < before:
                removed = True
        before_utm = len(self._utm)
        self._utm[:] = [x for x in self._utm if kw not in x.lower()]
        if len(self._utm) < before_utm:
            removed = True
        before_public = len(self._utm_public)
        self._utm_public[:] = [x for x in self._utm_public if kw not in x.lower()]
        if len(self._utm_public) < before_public:
            removed = True
        if removed:
            self._dirty = True
        return removed

    def clear_all_memory(self):
        for stream in self._conversation_stm.values():
            stream.clear()
        self._conversation_stm.setdefault("normal", deque(maxlen=STM_LIMIT))
        self._conversation_stm.setdefault("partner", deque(maxlen=STM_LIMIT))
        self.stm = self._conversation_stm["normal"]
        self._partner_stm = self._conversation_stm["partner"]
        self._utm.clear()
        self._utm_public.clear()
        self._ltm_facts.clear()
        self._ltm_prefs.clear()
        self._ltm_topics.clear()
        self._partner_ltm_facts.clear()
        self._partner_ltm_prefs.clear()
        self._clear_conversations = True
        self._dirty = True

    def clear_stm(self):
        for stream in self._conversation_stm.values():
            stream.clear()
        self._clear_conversations = True
        self._dirty = True

    def export_dict(
        self, requester_id: int, partner_id: int | None, channel, guild=None,
    ) -> dict:
        if requester_id != self.user_id:
            raise PermissionError("Users may only export their own memory.")
        include_partner_private = (
            partner_id == requester_id
            and is_one_to_one_dm(channel, guild, requester_id)
        )
        data = self.to_dict()
        if not include_partner_private:
            streams = data.get("conversation_stm")
            if isinstance(streams, dict) and "normal" in streams:
                streams["normal"] = self._without_partner_duplicate_turns(
                    streams["normal"]
                )
                data["stm"] = streams["normal"]
            for field in ("ltm_facts", "ltm_prefs", "ltm_topics"):
                data[field] = [
                    item for item in data.get(field, [])
                    if (
                        not self.is_partner_private_memory(item["content"])
                        or (
                            "visibility:public" in item.get("tags", [])
                            and "visibility:private" not in item.get("tags", [])
                        )
                    )
                ]
            data["utm"] = self.ordinary_utm(data.get("utm", []))
            data["utm_public"] = self.ordinary_utm(data.get("utm_public", []))
            streams = data.get("conversation_stm")
            if isinstance(streams, dict):
                data["conversation_stm"] = {
                    scope: messages
                    for scope, messages in streams.items()
                    if scope not in {"partner", "partner_normal"}
                }
            data["partner_stm"] = []
            data["partner_ltm_facts"] = []
            data["partner_ltm_prefs"] = []
            data["roleplay"] = {}
        return data
