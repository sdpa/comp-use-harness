"""
Session store — SQLite-backed persistence for sessions, subtasks, and steps.

Schema:
  sessions  (id TEXT PK, prompt TEXT, status TEXT, created_at REAL, completed_at REAL, elapsed_ms INTEGER)
  subtasks  (session_id TEXT, id TEXT, goal TEXT, subtask_type TEXT, status TEXT,
             depends_on TEXT, evidence TEXT, notes TEXT, created_at REAL)
  steps     (session_id TEXT, subtask_id TEXT, step_index INTEGER, type TEXT,
             label TEXT, detail TEXT, time TEXT, created_at REAL)
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("harness.store")

DEFAULT_DB = Path(__file__).parent.parent.parent.parent / "sessions.db"


class SessionStore:
    """Thread-safe async SQLite session store."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = str(db_path or DEFAULT_DB)
        self._lock   = asyncio.Lock()
        log.info(f"SessionStore  db={self.db_path}")

    # ── Lifecycle ─────────────────────────────────────────────

    async def init(self) -> None:
        """Create tables if they don't exist."""
        await asyncio.to_thread(self._sync_init)

    def _sync_init(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id           TEXT PRIMARY KEY,
                    prompt       TEXT NOT NULL,
                    status       TEXT NOT NULL DEFAULT 'pending',
                    created_at   REAL NOT NULL,
                    completed_at REAL,
                    elapsed_ms   INTEGER
                );
                CREATE TABLE IF NOT EXISTS subtasks (
                    session_id   TEXT NOT NULL,
                    id           TEXT NOT NULL,
                    goal         TEXT NOT NULL,
                    subtask_type TEXT NOT NULL DEFAULT 'ui_navigator',
                    status       TEXT NOT NULL DEFAULT 'pending',
                    depends_on   TEXT NOT NULL DEFAULT '[]',
                    evidence     TEXT DEFAULT '',
                    notes        TEXT DEFAULT '',
                    created_at   REAL NOT NULL,
                    PRIMARY KEY (session_id, id)
                );
                CREATE TABLE IF NOT EXISTS steps (
                    session_id  TEXT NOT NULL,
                    subtask_id  TEXT,
                    step_index  INTEGER NOT NULL,
                    type        TEXT NOT NULL,
                    label       TEXT NOT NULL,
                    detail      TEXT DEFAULT '',
                    time        TEXT DEFAULT '',
                    created_at  REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_steps_session ON steps (session_id);
                CREATE INDEX IF NOT EXISTS idx_subtasks_session ON subtasks (session_id);
            """)

    # ── Sessions ──────────────────────────────────────────────

    async def create_session(self, session_id: str, prompt: str) -> None:
        async with self._lock:
            await asyncio.to_thread(
                self._exec,
                "INSERT OR IGNORE INTO sessions (id, prompt, status, created_at) VALUES (?,?,?,?)",
                (session_id, prompt, "running", time.time()),
            )

    async def complete_session(
        self, session_id: str, status: str, elapsed_ms: int
    ) -> None:
        async with self._lock:
            await asyncio.to_thread(
                self._exec,
                "UPDATE sessions SET status=?, completed_at=?, elapsed_ms=? WHERE id=?",
                (status, time.time(), elapsed_ms, session_id),
            )

    async def list_sessions(self, limit: int = 50) -> list[dict]:
        rows = await asyncio.to_thread(
            self._fetch_all,
            "SELECT id, prompt, status, created_at, elapsed_ms "
            "FROM sessions ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [
            {
                "id":         r[0],
                "prompt":     r[1],
                "status":     r[2],
                "created_at": r[3],
                "elapsed_ms": r[4] or 0,
            }
            for r in rows
        ]

    async def get_session(self, session_id: str) -> dict | None:
        row = await asyncio.to_thread(
            self._fetch_one,
            "SELECT id, prompt, status, created_at, elapsed_ms FROM sessions WHERE id=?",
            (session_id,),
        )
        if not row:
            return None

        subtasks = await self.get_subtasks(session_id)
        steps    = await self.get_steps(session_id)

        return {
            "id":         row[0],
            "prompt":     row[1],
            "status":     row[2],
            "created_at": row[3],
            "elapsed_ms": row[4] or 0,
            "subtasks":   subtasks,
            "steps":      steps,
        }

    # ── Subtasks ──────────────────────────────────────────────

    async def upsert_subtask(
        self,
        session_id:   str,
        subtask_id:   str,
        goal:         str,
        subtask_type: str = "ui_navigator",
        depends_on:   list[str] | None = None,
    ) -> None:
        async with self._lock:
            await asyncio.to_thread(
                self._exec,
                "INSERT OR IGNORE INTO subtasks "
                "(session_id, id, goal, subtask_type, depends_on, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (
                    session_id, subtask_id, goal, subtask_type,
                    json.dumps(depends_on or []), time.time(),
                ),
            )

    async def update_subtask_status(
        self,
        session_id: str,
        subtask_id: str,
        status:     str,
        notes:      str = "",
        evidence:   str = "",
    ) -> None:
        async with self._lock:
            await asyncio.to_thread(
                self._exec,
                "UPDATE subtasks SET status=?, notes=?, evidence=? WHERE session_id=? AND id=?",
                (status, notes, evidence, session_id, subtask_id),
            )

    async def get_subtasks(self, session_id: str) -> list[dict]:
        rows = await asyncio.to_thread(
            self._fetch_all,
            "SELECT id, goal, subtask_type, status, depends_on, notes FROM subtasks WHERE session_id=? ORDER BY created_at",
            (session_id,),
        )
        return [
            {
                "id":           r[0],
                "goal":         r[1],
                "subtask_type": r[2],
                "status":       r[3],
                "depends_on":   json.loads(r[4] or "[]"),
                "notes":        r[5] or "",
            }
            for r in rows
        ]

    # ── Steps ─────────────────────────────────────────────────

    async def log_step(
        self,
        session_id: str,
        subtask_id: str | None,
        step:       dict,
    ) -> None:
        """Append a step to the database."""
        # Get next index for this session
        async with self._lock:
            await asyncio.to_thread(
                self._log_step_sync, session_id, subtask_id, step
            )

    def _log_step_sync(self, session_id: str, subtask_id: str | None, step: dict) -> None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(step_index) + 1, 0) FROM steps WHERE session_id=?",
                (session_id,),
            ).fetchone()
            idx = row[0] if row else 0
            conn.execute(
                "INSERT INTO steps (session_id, subtask_id, step_index, type, label, detail, time, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    session_id, subtask_id, idx,
                    step.get("type", ""),
                    step.get("label", ""),
                    step.get("detail", ""),
                    step.get("time", ""),
                    time.time(),
                ),
            )

    async def get_steps(
        self,
        session_id: str,
        subtask_id: str | None = None,
    ) -> list[dict]:
        if subtask_id:
            rows = await asyncio.to_thread(
                self._fetch_all,
                "SELECT type, label, detail, time, subtask_id FROM steps WHERE session_id=? AND subtask_id=? ORDER BY step_index",
                (session_id, subtask_id),
            )
        else:
            rows = await asyncio.to_thread(
                self._fetch_all,
                "SELECT type, label, detail, time, subtask_id FROM steps WHERE session_id=? ORDER BY step_index",
                (session_id,),
            )
        return [
            {
                "type":       r[0],
                "label":      r[1],
                "detail":     r[2],
                "time":       r[3],
                "subtask_id": r[4],
            }
            for r in rows
        ]

    # ── SQLite helpers ────────────────────────────────────────

    def _exec(self, sql: str, params: tuple = ()) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(sql, params)

    def _fetch_all(self, sql: str, params: tuple = ()) -> list:
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(sql, params).fetchall()

    def _fetch_one(self, sql: str, params: tuple = ()):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(sql, params).fetchone()


__all__ = ["SessionStore"]
