"""SQLite connection management.

Qt runs library queries from the GUI thread and from worker threads, so each
thread gets its own connection via ``threading.local``. WAL mode lets a worker
write while the UI reads.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.database.migrations import current_version, ensure_fts, migrate
from app.utils.logging import get_logger
from app.utils.paths import database_path

log = get_logger("db")


class Database:
    """A thread-safe handle to the Mediary SQLite library."""

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path is not None else database_path()
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self._connections: list = []
        self._connections_lock = threading.Lock()
        self._schema_version = 0
        self._initialised = False
        self._fts_available = False

    # -- Lifecycle --------------------------------------------------------

    @property
    def path(self) -> Path:
        return self._path

    @property
    def schema_version(self) -> int:
        return self._schema_version

    def initialise(self) -> int:
        """Create the file, apply migrations and return the schema version."""
        if self._path.parent and str(self._path) != ":memory:":
            self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = self.connection
        self._schema_version = migrate(connection)
        self._fts_available = ensure_fts(connection)
        self._initialised = True
        log.info(
            "Library database ready at %s (schema v%s, fts=%s)",
            self._path,
            self._schema_version,
            self._fts_available,
        )
        return self._schema_version

    @property
    def fts_available(self) -> bool:
        return self._fts_available

    def _configure(self, connection: sqlite3.Connection) -> None:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        if str(self._path) != ":memory:":
            connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA temp_store = MEMORY")

    @property
    def connection(self) -> sqlite3.Connection:
        """The calling thread's connection, opened lazily."""
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(
                str(self._path),
                timeout=10.0,
                isolation_level="DEFERRED",
                check_same_thread=False,
            )
            self._configure(connection)
            self._local.connection = connection
            with self._connections_lock:
                self._connections.append(connection)
        return connection

    def close(self) -> None:
        """Close every connection this database has handed out."""
        with self._connections_lock:
            connections, self._connections = self._connections, []
        for connection in connections:
            try:
                connection.close()
            except sqlite3.Error:
                pass
        self._local = threading.local()

    # -- Query helpers ----------------------------------------------------

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """Serialised write transaction; commits on success, rolls back on error."""
        connection = self.connection
        with self._write_lock:
            try:
                yield connection
                connection.commit()
            except BaseException:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
                raise

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        return self.connection.execute(sql, params)

    def query(self, sql: str, params: tuple | dict = ()) -> list:
        return self.connection.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple | dict = ()):
        return self.connection.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: tuple | dict = (), default=None):
        row = self.query_one(sql, params)
        if row is None:
            return default
        return row[0]

    # -- Maintenance ------------------------------------------------------

    def vacuum(self) -> None:
        connection = self.connection
        connection.commit()
        connection.execute("VACUUM")

    def integrity_check(self) -> str:
        return str(self.scalar("PRAGMA integrity_check", default="unknown"))

    def stats(self) -> dict:
        return {
            "path": str(self._path),
            "schema_version": current_version(self.connection),
            "media_count": self.scalar("SELECT COUNT(*) FROM media", default=0),
            "tag_count": self.scalar("SELECT COUNT(*) FROM tags", default=0),
            "size_bytes": self._path.stat().st_size if self._path.is_file() else 0,
        }


_database: Database | None = None


def get_database() -> Database:
    """Process-wide database handle, initialised on first use."""
    global _database
    if _database is None:
        _database = Database()
        _database.initialise()
    return _database


def set_database(database: Database | None) -> None:
    """Replace the process-wide handle (used by tests)."""
    global _database
    _database = database
