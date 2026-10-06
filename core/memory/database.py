"""SQLite persistence for Aishu.  The database is the authoritative store."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 3

_database_instances: dict[str, "AishuDatabase"] = {}
_database_instances_lock = threading.Lock()


def get_database(path: str) -> "AishuDatabase":
    """Return the process-wide database handle for *path*.

    The bot has several services that access the same SQLite file.  Sharing the
    handle also shares its lock, so their short write transactions cannot race.
    """
    key = str(Path(path).resolve())
    with _database_instances_lock:
        database = _database_instances.get(key)
        if database is None:
            database = _database_instances[key] = AishuDatabase(key)
        return database


class AishuDatabase:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._state_cache: dict[str, Any] = {}
        self._migrate()

    @contextmanager
    def connection(self):
        # One short-lived connection per operation is safe across Discord's executor threads.
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA cache_size = -4000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _migrate(self) -> None:
        with self._lock, self.connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY, username TEXT NOT NULL, display_name TEXT NOT NULL,
                    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, message_count INTEGER NOT NULL DEFAULT 0,
                    current_streak INTEGER NOT NULL DEFAULT 0, longest_streak INTEGER NOT NULL DEFAULT 0,
                    last_streak_date TEXT NOT NULL DEFAULT '', roleplay_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    scope TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                    content TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_conversations_user_scope_id ON conversations(user_id, scope, id DESC);
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    scope TEXT NOT NULL DEFAULT 'normal', layer TEXT NOT NULL, category TEXT NOT NULL,
                    content TEXT NOT NULL, content_key TEXT NOT NULL, source TEXT NOT NULL, importance INTEGER NOT NULL,
                    confidence REAL NOT NULL, mention_count INTEGER NOT NULL DEFAULT 1, tags_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived_at TEXT,
                    UNIQUE(user_id, scope, layer, category, content_key)
                );
                CREATE INDEX IF NOT EXISTS idx_memories_lookup ON memories(user_id, scope, layer, category, archived_at, importance DESC, updated_at DESC);
                CREATE TABLE IF NOT EXISTS guild_configs (guild_id INTEGER PRIMARY KEY, data_json TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS server_topics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, topic TEXT NOT NULL, topic_key TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(guild_id, topic_key)
                );
                CREATE INDEX IF NOT EXISTS idx_server_topics_guild_id ON server_topics(guild_id, id DESC);
                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # These are database-wide settings; applying them during migration avoids
            # repeatedly changing journal mode on every short-lived connection.
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("PRAGMA synchronous = NORMAL")
            db.execute("CREATE INDEX IF NOT EXISTS idx_memories_retrieval ON memories(user_id, scope, archived_at, category, importance DESC, mention_count DESC, updated_at DESC)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_conversations_user_scope_created ON conversations(user_id, scope, created_at DESC)")
            db.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (SCHEMA_VERSION,))

    def load_user(self, user_id: int) -> dict | None:
        with self._lock, self.connection() as db:
            user = db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
            if not user:
                return None
            data = dict(user)
            data.pop("roleplay_json", None)
            data["roleplay"] = json.loads(user["roleplay_json"] or "{}")
            for scope, prefix in (("normal", ""), ("partner", "partner_")):
                rows = db.execute("SELECT * FROM conversations WHERE user_id=? AND scope=? ORDER BY id DESC LIMIT 12", (user_id, scope)).fetchall()
                data[f"{prefix}stm"] = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
                mems = db.execute("SELECT * FROM memories WHERE user_id=? AND scope=? AND archived_at IS NULL ORDER BY updated_at", (user_id, scope)).fetchall()
                buckets: dict[str, list] = {"fact": [], "pref": [], "topic": [], "utm": []}
                for r in mems:
                    target = "utm" if r["layer"] == "utm" else r["category"]
                    item = {"content": r["content"], "layer": r["layer"], "source": r["source"], "category": r["category"], "importance": r["importance"], "confidence": r["confidence"], "mention_count": r["mention_count"], "created_at": r["created_at"], "updated_at": r["updated_at"], "item_id": r["id"], "tags": json.loads(r["tags_json"])}
                    buckets.setdefault(target, []).append(item if target != "utm" else r["content"])
                if scope == "normal":
                    data.update(ltm_facts=buckets["fact"], ltm_prefs=buckets["pref"], ltm_topics=buckets["topic"], utm=buckets["utm"])
                else:
                    data.update(partner_ltm_facts=buckets["fact"], partner_ltm_prefs=buckets["pref"])
            return data

    def save_user(self, data: dict) -> None:
        def key(value: str) -> str:
            return " ".join(value.lower().split())[:240]
        with self._lock, self.connection() as db:
            db.execute("""INSERT INTO users(user_id,username,display_name,first_seen,last_seen,message_count,current_streak,longest_streak,last_streak_date,roleplay_json)
                VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,display_name=excluded.display_name,last_seen=excluded.last_seen,message_count=excluded.message_count,current_streak=excluded.current_streak,longest_streak=excluded.longest_streak,last_streak_date=excluded.last_streak_date,roleplay_json=excluded.roleplay_json""",
                (data["user_id"], data["username"], data["display_name"], data["first_seen"], data["last_seen"], data["message_count"], data["current_streak"], data["longest_streak"], data["last_streak_date"], json.dumps(data.get("roleplay", {}), ensure_ascii=False)))
            for scope, messages in (("normal", data.get("stm", [])), ("partner", data.get("partner_stm", []))):
                incoming = [
                    (m["role"], m["content"][:4000])
                    for m in messages
                    if m.get("role") in ("user", "assistant") and m.get("content")
                ][-12:]
                existing = [
                    (row["role"], row["content"])
                    for row in reversed(db.execute(
                        "SELECT role, content FROM conversations WHERE user_id=? AND scope=? ORDER BY id DESC LIMIT 12",
                        (data["user_id"], scope),
                    ).fetchall())
                ]
                # UserMemory saves a rolling snapshot.  Persist just the new
                # tail, including after an interval-delayed save, instead of
                # deleting/reinserting the entire conversation every turn.
                overlap = 0
                for size in range(min(len(existing), len(incoming)), 0, -1):
                    if existing[-size:] == incoming[:size]:
                        overlap = size
                        break
                new_rows = incoming[overlap:]
                if new_rows:
                    db.executemany(
                        "INSERT INTO conversations(user_id,scope,role,content) VALUES(?,?,?,?)",
                        [(data["user_id"], scope, role, content) for role, content in new_rows],
                    )
                db.execute("""DELETE FROM conversations
                    WHERE user_id = ? AND scope = ? AND id NOT IN (
                        SELECT id FROM conversations WHERE user_id = ? AND scope = ?
                        ORDER BY id DESC LIMIT 12
                    )""", (data["user_id"], scope, data["user_id"], scope))
            rows = []
            memory_sets = (
                ("normal", (("ltm_facts", "fact"), ("ltm_prefs", "pref"), ("ltm_topics", "topic"))),
                ("partner", (("partner_ltm_facts", "fact"), ("partner_ltm_prefs", "pref"))),
            )
            for scope, collections in memory_sets:
                for field, category in collections:
                    for item in data.get(field, []):
                        item = item if isinstance(item, dict) else {"content": str(item)}
                        content = item.get("content", "").strip()[:500]
                        if content:
                            rows.append((item.get("item_id") or f"{scope}:{category}:{key(content)}", data["user_id"], scope, "ltm", category, content, key(content), item.get("source", "inferred"), int(item.get("importance", 5)), float(item.get("confidence", .7)), int(item.get("mention_count", 1)), json.dumps(item.get("tags", [])), item.get("created_at", data["first_seen"]), item.get("updated_at", data["last_seen"])))
            for content in data.get("utm", []):
                content = str(content).strip()[:500]
                if content: rows.append((f"utm:{key(content)}", data["user_id"], "normal", "utm", "utm", content, key(content), "inferred", 3, .5, 1, "[]", data["last_seen"], data["last_seen"]))
            # Preserve existing IDs when importing legacy data whose IDs may not
            # use the current stable-key convention. This also avoids a secondary
            # unique-key collision when two old records normalize to one memory.
            existing_ids = {
                (r["scope"], r["layer"], r["category"], r["content_key"]): r["id"]
                for r in db.execute(
                    "SELECT id,scope,layer,category,content_key FROM memories WHERE user_id=?",
                    (data["user_id"],),
                )
            }
            rows = [
                (existing_ids.get((row[2], row[3], row[4], row[6]), row[0]), *row[1:])
                for row in rows
            ]

            # Upsert in place so frequently mentioned memories retain a stable row
            # and readers never observe a user with an empty memory set mid-save.
            db.executemany("""INSERT INTO memories(id,user_id,scope,layer,category,content,content_key,source,importance,confidence,mention_count,tags_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET content=excluded.content, content_key=excluded.content_key,
                source=excluded.source, importance=excluded.importance, confidence=excluded.confidence,
                mention_count=excluded.mention_count, tags_json=excluded.tags_json, updated_at=excluded.updated_at,
                archived_at=NULL""", rows)
            # Removal commands are represented by an absent item in the snapshot.
            # Limits are small, so the parameterised reconciliation remains cheap.
            if rows:
                placeholders = ",".join("?" for _ in rows)
                db.execute(f"DELETE FROM memories WHERE user_id=? AND id NOT IN ({placeholders})",
                           (data["user_id"], *(row[0] for row in rows)))
            else:
                db.execute("DELETE FROM memories WHERE user_id=?", (data["user_id"],))

    def get_guild(self, guild_id: int) -> dict | None:
        with self._lock, self.connection() as db:
            row = db.execute("SELECT data_json FROM guild_configs WHERE guild_id=?", (guild_id,)).fetchone()
            return json.loads(row["data_json"]) if row else None

    def save_guild(self, data: dict) -> None:
        with self._lock, self.connection() as db:
            db.execute("INSERT INTO guild_configs(guild_id,data_json,updated_at) VALUES(?,?,?) ON CONFLICT(guild_id) DO UPDATE SET data_json=excluded.data_json,updated_at=excluded.updated_at", (data["guild_id"], json.dumps(data, ensure_ascii=False), data["updated_at"]))

    def add_topic(self, guild_id: int, topic: str) -> None:
        with self._lock, self.connection() as db:
            db.execute("INSERT OR IGNORE INTO server_topics(guild_id,topic,topic_key) VALUES(?,?,?)", (guild_id, topic[:300], " ".join(topic.lower().split())[:300]))
            db.execute("DELETE FROM server_topics WHERE guild_id=? AND id NOT IN (SELECT id FROM server_topics WHERE guild_id=? ORDER BY id DESC LIMIT 20)", (guild_id, guild_id))

    def topics(self, guild_id: int) -> list[str]:
        with self._lock, self.connection() as db:
            rows = db.execute("SELECT topic FROM server_topics WHERE guild_id=? ORDER BY id DESC LIMIT 8", (guild_id,)).fetchall()
            return [r["topic"] for r in reversed(rows)]

    def user_count(self) -> int:
        with self._lock, self.connection() as db:
            return int(db.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def clear_users(self) -> None:
        with self._lock, self.connection() as db:
            db.execute("DELETE FROM users")

    def delete_user(self, user_id: int) -> None:
        with self._lock, self.connection() as db:
            db.execute("DELETE FROM users WHERE user_id=?", (user_id,))

    def get_state(self, key: str, default=None):
        with self._lock:
            if key in self._state_cache:
                return self._state_cache[key]
            with self.connection() as db:
                row = db.execute("SELECT value_json FROM app_state WHERE key=?", (key,)).fetchone()
                val = json.loads(row["value_json"]) if row else default
                self._state_cache[key] = val
                return val

    def set_state(self, key: str, value) -> None:
        with self._lock:
            self._state_cache[key] = value
            with self.connection() as db:
                db.execute("INSERT INTO app_state(key,value_json,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=CURRENT_TIMESTAMP", (key, json.dumps(value, ensure_ascii=False)))
