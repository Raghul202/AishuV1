"""
core/afk_manager.py — Persistent AFK system.

Replaces the in-memory _afk_registry dict in chat_cog.
AFK data survives bot restarts in SQLite.

Storage format:
  {
    "user_id_str": {
      "reason":    "Out for lunch",
      "timestamp": "2026-03-14T12:00:00+00:00"
    },
    ...
  }
"""

from datetime import datetime, timezone
from typing import Optional

from utilities.logger import get_logger
from config.settings import DATABASE_FILE
from core.memory.database import get_database

log = get_logger("afk_manager")

class AfkManager:
    """
    Manages AFK state for all users, persisted to disk.
    Loaded once at startup; written on every set/clear.
    """

    def __init__(self):
        self._data: dict = {}   # user_id_str -> {reason, timestamp}
        self._db = get_database(DATABASE_FILE)
        self._load()

    # ─── Persistence ──────────────────────────────────────────────────────────

    def _load(self):
        try:
            self._data = self._db.get_state("afk", {})
            log.debug(f"AFK data loaded — {len(self._data)} entries")
        except Exception as e:
            log.error(f"Failed to load AFK data: {e}")
            self._data = {}

    def _save(self):
        try:
            self._db.set_state("afk", self._data)
        except Exception as e:
            log.error(f"Failed to save AFK data: {e}")

    # ─── Public API ───────────────────────────────────────────────────────────

    def set(self, user_id: int, reason: str = "AFK"):
        """Mark a user as AFK."""
        self._data[str(user_id)] = {
            "reason":    reason.strip() or "AFK",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._save()
        log.debug(f"AFK set: {user_id} — {reason}")

    def clear(self, user_id: int) -> bool:
        """
        Remove AFK for a user.
        Returns True if they were actually AFK (so caller can announce return).
        """
        key = str(user_id)
        if key in self._data:
            del self._data[key]
            self._save()
            log.debug(f"AFK cleared: {user_id}")
            return True
        return False

    def is_afk(self, user_id: int) -> bool:
        return str(user_id) in self._data

    def get_reason(self, user_id: int) -> Optional[str]:
        entry = self._data.get(str(user_id))
        return entry["reason"] if entry else None

    def get_entry(self, user_id: int) -> Optional[dict]:
        """Return full AFK entry dict or None."""
        return self._data.get(str(user_id))

    def since(self, user_id: int) -> Optional[str]:
        """
        Human-readable elapsed time since AFK was set.
        e.g. "2 hours ago", "just now"
        """
        entry = self._data.get(str(user_id))
        if not entry:
            return None
        try:
            ts      = datetime.fromisoformat(entry["timestamp"])
            elapsed = (datetime.now(timezone.utc) - ts).total_seconds()
            if elapsed < 60:
                return "just now"
            if elapsed < 3600:
                return f"{int(elapsed // 60)}m ago"
            if elapsed < 86400:
                return f"{int(elapsed // 3600)}h ago"
            return f"{int(elapsed // 86400)}d ago"
        except Exception:
            return None


# ─── Global singleton ─────────────────────────────────────────────────────────
afk_manager = AfkManager()
