"""The library: everything that reads or writes the media index.

This is the only module that issues SQL against ``media``, ``tags`` and
``media_tags``, so the schema stays a private detail of the persistence layer.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.database.database import Database, get_database
from app.models.category import (
    BUILTIN_BY_NAME,
    KIND_AUDIO,
    KIND_VIDEO,
    make_custom_category,
)
from app.models.media import MediaItem
from app.utils.logging import get_logger

log = get_logger("library")

SORT_FIELDS: dict[str, str] = {
    "recent": "m.downloaded_at DESC, m.id DESC",
    "oldest": "m.downloaded_at ASC, m.id ASC",
    "title": "m.title COLLATE NOCASE ASC, m.id ASC",
    "title_desc": "m.title COLLATE NOCASE DESC, m.id DESC",
    "duration": "m.duration DESC, m.id DESC",
    "duration_asc": "m.duration ASC, m.id ASC",
    "size": "m.file_size DESC, m.id DESC",
    "creator": "m.creator COLLATE NOCASE ASC, m.title COLLATE NOCASE ASC",
}

SORT_LABELS: tuple[tuple[str, str], ...] = (
    ("recent", "Recently added"),
    ("oldest", "Oldest first"),
    ("title", "Title A–Z"),
    ("title_desc", "Title Z–A"),
    ("duration", "Longest"),
    ("duration_asc", "Shortest"),
    ("size", "Largest"),
    ("creator", "Creator"),
)

_MEDIA_COLUMNS = (
    "filename", "file_path", "file_size", "file_missing",
    "source_url", "platform", "platform_id", "title", "creator",
    "upload_date", "downloaded_at", "media_kind", "category",
    "duration", "container", "width", "height", "fps",
    "video_codec", "audio_codec", "audio_bitrate", "sample_rate",
    "thumbnail_path", "license_type", "license_url",
    "attribution_required", "license_notes", "notes", "favorite", "play_count",
    "category_source",
)


@dataclass
class LibraryQuery:
    """Everything the Library screen can filter by."""

    text: str = ""
    media_kind: str = ""            # "" | video | audio | other
    category: str = ""              # exact category name
    categories: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    favorites_only: bool = False
    missing_only: bool = False
    license_type: str = ""
    since: str = ""                 # ISO date lower bound on downloaded_at
    until: str = ""
    sort: str = "recent"
    limit: int = 0
    offset: int = 0

    def is_empty(self) -> bool:
        return not any(
            (
                self.text.strip(),
                self.media_kind,
                self.category,
                self.categories,
                self.tags,
                self.favorites_only,
                self.missing_only,
                self.license_type,
                self.since,
                self.until,
            )
        )


class DuplicateMatch:
    """Why an incoming download looks like something already in the library."""

    BY_URL = "url"
    BY_PLATFORM_ID = "platform_id"
    BY_PATH = "path"
    BY_FILENAME = "filename"

    def __init__(self, item: MediaItem, reason: str) -> None:
        self.item = item
        self.reason = reason

    @property
    def description(self) -> str:
        return {
            self.BY_URL: "the same source URL",
            self.BY_PLATFORM_ID: "the same video on this platform",
            self.BY_PATH: "the same file path",
            self.BY_FILENAME: "the same filename in this folder",
        }.get(self.reason, "a matching entry")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<DuplicateMatch {self.reason} id={self.item.id}>"


class LibraryService:
    """CRUD, search, tagging and integrity maintenance for the media library."""

    def __init__(self, database: Database | None = None) -> None:
        self._db = database or get_database()

    @property
    def db(self) -> Database:
        return self._db

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get(self, media_id: int) -> MediaItem | None:
        row = self._db.query_one("SELECT * FROM media WHERE id = ?", (media_id,))
        if row is None:
            return None
        return MediaItem.from_row(row, self.tags_for(media_id))

    def get_by_path(self, path: str | Path) -> MediaItem | None:
        row = self._db.query_one("SELECT * FROM media WHERE file_path = ?", (str(path),))
        if row is None:
            return None
        return MediaItem.from_row(row, self.tags_for(row["id"]))

    def count(self, query: LibraryQuery | None = None) -> int:
        sql, params = self._build_query(query or LibraryQuery(), count_only=True)
        return int(self._db.scalar(sql, params, default=0) or 0)

    def search(self, query: LibraryQuery | None = None) -> list:
        """Run a :class:`LibraryQuery` and return hydrated :class:`MediaItem`s."""
        sql, params = self._build_query(query or LibraryQuery())
        try:
            rows = self._db.query(sql, params)
        except sqlite3.Error:
            log.exception("Library search failed; returning empty result")
            return []
        if not rows:
            return []
        tag_map = self._tags_for_many([row["id"] for row in rows])
        return [MediaItem.from_row(row, tag_map.get(row["id"], [])) for row in rows]

    def _build_query(self, query: LibraryQuery, *, count_only: bool = False) -> tuple:
        where: list = []
        params: list = []
        joins = ""

        text = (query.text or "").strip()
        if text:
            fts_ids = self._fts_ids(text)
            if fts_ids is not None:
                if not fts_ids:
                    # Definitive "no matches" - short-circuit with a false clause.
                    where.append("1 = 0")
                else:
                    placeholders = ",".join("?" for _ in fts_ids)
                    where.append(f"m.id IN ({placeholders})")
                    params.extend(fts_ids)
            else:
                like = f"%{text}%"
                where.append(
                    "(m.title LIKE ? OR m.filename LIKE ? OR m.creator LIKE ? "
                    "OR m.notes LIKE ? OR m.category LIKE ? OR m.license_notes LIKE ? "
                    "OR m.platform LIKE ? OR EXISTS ("
                    "  SELECT 1 FROM media_tags mt JOIN tags t ON t.id = mt.tag_id"
                    "  WHERE mt.media_id = m.id AND t.name LIKE ?))"
                )
                params.extend([like] * 8)

        if query.media_kind:
            where.append("m.media_kind = ?")
            params.append(query.media_kind)

        names = list(query.categories)
        if query.category:
            names.append(query.category)
        if names:
            placeholders = ",".join("?" for _ in names)
            where.append(f"m.category IN ({placeholders})")
            params.extend(names)

        if query.tags:
            # Require *every* selected tag (intersection semantics).
            joins += (
                " JOIN media_tags mt_f ON mt_f.media_id = m.id"
                " JOIN tags t_f ON t_f.id = mt_f.tag_id"
            )
            placeholders = ",".join("?" for _ in query.tags)
            where.append(f"t_f.name IN ({placeholders})")
            params.extend(query.tags)

        if query.favorites_only:
            where.append("m.favorite = 1")
        if query.missing_only:
            where.append("m.file_missing = 1")
        if query.license_type:
            where.append("m.license_type = ?")
            params.append(query.license_type)
        if query.since:
            where.append("m.downloaded_at >= ?")
            params.append(query.since)
        if query.until:
            where.append("m.downloaded_at <= ?")
            params.append(query.until)

        clause = (" WHERE " + " AND ".join(where)) if where else ""
        group = " GROUP BY m.id HAVING COUNT(DISTINCT t_f.name) = ?" if query.tags else ""
        if query.tags:
            params.append(len(set(query.tags)))

        if count_only:
            if query.tags:
                return (
                    f"SELECT COUNT(*) FROM (SELECT m.id FROM media m{joins}{clause}{group})",
                    tuple(params),
                )
            return f"SELECT COUNT(*) FROM media m{joins}{clause}", tuple(params)

        order = SORT_FIELDS.get(query.sort, SORT_FIELDS["recent"])
        sql = f"SELECT m.* FROM media m{joins}{clause}{group} ORDER BY {order}"
        if query.limit:
            sql += " LIMIT ? OFFSET ?"
            params.extend([int(query.limit), int(query.offset)])
        return sql, tuple(params)

    def _fts_ids(self, text: str):
        """Row ids matching a full-text query, or ``None`` if FTS is unusable."""
        if not self._db.fts_available:
            return None
        expression = _to_fts_expression(text)
        if not expression:
            return None
        try:
            rows = self._db.query(
                "SELECT rowid FROM media_fts WHERE media_fts MATCH ? ORDER BY rank",
                (expression,),
            )
        except sqlite3.Error as exc:
            log.debug("FTS query rejected (%s); falling back to LIKE", exc)
            return None
        return [row[0] for row in rows]

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def add(self, item: MediaItem, tags: list | None = None) -> int:
        """Insert a media item and return its new id."""
        row = item.to_row()
        columns = ", ".join(_MEDIA_COLUMNS)
        placeholders = ", ".join(f":{name}" for name in _MEDIA_COLUMNS)
        with self._db.write() as connection:
            cursor = connection.execute(
                f"INSERT INTO media ({columns}) VALUES ({placeholders})", row
            )
            media_id = int(cursor.lastrowid)
        item.id = media_id
        item.downloaded_at = row["downloaded_at"]
        if tags or item.tags:
            self.set_tags(media_id, list(tags or item.tags))
        else:
            self._reindex(media_id)
        log.info("Added to library: %s (id=%s)", item.filename, media_id)
        return media_id

    def update(self, item: MediaItem) -> bool:
        if not item.id:
            raise ValueError("Cannot update a MediaItem without an id")
        row = item.to_row()
        row["id"] = item.id
        assignments = ", ".join(f"{name} = :{name}" for name in _MEDIA_COLUMNS)
        with self._db.write() as connection:
            connection.execute(f"UPDATE media SET {assignments} WHERE id = :id", row)
        self._reindex(item.id)
        return True

    def update_fields(self, media_id: int, **values) -> bool:
        """Patch individual columns without loading the whole item."""
        allowed = {k: v for k, v in values.items() if k in _MEDIA_COLUMNS}
        if not allowed:
            return False
        assignments = ", ".join(f"{name} = ?" for name in allowed)
        params = list(allowed.values()) + [media_id]
        with self._db.write() as connection:
            connection.execute(f"UPDATE media SET {assignments} WHERE id = ?", params)
        self._reindex(media_id)
        return True

    def set_favorite(self, media_id: int, favorite: bool) -> bool:
        with self._db.write() as connection:
            connection.execute(
                "UPDATE media SET favorite = ? WHERE id = ?", (int(bool(favorite)), media_id)
            )
        return True

    def toggle_favorite(self, media_id: int) -> bool:
        current = self._db.scalar("SELECT favorite FROM media WHERE id = ?", (media_id,), 0)
        new_value = not bool(current)
        self.set_favorite(media_id, new_value)
        return new_value

    def set_category(self, media_id: int, category: str) -> bool:
        kind = BUILTIN_BY_NAME[category].kind if category in BUILTIN_BY_NAME else None
        values = {"category": category}
        if kind:
            values["media_kind"] = kind
        return self.update_fields(media_id, **values)

    def increment_play_count(self, media_id: int) -> None:
        try:
            with self._db.write() as connection:
                connection.execute(
                    "UPDATE media SET play_count = play_count + 1 WHERE id = ?", (media_id,)
                )
        except sqlite3.Error:
            log.debug("Could not increment play count for %s", media_id)

    def remove(self, media_id: int) -> bool:
        """Remove the library entry. The file on disk is left untouched."""
        with self._db.write() as connection:
            connection.execute("DELETE FROM media WHERE id = ?", (media_id,))
        self._delete_index(media_id)
        log.info("Removed from library: id=%s (file kept)", media_id)
        return True

    def remove_many(self, media_ids: list) -> int:
        if not media_ids:
            return 0
        placeholders = ",".join("?" for _ in media_ids)
        with self._db.write() as connection:
            connection.execute(f"DELETE FROM media WHERE id IN ({placeholders})", tuple(media_ids))
        for media_id in media_ids:
            self._delete_index(media_id)
        return len(media_ids)

    def delete_file(self, media_id: int, *, remove_entry: bool = True) -> tuple:
        """Delete the file from disk *and* (by default) the library entry.

        Returns ``(ok, message)``. Never raises for an ordinary OS failure.
        """
        item = self.get(media_id)
        if item is None:
            return False, "That item is no longer in the library."

        path = Path(item.file_path) if item.file_path else None
        if path and path.exists():
            try:
                path.unlink()
                log.info("Deleted file %s", path)
            except OSError as exc:
                log.error("Could not delete %s: %s", path, exc)
                return False, f"Could not delete the file: {exc.strerror or exc}"
        if item.thumbnail_path:
            try:
                Path(item.thumbnail_path).unlink(missing_ok=True)
            except OSError:
                pass
        if remove_entry:
            self.remove(media_id)
        return True, "File deleted."

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    def tags_for(self, media_id: int) -> list:
        rows = self._db.query(
            "SELECT t.name FROM tags t JOIN media_tags mt ON mt.tag_id = t.id "
            "WHERE mt.media_id = ? ORDER BY t.name COLLATE NOCASE",
            (media_id,),
        )
        return [row[0] for row in rows]

    def _tags_for_many(self, media_ids: list) -> dict:
        if not media_ids:
            return {}
        placeholders = ",".join("?" for _ in media_ids)
        rows = self._db.query(
            f"SELECT mt.media_id, t.name FROM media_tags mt "
            f"JOIN tags t ON t.id = mt.tag_id WHERE mt.media_id IN ({placeholders}) "
            f"ORDER BY t.name COLLATE NOCASE",
            tuple(media_ids),
        )
        result: dict = {}
        for media_id, name in rows:
            result.setdefault(media_id, []).append(name)
        return result

    def all_tags(self, *, with_counts: bool = False) -> list:
        if with_counts:
            rows = self._db.query(
                "SELECT t.name, COUNT(mt.media_id) AS n FROM tags t "
                "LEFT JOIN media_tags mt ON mt.tag_id = t.id "
                "GROUP BY t.id ORDER BY n DESC, t.name COLLATE NOCASE"
            )
            return [(row[0], row[1]) for row in rows]
        rows = self._db.query("SELECT name FROM tags ORDER BY name COLLATE NOCASE")
        return [row[0] for row in rows]

    def ensure_tag(self, name: str) -> int:
        clean = _clean_tag(name)
        if not clean:
            raise ValueError("Tag name cannot be empty")
        with self._db.write() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO tags (name, created_at) VALUES (?, ?)",
                (clean, datetime.now().isoformat(timespec="seconds")),
            )
        return int(
            self._db.scalar("SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (clean,))
        )

    def add_tag(self, media_id: int, name: str) -> bool:
        clean = _clean_tag(name)
        if not clean:
            return False
        tag_id = self.ensure_tag(clean)
        with self._db.write() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO media_tags (media_id, tag_id) VALUES (?, ?)",
                (media_id, tag_id),
            )
        self._reindex(media_id)
        return True

    def remove_tag(self, media_id: int, name: str) -> bool:
        with self._db.write() as connection:
            connection.execute(
                "DELETE FROM media_tags WHERE media_id = ? AND tag_id = "
                "(SELECT id FROM tags WHERE name = ? COLLATE NOCASE)",
                (media_id, _clean_tag(name)),
            )
        self._reindex(media_id)
        return True

    def set_tags(self, media_id: int, names: list) -> None:
        cleaned = []
        for name in names:
            clean = _clean_tag(name)
            if clean and clean.lower() not in {c.lower() for c in cleaned}:
                cleaned.append(clean)
        tag_ids = [self.ensure_tag(name) for name in cleaned]
        with self._db.write() as connection:
            connection.execute("DELETE FROM media_tags WHERE media_id = ?", (media_id,))
            connection.executemany(
                "INSERT OR IGNORE INTO media_tags (media_id, tag_id) VALUES (?, ?)",
                [(media_id, tag_id) for tag_id in tag_ids],
            )
        self._reindex(media_id)

    def rename_tag(self, old: str, new: str) -> bool:
        clean_new = _clean_tag(new)
        if not clean_new:
            return False
        existing = self._db.query_one(
            "SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (clean_new,)
        )
        old_row = self._db.query_one(
            "SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (_clean_tag(old),)
        )
        if old_row is None:
            return False
        with self._db.write() as connection:
            if existing is not None and existing[0] != old_row[0]:
                # Merge into the existing tag rather than failing on the unique index.
                connection.execute(
                    "UPDATE OR IGNORE media_tags SET tag_id = ? WHERE tag_id = ?",
                    (existing[0], old_row[0]),
                )
                connection.execute("DELETE FROM media_tags WHERE tag_id = ?", (old_row[0],))
                connection.execute("DELETE FROM tags WHERE id = ?", (old_row[0],))
            else:
                connection.execute(
                    "UPDATE tags SET name = ? WHERE id = ?", (clean_new, old_row[0])
                )
        self.rebuild_index()
        return True

    def delete_tag(self, name: str) -> bool:
        with self._db.write() as connection:
            connection.execute("DELETE FROM tags WHERE name = ? COLLATE NOCASE", (_clean_tag(name),))
        self.rebuild_index()
        return True

    def prune_orphan_tags(self) -> int:
        with self._db.write() as connection:
            cursor = connection.execute(
                "DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM media_tags)"
            )
        return cursor.rowcount or 0

    # ------------------------------------------------------------------
    # Categories
    # ------------------------------------------------------------------

    def all_categories(self) -> list:
        rows = self._db.query(
            "SELECT name, kind, folder, builtin FROM categories ORDER BY sort_order, name"
        )
        return [dict(row) for row in rows]

    def category_counts(self) -> dict:
        rows = self._db.query("SELECT category, COUNT(*) FROM media GROUP BY category")
        return {row[0]: row[1] for row in rows}

    def kind_counts(self) -> dict:
        rows = self._db.query("SELECT media_kind, COUNT(*) FROM media GROUP BY media_kind")
        counts = {row[0]: row[1] for row in rows}
        counts["all"] = sum(counts.values())
        counts["favorites"] = int(
            self._db.scalar("SELECT COUNT(*) FROM media WHERE favorite = 1", default=0) or 0
        )
        return counts

    def add_category(self, name: str, kind: str) -> bool:
        category = make_custom_category(name, kind)
        try:
            with self._db.write() as connection:
                connection.execute(
                    "INSERT OR IGNORE INTO categories (name, kind, folder, builtin, sort_order) "
                    "VALUES (?, ?, ?, 0, 500)",
                    (category.name, category.kind, category.folder),
                )
            return True
        except sqlite3.Error:
            log.exception("Could not create category %r", name)
            return False

    def delete_category(self, name: str) -> bool:
        """Delete a custom category. Media in it is moved to ``Other``."""
        if name in BUILTIN_BY_NAME:
            return False
        with self._db.write() as connection:
            connection.execute("UPDATE media SET category = 'Other' WHERE category = ?", (name,))
            connection.execute("DELETE FROM categories WHERE name = ? AND builtin = 0", (name,))
        self.rebuild_index()
        return True

    # ------------------------------------------------------------------
    # Duplicate detection
    # ------------------------------------------------------------------

    def find_duplicate(
        self,
        *,
        source_url: str = "",
        platform: str = "",
        platform_id: str = "",
        file_path: str = "",
        filename: str = "",
    ) -> DuplicateMatch | None:
        """Return the strongest duplicate signal for an incoming download."""
        if source_url:
            row = self._db.query_one(
                "SELECT * FROM media WHERE source_url = ? ORDER BY id LIMIT 1", (source_url,)
            )
            if row is not None:
                return DuplicateMatch(self._hydrate(row), DuplicateMatch.BY_URL)

        if platform and platform_id:
            row = self._db.query_one(
                "SELECT * FROM media WHERE platform = ? AND platform_id = ? "
                "AND platform_id != '' ORDER BY id LIMIT 1",
                (platform, platform_id),
            )
            if row is not None:
                return DuplicateMatch(self._hydrate(row), DuplicateMatch.BY_PLATFORM_ID)

        if file_path:
            row = self._db.query_one(
                "SELECT * FROM media WHERE file_path = ? LIMIT 1", (str(file_path),)
            )
            if row is not None:
                return DuplicateMatch(self._hydrate(row), DuplicateMatch.BY_PATH)

        if filename:
            row = self._db.query_one(
                "SELECT * FROM media WHERE filename = ? COLLATE NOCASE ORDER BY id LIMIT 1",
                (filename,),
            )
            if row is not None:
                return DuplicateMatch(self._hydrate(row), DuplicateMatch.BY_FILENAME)

        return None

    def _hydrate(self, row) -> MediaItem:
        return MediaItem.from_row(row, self.tags_for(row["id"]))

    # ------------------------------------------------------------------
    # Integrity / rescan
    # ------------------------------------------------------------------

    def verify_files(self) -> dict:
        """Flag entries whose file has vanished; clear the flag when it returns."""
        rows = self._db.query("SELECT id, file_path, file_missing, file_size FROM media")
        newly_missing, recovered, updated_size = 0, 0, 0
        with self._db.write() as connection:
            for row in rows:
                path = Path(row["file_path"]) if row["file_path"] else None
                exists = bool(path and path.is_file())
                if exists and row["file_missing"]:
                    connection.execute(
                        "UPDATE media SET file_missing = 0 WHERE id = ?", (row["id"],)
                    )
                    recovered += 1
                elif not exists and not row["file_missing"]:
                    connection.execute(
                        "UPDATE media SET file_missing = 1 WHERE id = ?", (row["id"],)
                    )
                    newly_missing += 1
                if exists:
                    try:
                        size = path.stat().st_size
                    except OSError:
                        continue
                    if size != row["file_size"]:
                        connection.execute(
                            "UPDATE media SET file_size = ? WHERE id = ?", (size, row["id"])
                        )
                        updated_size += 1
        return {"missing": newly_missing, "recovered": recovered, "resized": updated_size}

    def relocate_missing(self, search_roots: list) -> int:
        """Try to re-point missing entries at a file of the same name.

        This is how Mediary recovers when a user moves or renames the library
        folder outside the app.
        """
        missing = self._db.query(
            "SELECT id, filename FROM media WHERE file_missing = 1 AND filename != ''"
        )
        if not missing:
            return 0

        index: dict = {}
        for root in search_roots:
            root_path = Path(root)
            if not root_path.is_dir():
                continue
            for candidate in root_path.rglob("*"):
                if candidate.is_file():
                    index.setdefault(candidate.name.lower(), candidate)

        relocated = 0
        with self._db.write() as connection:
            for row in missing:
                candidate = index.get(str(row["filename"]).lower())
                if candidate is None:
                    continue
                taken = connection.execute(
                    "SELECT id FROM media WHERE file_path = ? AND id != ?",
                    (str(candidate), row["id"]),
                ).fetchone()
                if taken is not None:
                    continue
                try:
                    size = candidate.stat().st_size
                except OSError:
                    size = 0
                connection.execute(
                    "UPDATE media SET file_path = ?, file_missing = 0, file_size = ? WHERE id = ?",
                    (str(candidate), size, row["id"]),
                )
                relocated += 1
        if relocated:
            log.info("Relocated %s missing file(s)", relocated)
        return relocated

    def import_file(
        self,
        path: Path,
        *,
        category: str,
        media_kind: str,
        probe: dict | None = None,
    ) -> int | None:
        """Index a file that already exists on disk (used by Rescan Library)."""
        if self.get_by_path(path) is not None:
            return None
        try:
            size = path.stat().st_size
            mtime = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
        except OSError:
            return None
        item = MediaItem(
            filename=path.name,
            file_path=str(path),
            file_size=size,
            title=path.stem,
            media_kind=media_kind,
            category=category,
            container=path.suffix.lstrip("."),
            downloaded_at=mtime,
        )
        if probe:
            item.duration = probe.get("duration", 0.0) or 0.0
            item.width = probe.get("width", 0) or 0
            item.height = probe.get("height", 0) or 0
            item.fps = probe.get("fps", 0.0) or 0.0
            item.video_codec = probe.get("video_codec", "") or ""
            item.audio_codec = probe.get("audio_codec", "") or ""
            item.audio_bitrate = probe.get("audio_bitrate", 0) or 0
            item.sample_rate = probe.get("sample_rate", 0) or 0
        return self.add(item)

    # ------------------------------------------------------------------
    # Filing: evidence and rules
    # ------------------------------------------------------------------

    def category_history(
        self,
        *,
        creator: str = "",
        platform: str = "",
        media_kind: str = "",
    ) -> list:
        """Weighted category counts for matching past downloads.

        Returns ``[(category, weight, raw_count, deliberate_count), ...]``,
        heaviest first. The weight discounts categories Mediary itself
        suggested, so the suggester cannot train on its own output - see
        ``models/filing.SOURCE_WEIGHTS``. ``deliberate_count`` is how many of
        those the user actually chose, as opposed to simply not correcting.
        """
        from app.models.filing import is_deliberate, source_weight

        where: list = []
        params: list = []
        if creator:
            where.append("creator = ? COLLATE NOCASE")
            params.append(creator)
        if platform:
            where.append("platform = ? COLLATE NOCASE")
            params.append(platform)
        if media_kind:
            where.append("media_kind = ?")
            params.append(media_kind)
        if not where:
            return []

        rows = self._db.query(
            "SELECT category, category_source, COUNT(*) AS n FROM media "
            f"WHERE {' AND '.join(where)} GROUP BY category, category_source",
            tuple(params),
        )

        totals: dict = {}
        counts: dict = {}
        deliberate: dict = {}
        for row in rows:
            category = row["category"]
            source = row["category_source"]
            count = int(row["n"])
            totals[category] = totals.get(category, 0.0) + source_weight(source) * count
            counts[category] = counts.get(category, 0) + count
            if is_deliberate(source):
                deliberate[category] = deliberate.get(category, 0) + count

        return sorted(
            (
                (name, weight, counts[name], deliberate.get(name, 0))
                for name, weight in totals.items()
            ),
            key=lambda entry: entry[1],
            reverse=True,
        )

    def title_token_counts(self, media_kind: str = "") -> tuple:
        """``(token -> {category: weight}, {category: weight}, item_count)``.

        The corpus for the title model. Small enough to compute on demand for a
        personal library, and the caller caches it between changes.
        """
        from app.models.filing import source_weight

        clause = " WHERE media_kind = ?" if media_kind else ""
        params = (media_kind,) if media_kind else ()
        rows = self._db.query(
            f"SELECT title, category, category_source FROM media{clause}", params
        )

        tokens: dict = {}
        totals: dict = {}
        for row in rows:
            weight = source_weight(row["category_source"])
            category = row["category"]
            totals[category] = totals.get(category, 0.0) + weight
            for token in _tokenise(row["title"]):
                bucket = tokens.setdefault(token, {})
                bucket[category] = bucket.get(category, 0.0) + weight
        return tokens, totals, len(rows)

    # -- Rules ------------------------------------------------------------

    def all_rules(self, *, enabled_only: bool = False) -> list:
        from app.models.filing import FilingRule

        clause = " WHERE enabled = 1" if enabled_only else ""
        rows = self._db.query(
            f"SELECT * FROM filing_rules{clause} ORDER BY priority, id"
        )
        return [FilingRule.from_row(row) for row in rows]

    def save_rule(self, rule) -> int:
        """Create or update a rule. Re-teaching the same match updates it.

        Two rules matching the same thing and disagreeing would make filing
        depend on row order, so the unique index collapses them instead.
        """
        row = rule.to_row()
        with self._db.write() as connection:
            if rule.id:
                row["id"] = rule.id
                connection.execute(
                    "UPDATE filing_rules SET field = :field, pattern = :pattern, "
                    "category = :category, enabled = :enabled, priority = :priority "
                    "WHERE id = :id",
                    row,
                )
                return int(rule.id)

            cursor = connection.execute(
                "INSERT INTO filing_rules (field, pattern, category, enabled, priority, "
                "times_applied, created_at) VALUES (:field, :pattern, :category, "
                ":enabled, :priority, :times_applied, :created_at) "
                "ON CONFLICT(field, pattern COLLATE NOCASE) DO UPDATE SET "
                "category = excluded.category, enabled = 1",
                row,
            )
            if cursor.lastrowid:
                return int(cursor.lastrowid)

        existing = self._db.query_one(
            "SELECT id FROM filing_rules WHERE field = ? AND pattern = ? COLLATE NOCASE",
            (rule.field, rule.pattern),
        )
        return int(existing[0]) if existing else 0

    def delete_rule(self, rule_id: int) -> bool:
        with self._db.write() as connection:
            connection.execute("DELETE FROM filing_rules WHERE id = ?", (rule_id,))
        return True

    def set_rule_enabled(self, rule_id: int, enabled: bool) -> bool:
        with self._db.write() as connection:
            connection.execute(
                "UPDATE filing_rules SET enabled = ? WHERE id = ?",
                (int(bool(enabled)), rule_id),
            )
        return True

    def note_rule_applied(self, rule_id: int) -> None:
        """Count a firing, so the rules screen can show which ones earn their keep."""
        try:
            with self._db.write() as connection:
                connection.execute(
                    "UPDATE filing_rules SET times_applied = times_applied + 1 WHERE id = ?",
                    (rule_id,),
                )
        except sqlite3.Error:
            log.debug("Could not record rule %s firing", rule_id)

    # ------------------------------------------------------------------
    # Download history
    # ------------------------------------------------------------------

    def record_download(
        self,
        *,
        task_id: str,
        url: str,
        title: str,
        platform: str,
        category: str,
        format_label: str,
        status: str,
        error: str = "",
        media_id: int | None = None,
        started_at: str = "",
    ) -> None:
        try:
            with self._db.write() as connection:
                connection.execute(
                    "INSERT INTO downloads (task_id, url, title, platform, category, "
                    "format_label, status, error, media_id, started_at, finished_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        task_id, url, title, platform, category, format_label, status,
                        error, media_id, started_at,
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                )
        except sqlite3.Error:
            log.debug("Could not record download history for %s", task_id)

    def recent_downloads(self, limit: int = 50) -> list:
        return [
            dict(row)
            for row in self._db.query(
                "SELECT * FROM downloads ORDER BY id DESC LIMIT ?", (int(limit),)
            )
        ]

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        row = self._db.query_one(
            "SELECT COUNT(*) AS items, COALESCE(SUM(file_size), 0) AS bytes, "
            "COALESCE(SUM(duration), 0) AS seconds, "
            "COALESCE(SUM(file_missing), 0) AS missing FROM media"
        )
        return {
            "items": row["items"] if row else 0,
            "bytes": row["bytes"] if row else 0,
            "seconds": row["seconds"] if row else 0,
            "missing": row["missing"] if row else 0,
        }

    # ------------------------------------------------------------------
    # Search index maintenance
    # ------------------------------------------------------------------

    def _reindex(self, media_id: int) -> None:
        if not self._db.fts_available:
            return
        row = self._db.query_one("SELECT * FROM media WHERE id = ?", (media_id,))
        if row is None:
            self._delete_index(media_id)
            return
        tags = " ".join(self.tags_for(media_id))
        try:
            with self._db.write() as connection:
                connection.execute("DELETE FROM media_fts WHERE rowid = ?", (media_id,))
                connection.execute(
                    "INSERT INTO media_fts (rowid, title, filename, creator, category, "
                    "tags, notes, license_notes, platform) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        media_id, row["title"], row["filename"], row["creator"],
                        row["category"], tags, row["notes"], row["license_notes"],
                        row["platform"],
                    ),
                )
        except sqlite3.Error:
            log.debug("Could not reindex media %s", media_id)

    def _delete_index(self, media_id: int) -> None:
        if not self._db.fts_available:
            return
        try:
            with self._db.write() as connection:
                connection.execute("DELETE FROM media_fts WHERE rowid = ?", (media_id,))
        except sqlite3.Error:
            pass

    def rebuild_index(self) -> int:
        """Rebuild the whole search index from the media table."""
        if not self._db.fts_available:
            return 0
        rows = self._db.query("SELECT * FROM media")
        tag_map = self._tags_for_many([row["id"] for row in rows])
        try:
            with self._db.write() as connection:
                connection.execute("DELETE FROM media_fts")
                connection.executemany(
                    "INSERT INTO media_fts (rowid, title, filename, creator, category, "
                    "tags, notes, license_notes, platform) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            row["id"], row["title"], row["filename"], row["creator"],
                            row["category"], " ".join(tag_map.get(row["id"], [])),
                            row["notes"], row["license_notes"], row["platform"],
                        )
                        for row in rows
                    ],
                )
        except sqlite3.Error:
            log.exception("Could not rebuild search index")
            return 0
        return len(rows)


def _clean_tag(name: str) -> str:
    return " ".join(str(name or "").split()).strip()


def _to_fts_expression(text: str) -> str:
    """Turn user input into a safe FTS5 MATCH expression with prefix matching.

    Every token is quoted so punctuation cannot be read as FTS syntax, and a
    trailing ``*`` gives the partial matching people expect while typing.
    """
    tokens = [t for t in _split_terms(text) if t]
    if not tokens:
        return ""
    return " AND ".join(f'"{token}"*' for token in tokens)


def _split_terms(text: str) -> list:
    cleaned = []
    current = []
    for char in str(text):
        if char.isalnum() or char in "_'":
            current.append(char)
        else:
            if current:
                cleaned.append("".join(current).replace('"', ""))
                current = []
    if current:
        cleaned.append("".join(current).replace('"', ""))
    return cleaned


__all__ = [
    "DuplicateMatch",
    "LibraryQuery",
    "LibraryService",
    "SORT_LABELS",
    "KIND_AUDIO",
    "KIND_VIDEO",
]


#: Words too common to say anything about where an item belongs.
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "in", "on", "for", "to", "with",
    "by", "from", "at", "is", "it", "this", "that", "my", "your", "official",
    "video", "audio", "hd", "4k", "full", "new", "free", "download", "part",
    "feat", "ft", "remix", "version", "clip", "sound", "effect", "effects",
})


def _tokenise(text: str) -> set:
    """Lowercase word tokens from a title, minus noise.

    Numbers go too: "Whoosh 03" and "Whoosh 07" are the same kind of thing, and
    keeping the digits would just scatter the evidence across many useless
    tokens.
    """
    words = re.findall(r"[^\W\d_]{3,}", (text or "").casefold(), re.UNICODE)
    return {word for word in words if word not in _STOPWORDS}
