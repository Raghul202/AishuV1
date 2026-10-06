"""Memory service backed by SQLite, with one-time import of legacy JSON files."""
import json
from pathlib import Path
from typing import Optional

from config.settings import DATA_DIR, USERS_DIR, GUILDS_DIR, SERVER_DIR, UTM_PROMOTION_HITS
from core.memory.database import get_database
from core.memory.user_memory import UserMemory
from core.schemas import GuildConfig
from utilities.logger import get_logger

log = get_logger("memory.manager")


class MemoryManager:
    def __init__(self):
        self._memory_ok = True
        self._user_cache: dict[int, UserMemory] = {}
        self._guild_cache: dict[int, GuildConfig] = {}
        self._quiet_cache: Optional[set[str]] = None
        try:
            Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
            self.db = get_database(str(Path(DATA_DIR) / "aishu.db"))
            self._import_legacy_json()
        except Exception as exc:
            self._memory_ok, self.db = False, None
            log.exception("SQLite memory unavailable: %s", exc)

    def _import_legacy_json(self) -> None:
        """Import once only; JSON originals remain as a recovery backup."""
        if self.db.user_count(): return
        imported = 0
        for path in Path(USERS_DIR).glob("*.json") if Path(USERS_DIR).exists() else []:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if "user_id" in data: self.db.save_user(data); imported += 1
            except (OSError, ValueError) as exc: log.warning("Skipping %s: %s", path.name, exc)
        for path in Path(GUILDS_DIR).glob("*.json") if Path(GUILDS_DIR).exists() else []:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if "guild_id" in data: self.db.save_guild(data)
            except (OSError, ValueError): pass
        for path in Path(SERVER_DIR).glob("*_topics.json") if Path(SERVER_DIR).exists() else []:
            try:
                for topic in json.loads(path.read_text(encoding="utf-8")): self.db.add_topic(int(path.name.replace("_topics.json", "")), str(topic))
            except (OSError, ValueError): pass
        if imported: log.info("Imported %s legacy user memories into SQLite", imported)

    def load(self, user_id: int, username: str = "", display_name: str = "") -> UserMemory:
        if user_id in self._user_cache:
            um = self._user_cache[user_id]
            if username: um.update_identity(username, display_name)
            return um
        if len(self._user_cache) > 800:
            # Prune non-dirty cached entries to keep RAM bounded
            for uid in list(self._user_cache.keys())[:200]:
                cached = self._user_cache.get(uid)
                if cached and not cached._dirty:
                    self._user_cache.pop(uid, None)
        data = self.db.load_user(user_id) if self._memory_ok else None
        if not data: data = {"user_id": user_id, "username": username or str(user_id), "display_name": display_name or str(user_id)}
        um = UserMemory(user_id, data, storage=self.db)
        if username: um.update_identity(username, display_name)
        self._user_cache[user_id] = um
        return um

    def get(self, user_id: int) -> Optional[UserMemory]: return self._user_cache.get(user_id)
    def is_memory_available(self) -> bool: return self._memory_ok

    def record_conversation(self, user_id, username, display_name, user_text, ai_reply):
        um = self.load(user_id, username, display_name)
        um.touch(); um.update_streak(); um.push_stm("user", user_text); um.push_stm("assistant", ai_reply); um.extract_and_store(user_text); um.save()

    def record_conversation_partner(self, user_id, username, display_name, user_text, ai_reply):
        um = self.load(user_id, username, display_name)
        um.touch(); um.update_streak(); um.push_stm("user", user_text); um.push_stm("assistant", ai_reply); um.push_partner_stm("user", user_text); um.push_partner_stm("assistant", ai_reply); um.extract_and_store(user_text); um.extract_and_store_partner(user_text); um.save()

    def detect_promotion_candidates(self, user_id: int) -> list:
        um = self.get(user_id)
        if not um: return []
        text = " ".join(m["content"].lower() for m in um.get_stm_list() if m["role"] == "user")
        return [entry for entry in um.utm if sum(text.count(word) for word in entry.lower().split() if len(word) > 4) >= UTM_PROMOTION_HITS]

    def user_count(self) -> int: return self.db.user_count() if self._memory_ok else len(self._user_cache)
    def flush_all(self):
        for um in self._user_cache.values(): um.flush()
    def clear_all_users(self):
        if self._memory_ok: self.db.clear_users()
        self._user_cache.clear()

    def get_guild_config(self, guild_id: int, guild_name: str = "") -> GuildConfig:
        if guild_id in self._guild_cache: return self._guild_cache[guild_id]
        data = self.db.get_guild(guild_id) if self._memory_ok else None
        gc = GuildConfig.from_dict(data) if data else GuildConfig.default(guild_id, guild_name)
        if guild_name and not gc.guild_name: gc.guild_name = guild_name
        self._guild_cache[guild_id] = gc
        if not data: self._save_guild_config(gc)
        return gc

    def _save_guild_config(self, gc: GuildConfig):
        if self._memory_ok: self.db.save_guild(gc.to_dict())

    def update_guild_config(self, guild_id: int, **kwargs):
        gc = self.get_guild_config(guild_id)
        for key, value in kwargs.items():
            if hasattr(gc, key): setattr(gc, key, value)
        gc.touch(); self._save_guild_config(gc)

    def record_server_topic(self, guild_id: int, topic: str):
        if guild_id and topic and self._memory_ok: self.db.add_topic(guild_id, topic)
    def get_server_topics(self, guild_id: int) -> list:
        return self.db.topics(guild_id) if guild_id and self._memory_ok else []

    def is_quiet(self, channel_id: int, guild_id: int = 0) -> bool:
        if not self._memory_ok or not self.db:
            return False
        if self._quiet_cache is None:
            self._quiet_cache = set(self.db.get_state("quiet_mode_ids", []))
        return str(channel_id) in self._quiet_cache or (bool(guild_id) and str(guild_id) in self._quiet_cache)

    def set_quiet(self, target_id: int, enabled: bool) -> bool:
        if not self._memory_ok or not self.db:
            return False
        if self._quiet_cache is None:
            self._quiet_cache = set(self.db.get_state("quiet_mode_ids", []))
        key = str(target_id)
        if enabled:
            self._quiet_cache.add(key)
        else:
            self._quiet_cache.discard(key)
        self.db.set_state("quiet_mode_ids", list(self._quiet_cache))
        return enabled


memory_manager = MemoryManager()
