# -*- coding: utf-8 -*-
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
#  Author: Mauro Soria

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from functools import partial
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterator, Optional, TypeVar

T = TypeVar("T")


class SessionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class TargetStatus(str, Enum):
    PENDING = "pending"
    SCANNING = "scanning"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class DirectoryStatus(str, Enum):
    PENDING = "pending"
    SCANNING = "scanning"
    COMPLETED = "completed"
    SKIPPED = "skipped"


@dataclass
class ThreadCheckpoint:
    thread_id: int
    last_index: int
    timestamp: float = field(default_factory=time.time)


@dataclass
class SessionInfo:
    id: int
    created_at: float
    updated_at: float
    status: SessionStatus
    options: dict[str, Any]
    terminal_buffer: str = ""
    current_url_index: int = 0


class SessionDatabase:
    """
    SQLite-based session storage for dirsearch.
    Thread-safe with WAL mode for better concurrent access.

    Design inspired by patator's checkpoint system:
    - Stores last index per thread for fast resume
    - Tracks wordlist progress separately from session state
    - Uses atomic transactions for consistency
    """

    SCHEMA_VERSION = 1

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local connection with optimized settings."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(
                self.db_path,
                timeout=30.0,
                check_same_thread=False,
                isolation_level=None,  # autocommit mode for explicit transactions
            )
            conn.row_factory = sqlite3.Row
            # Performance optimizations
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA mmap_size=268435456")  # 256MB mmap
            self._local.conn = conn
        return self._local.conn

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Cursor]:
        """Context manager for write transactions with exclusive lock."""
        conn = self._get_connection()
        with self._write_lock:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            try:
                yield cursor
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def _init_database(self) -> None:
        """Initialize database schema."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.executescript("""
            -- Schema version tracking
            CREATE TABLE IF NOT EXISTS schema_info (
                version INTEGER PRIMARY KEY
            );

            -- Main session table
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                options_json TEXT NOT NULL,
                terminal_buffer TEXT DEFAULT '',
                current_url_index INTEGER DEFAULT 0
            );

            -- Targets (URLs) per session
            CREATE TABLE IF NOT EXISTS targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                order_index INTEGER NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                UNIQUE(session_id, url)
            );

            -- Directories per target
            CREATE TABLE IF NOT EXISTS directories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_id INTEGER NOT NULL,
                path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                order_index INTEGER NOT NULL,
                FOREIGN KEY (target_id) REFERENCES targets(id) ON DELETE CASCADE,
                UNIQUE(target_id, path)
            );

            -- Thread checkpoints (patator-style)
            -- Each thread stores its last processed index for fast resume
            CREATE TABLE IF NOT EXISTS thread_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                directory_id INTEGER,
                thread_id INTEGER NOT NULL,
                last_index INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                FOREIGN KEY (directory_id) REFERENCES directories(id) ON DELETE CASCADE,
                UNIQUE(session_id, directory_id, thread_id)
            );

            -- Wordlist tracking - which wordlists have been processed
            CREATE TABLE IF NOT EXISTS wordlist_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                wordlist_path TEXT NOT NULL,
                total_items INTEGER NOT NULL,
                hash TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                UNIQUE(session_id, wordlist_path)
            );

            -- Dictionary state per directory
            CREATE TABLE IF NOT EXISTS dictionary_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                directory_id INTEGER,
                main_index INTEGER NOT NULL DEFAULT 0,
                extra_index INTEGER NOT NULL DEFAULT 0,
                extra_items_json TEXT DEFAULT '[]',
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                FOREIGN KEY (directory_id) REFERENCES directories(id) ON DELETE CASCADE,
                UNIQUE(session_id, directory_id)
            );

            -- Passed URLs (already visited)
            CREATE TABLE IF NOT EXISTS passed_urls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                UNIQUE(session_id, url)
            );

            -- Indexes for fast lookups
            CREATE INDEX IF NOT EXISTS idx_targets_session ON targets(session_id);
            CREATE INDEX IF NOT EXISTS idx_directories_target ON directories(target_id);
            CREATE INDEX IF NOT EXISTS idx_checkpoints_session ON thread_checkpoints(session_id);
            CREATE INDEX IF NOT EXISTS idx_checkpoints_directory ON thread_checkpoints(directory_id);
            CREATE INDEX IF NOT EXISTS idx_dict_state_session ON dictionary_state(session_id);
            CREATE INDEX IF NOT EXISTS idx_passed_urls_session ON passed_urls(session_id);
        """)

        # Set schema version if not exists
        cursor.execute("INSERT OR IGNORE INTO schema_info (version) VALUES (?)", (self.SCHEMA_VERSION,))
        conn.commit()

    # =========================================================================
    # Session Management
    # =========================================================================

    def create_session(self, options: dict[str, Any]) -> int:
        """Create a new session and return its ID."""
        now = time.time()
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO sessions (created_at, updated_at, status, options_json)
                VALUES (?, ?, ?, ?)
                """,
                (now, now, SessionStatus.PENDING.value, json.dumps(options)),
            )
            return cursor.lastrowid

    def get_session(self, session_id: int) -> Optional[SessionInfo]:
        """Get session info by ID."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return SessionInfo(
            id=row["id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            status=SessionStatus(row["status"]),
            options=json.loads(row["options_json"]),
            terminal_buffer=row["terminal_buffer"] or "",
            current_url_index=row["current_url_index"],
        )

    def list_sessions(self, status: Optional[SessionStatus] = None) -> list[SessionInfo]:
        """List all sessions, optionally filtered by status."""
        conn = self._get_connection()
        cursor = conn.cursor()
        if status:
            cursor.execute(
                "SELECT * FROM sessions WHERE status = ? ORDER BY created_at DESC",
                (status.value,),
            )
        else:
            cursor.execute("SELECT * FROM sessions ORDER BY created_at DESC")
        return [
            SessionInfo(
                id=row["id"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                status=SessionStatus(row["status"]),
                options=json.loads(row["options_json"]),
                terminal_buffer=row["terminal_buffer"] or "",
                current_url_index=row["current_url_index"],
            )
            for row in cursor.fetchall()
        ]

    def update_session_status(self, session_id: int, status: SessionStatus) -> None:
        """Update session status."""
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE sessions SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, time.time(), session_id),
            )

    def update_session_buffer(self, session_id: int, buffer: str) -> None:
        """Update terminal buffer for session."""
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE sessions SET terminal_buffer = ?, updated_at = ? WHERE id = ?",
                (buffer, time.time(), session_id),
            )

    def update_session_url_index(self, session_id: int, index: int) -> None:
        """Update current URL index for session."""
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE sessions SET current_url_index = ?, updated_at = ? WHERE id = ?",
                (index, time.time(), session_id),
            )

    def delete_session(self, session_id: int) -> None:
        """Delete a session and all related data."""
        with self._transaction() as cursor:
            cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    # =========================================================================
    # Target Management
    # =========================================================================

    def add_targets(self, session_id: int, urls: list[str]) -> None:
        """Add targets (URLs) to a session."""
        with self._transaction() as cursor:
            for idx, url in enumerate(urls):
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO targets (session_id, url, status, order_index)
                    VALUES (?, ?, ?, ?)
                    """,
                    (session_id, url, TargetStatus.PENDING.value, idx),
                )

    def get_targets(self, session_id: int) -> list[tuple[int, str, TargetStatus]]:
        """Get all targets for a session."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, url, status FROM targets WHERE session_id = ? ORDER BY order_index",
            (session_id,),
        )
        return [(row["id"], row["url"], TargetStatus(row["status"])) for row in cursor.fetchall()]

    def get_pending_targets(self, session_id: int) -> list[tuple[int, str]]:
        """Get pending targets for a session."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, url FROM targets
            WHERE session_id = ? AND status = ?
            ORDER BY order_index
            """,
            (session_id, TargetStatus.PENDING.value),
        )
        return [(row["id"], row["url"]) for row in cursor.fetchall()]

    def update_target_status(self, target_id: int, status: TargetStatus) -> None:
        """Update target status."""
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE targets SET status = ? WHERE id = ?",
                (status.value, target_id),
            )

    # =========================================================================
    # Directory Management
    # =========================================================================

    def add_directory(self, target_id: int, path: str, order_index: int = 0) -> int:
        """Add a directory to scan for a target. Returns directory ID."""
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT OR IGNORE INTO directories (target_id, path, status, order_index)
                VALUES (?, ?, ?, ?)
                """,
                (target_id, path, DirectoryStatus.PENDING.value, order_index),
            )
            if cursor.rowcount == 0:
                # Already exists, get its ID
                cursor.execute(
                    "SELECT id FROM directories WHERE target_id = ? AND path = ?",
                    (target_id, path),
                )
                return cursor.fetchone()["id"]
            return cursor.lastrowid

    def get_directories(self, target_id: int) -> list[tuple[int, str, DirectoryStatus]]:
        """Get all directories for a target."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, path, status FROM directories WHERE target_id = ? ORDER BY order_index",
            (target_id,),
        )
        return [(row["id"], row["path"], DirectoryStatus(row["status"])) for row in cursor.fetchall()]

    def get_pending_directories(self, target_id: int) -> list[tuple[int, str]]:
        """Get pending directories for a target."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, path FROM directories
            WHERE target_id = ? AND status IN (?, ?)
            ORDER BY order_index
            """,
            (target_id, DirectoryStatus.PENDING.value, DirectoryStatus.SCANNING.value),
        )
        return [(row["id"], row["path"]) for row in cursor.fetchall()]

    def update_directory_status(self, directory_id: int, status: DirectoryStatus) -> None:
        """Update directory status."""
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE directories SET status = ? WHERE id = ?",
                (status.value, directory_id),
            )

    def get_next_directory_order(self, target_id: int) -> int:
        """Get the next order index for a new directory."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(MAX(order_index), -1) + 1 FROM directories WHERE target_id = ?",
            (target_id,),
        )
        return cursor.fetchone()[0]

    # =========================================================================
    # Thread Checkpoints (Patator-style)
    # =========================================================================

    def save_thread_checkpoint(
        self,
        session_id: int,
        thread_id: int,
        last_index: int,
        directory_id: Optional[int] = None,
    ) -> None:
        """
        Save checkpoint for a specific thread.
        This allows resuming from the exact point where each thread stopped.
        """
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO thread_checkpoints (session_id, directory_id, thread_id, last_index, timestamp)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id, directory_id, thread_id)
                DO UPDATE SET last_index = excluded.last_index, timestamp = excluded.timestamp
                """,
                (session_id, directory_id, thread_id, last_index, time.time()),
            )

    def get_thread_checkpoints(
        self, session_id: int, directory_id: Optional[int] = None
    ) -> list[ThreadCheckpoint]:
        """Get all thread checkpoints for a session/directory."""
        conn = self._get_connection()
        cursor = conn.cursor()
        if directory_id is not None:
            cursor.execute(
                """
                SELECT thread_id, last_index, timestamp
                FROM thread_checkpoints
                WHERE session_id = ? AND directory_id = ?
                ORDER BY thread_id
                """,
                (session_id, directory_id),
            )
        else:
            cursor.execute(
                """
                SELECT thread_id, last_index, timestamp
                FROM thread_checkpoints
                WHERE session_id = ? AND directory_id IS NULL
                ORDER BY thread_id
                """,
                (session_id,),
            )
        return [
            ThreadCheckpoint(
                thread_id=row["thread_id"],
                last_index=row["last_index"],
                timestamp=row["timestamp"],
            )
            for row in cursor.fetchall()
        ]

    def get_min_checkpoint_index(
        self, session_id: int, directory_id: Optional[int] = None
    ) -> int:
        """
        Get the minimum index across all threads - safe resume point.
        All items before this index have been processed by all threads.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        if directory_id is not None:
            cursor.execute(
                """
                SELECT COALESCE(MIN(last_index), 0)
                FROM thread_checkpoints
                WHERE session_id = ? AND directory_id = ?
                """,
                (session_id, directory_id),
            )
        else:
            cursor.execute(
                """
                SELECT COALESCE(MIN(last_index), 0)
                FROM thread_checkpoints
                WHERE session_id = ? AND directory_id IS NULL
                """,
                (session_id,),
            )
        return cursor.fetchone()[0]

    def clear_checkpoints(
        self, session_id: int, directory_id: Optional[int] = None
    ) -> None:
        """Clear checkpoints for a session/directory."""
        with self._transaction() as cursor:
            if directory_id is not None:
                cursor.execute(
                    "DELETE FROM thread_checkpoints WHERE session_id = ? AND directory_id = ?",
                    (session_id, directory_id),
                )
            else:
                cursor.execute(
                    "DELETE FROM thread_checkpoints WHERE session_id = ?",
                    (session_id,),
                )

    # =========================================================================
    # Dictionary State
    # =========================================================================

    def save_dictionary_state(
        self,
        session_id: int,
        main_index: int,
        extra_index: int,
        extra_items: list[str],
        directory_id: Optional[int] = None,
    ) -> None:
        """Save dictionary iteration state."""
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO dictionary_state (session_id, directory_id, main_index, extra_index, extra_items_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id, directory_id)
                DO UPDATE SET
                    main_index = excluded.main_index,
                    extra_index = excluded.extra_index,
                    extra_items_json = excluded.extra_items_json
                """,
                (session_id, directory_id, main_index, extra_index, json.dumps(extra_items)),
            )

    def get_dictionary_state(
        self, session_id: int, directory_id: Optional[int] = None
    ) -> Optional[tuple[int, int, list[str]]]:
        """Get dictionary state. Returns (main_index, extra_index, extra_items) or None."""
        conn = self._get_connection()
        cursor = conn.cursor()
        if directory_id is not None:
            cursor.execute(
                """
                SELECT main_index, extra_index, extra_items_json
                FROM dictionary_state
                WHERE session_id = ? AND directory_id = ?
                """,
                (session_id, directory_id),
            )
        else:
            cursor.execute(
                """
                SELECT main_index, extra_index, extra_items_json
                FROM dictionary_state
                WHERE session_id = ? AND directory_id IS NULL
                """,
                (session_id,),
            )
        row = cursor.fetchone()
        if row is None:
            return None
        return (row["main_index"], row["extra_index"], json.loads(row["extra_items_json"]))

    # =========================================================================
    # Wordlist Progress Tracking
    # =========================================================================

    def save_wordlist_info(
        self, session_id: int, wordlist_path: str, total_items: int, hash_value: str
    ) -> None:
        """Save wordlist metadata for verification on resume."""
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT OR REPLACE INTO wordlist_progress (session_id, wordlist_path, total_items, hash)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, wordlist_path, total_items, hash_value),
            )

    def get_wordlist_info(
        self, session_id: int, wordlist_path: str
    ) -> Optional[tuple[int, str]]:
        """Get wordlist info. Returns (total_items, hash) or None."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT total_items, hash FROM wordlist_progress WHERE session_id = ? AND wordlist_path = ?",
            (session_id, wordlist_path),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return (row["total_items"], row["hash"])

    # =========================================================================
    # Passed URLs
    # =========================================================================

    def add_passed_url(self, session_id: int, url: str) -> None:
        """Add a URL to the passed URLs set."""
        with self._transaction() as cursor:
            cursor.execute(
                "INSERT OR IGNORE INTO passed_urls (session_id, url) VALUES (?, ?)",
                (session_id, url),
            )

    def get_passed_urls(self, session_id: int) -> set[str]:
        """Get all passed URLs for a session."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT url FROM passed_urls WHERE session_id = ?",
            (session_id,),
        )
        return {row["url"] for row in cursor.fetchall()}

    def add_passed_urls_bulk(self, session_id: int, urls: set[str]) -> None:
        """Add multiple URLs to passed URLs set."""
        with self._transaction() as cursor:
            cursor.executemany(
                "INSERT OR IGNORE INTO passed_urls (session_id, url) VALUES (?, ?)",
                [(session_id, url) for url in urls],
            )

    # =========================================================================
    # Cleanup
    # =========================================================================

    def close(self) -> None:
        """Close the database connection."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None

    def vacuum(self) -> None:
        """Optimize database size."""
        conn = self._get_connection()
        conn.execute("VACUUM")

    # =========================================================================
    # Async Wrappers
    # =========================================================================

    async def _run_async(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run a synchronous function in a thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))

    async def async_save_thread_checkpoint(
        self,
        session_id: int,
        thread_id: int,
        last_index: int,
        directory_id: Optional[int] = None,
    ) -> None:
        """Async wrapper for save_thread_checkpoint."""
        await self._run_async(
            self.save_thread_checkpoint, session_id, thread_id, last_index, directory_id
        )

    async def async_save_dictionary_state(
        self,
        session_id: int,
        main_index: int,
        extra_index: int,
        extra_items: list[str],
        directory_id: Optional[int] = None,
    ) -> None:
        """Async wrapper for save_dictionary_state."""
        await self._run_async(
            self.save_dictionary_state,
            session_id,
            main_index,
            extra_index,
            extra_items,
            directory_id,
        )

    async def async_add_passed_url(self, session_id: int, url: str) -> None:
        """Async wrapper for add_passed_url."""
        await self._run_async(self.add_passed_url, session_id, url)

    async def async_update_session_status(
        self, session_id: int, status: SessionStatus
    ) -> None:
        """Async wrapper for update_session_status."""
        await self._run_async(self.update_session_status, session_id, status)

    async def async_update_directory_status(
        self, directory_id: int, status: DirectoryStatus
    ) -> None:
        """Async wrapper for update_directory_status."""
        await self._run_async(self.update_directory_status, directory_id, status)

    async def async_add_directory(
        self, target_id: int, path: str, order_index: int = 0
    ) -> int:
        """Async wrapper for add_directory."""
        return await self._run_async(self.add_directory, target_id, path, order_index)
