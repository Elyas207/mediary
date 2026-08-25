"""Versioned schema migrations.

Each migration is an ``(version, description, statements)`` tuple applied in
order inside a transaction. ``user_version`` in the SQLite header records how
far a database has progressed, so an existing library survives app updates.

Never edit a shipped migration - add a new one.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from app.utils.logging import get_logger

log = get_logger("db.migrations")

SCHEMA_VERSION = 2


_V1_STATEMENTS: tuple[str, ...] = (
    # -- Core library table ------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS media (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        filename             TEXT    NOT NULL,
        file_path            TEXT    NOT NULL,
        file_size            INTEGER NOT NULL DEFAULT 0,
        file_missing         INTEGER NOT NULL DEFAULT 0,

        source_url           TEXT    NOT NULL DEFAULT '',
        platform             TEXT    NOT NULL DEFAULT '',
        platform_id          TEXT    NOT NULL DEFAULT '',
        title                TEXT    NOT NULL DEFAULT '',
        creator              TEXT    NOT NULL DEFAULT '',
        upload_date          TEXT    NOT NULL DEFAULT '',
        downloaded_at        TEXT    NOT NULL DEFAULT '',

        media_kind           TEXT    NOT NULL DEFAULT 'other',
        category             TEXT    NOT NULL DEFAULT 'Other',

        duration             REAL    NOT NULL DEFAULT 0,
        container            TEXT    NOT NULL DEFAULT '',
        width                INTEGER NOT NULL DEFAULT 0,
        height               INTEGER NOT NULL DEFAULT 0,
        fps                  REAL    NOT NULL DEFAULT 0,
        video_codec          TEXT    NOT NULL DEFAULT '',
        audio_codec          TEXT    NOT NULL DEFAULT '',
        audio_bitrate        INTEGER NOT NULL DEFAULT 0,
        sample_rate          INTEGER NOT NULL DEFAULT 0,

        thumbnail_path       TEXT    NOT NULL DEFAULT '',

        license_type         TEXT    NOT NULL DEFAULT 'Unknown',
        license_url          TEXT    NOT NULL DEFAULT '',
        attribution_required TEXT    NOT NULL DEFAULT 'Unknown',
        license_notes        TEXT    NOT NULL DEFAULT '',

        notes                TEXT    NOT NULL DEFAULT '',
        favorite             INTEGER NOT NULL DEFAULT 0,
        play_count           INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_media_file_path ON media(file_path)",
    "CREATE INDEX IF NOT EXISTS idx_media_source_url ON media(source_url)",
    "CREATE INDEX IF NOT EXISTS idx_media_platform_id ON media(platform, platform_id)",
    "CREATE INDEX IF NOT EXISTS idx_media_category ON media(category)",
    "CREATE INDEX IF NOT EXISTS idx_media_kind ON media(media_kind)",
    "CREATE INDEX IF NOT EXISTS idx_media_favorite ON media(favorite)",
    "CREATE INDEX IF NOT EXISTS idx_media_downloaded_at ON media(downloaded_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_media_title ON media(title COLLATE NOCASE)",

    # -- Categories --------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS categories (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT    NOT NULL UNIQUE COLLATE NOCASE,
        kind        TEXT    NOT NULL DEFAULT 'other',
        folder      TEXT    NOT NULL DEFAULT '',
        builtin     INTEGER NOT NULL DEFAULT 0,
        sort_order  INTEGER NOT NULL DEFAULT 100
    )
    """,

    # -- Tags, many-to-many ------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS tags (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT    NOT NULL UNIQUE COLLATE NOCASE,
        created_at  TEXT    NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS media_tags (
        media_id    INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
        tag_id      INTEGER NOT NULL REFERENCES tags(id)  ON DELETE CASCADE,
        PRIMARY KEY (media_id, tag_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_media_tags_tag ON media_tags(tag_id)",

    # -- Download history --------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS downloads (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id      TEXT    NOT NULL DEFAULT '',
        url          TEXT    NOT NULL DEFAULT '',
        title        TEXT    NOT NULL DEFAULT '',
        platform     TEXT    NOT NULL DEFAULT '',
        category     TEXT    NOT NULL DEFAULT '',
        format_label TEXT    NOT NULL DEFAULT '',
        status       TEXT    NOT NULL DEFAULT '',
        error        TEXT    NOT NULL DEFAULT '',
        media_id     INTEGER REFERENCES media(id) ON DELETE SET NULL,
        started_at   TEXT    NOT NULL DEFAULT '',
        finished_at  TEXT    NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_downloads_started ON downloads(started_at DESC)",

    # -- Key/value app state (distinct from user settings JSON) ------------
    """
    CREATE TABLE IF NOT EXISTS app_state (
        key    TEXT PRIMARY KEY,
        value  TEXT NOT NULL DEFAULT ''
    )
    """,

)


#: Created separately from the migrations because FTS5 is an optional SQLite
#: compile-time module. If it is unavailable, search falls back to LIKE
#: matching rather than the whole database refusing to open.
FTS_STATEMENT = """
CREATE VIRTUAL TABLE IF NOT EXISTS media_fts USING fts5(
    title,
    filename,
    creator,
    category,
    tags,
    notes,
    license_notes,
    platform,
    tokenize='unicode61 remove_diacritics 2'
)
"""


def ensure_fts(connection: sqlite3.Connection) -> bool:
    """Create the search index if this SQLite build supports FTS5."""
    try:
        with connection:
            connection.execute(FTS_STATEMENT)
        return True
    except sqlite3.Error as exc:
        log.warning("FTS5 unavailable (%s); falling back to LIKE search", exc)
        return False


def _seed_categories(connection: sqlite3.Connection) -> None:
    from app.models.category import BUILTIN_CATEGORIES

    for order, category in enumerate(BUILTIN_CATEGORIES):
        connection.execute(
            "INSERT OR IGNORE INTO categories (name, kind, folder, builtin, sort_order) "
            "VALUES (?, ?, ?, 1, ?)",
            (category.name, category.kind, category.folder, order),
        )


_V2_STATEMENTS: tuple[str, ...] = (
    # How the category was decided. Smart filing learns from this: a category a
    # human deliberately chose is far better evidence than one it suggested and
    # the user simply did not override. Without the distinction the suggester
    # would train on its own guesses and reinforce them.
    #
    # Rows written before this feature keep '' and are read as deliberate,
    # which is historically accurate - back then every category was hand-picked.
    "ALTER TABLE media ADD COLUMN category_source TEXT NOT NULL DEFAULT ''",

    # User-authored filing rules. Deterministic, and they always outrank
    # anything the suggester infers.
    """
    CREATE TABLE IF NOT EXISTS filing_rules (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        field         TEXT    NOT NULL,               -- creator|platform|title_contains|url_contains
        pattern       TEXT    NOT NULL,
        category      TEXT    NOT NULL,
        enabled       INTEGER NOT NULL DEFAULT 1,
        priority      INTEGER NOT NULL DEFAULT 100,
        times_applied INTEGER NOT NULL DEFAULT 0,
        created_at    TEXT    NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_filing_rules_field ON filing_rules(field, enabled)",
    # One rule per field+pattern; re-teaching the same thing updates rather
    # than accumulating duplicates that quietly disagree with each other.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_filing_rules_match "
    "ON filing_rules(field, pattern COLLATE NOCASE)",
    "CREATE INDEX IF NOT EXISTS idx_media_creator ON media(creator COLLATE NOCASE)",
)


#: ``(version, description, statements, post_hook)``
MIGRATIONS: tuple[tuple[int, str, tuple[str, ...], Callable | None], ...] = (
    (1, "initial schema", _V1_STATEMENTS, _seed_categories),
    (2, "smart filing: rules and category provenance", _V2_STATEMENTS, None),
)


def current_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def migrate(connection: sqlite3.Connection) -> int:
    """Apply every outstanding migration. Returns the resulting version."""
    version = current_version(connection)
    if version > SCHEMA_VERSION:
        log.warning(
            "Database schema v%s is newer than this build (v%s); "
            "continuing read-only-ish. Upgrade Mediary to use it fully.",
            version,
            SCHEMA_VERSION,
        )
        return version

    for target, description, statements, post_hook in MIGRATIONS:
        if target <= version:
            continue
        log.info("Applying migration v%s: %s", target, description)
        try:
            with connection:
                for statement in statements:
                    connection.execute(statement)
                if post_hook is not None:
                    post_hook(connection)
                connection.execute(f"PRAGMA user_version = {int(target)}")
        except sqlite3.Error:
            log.exception("Migration v%s failed", target)
            raise
        version = target

    return version
