"""Platform paths, the SQLite layer and schema migrations."""

from __future__ import annotations

import sqlite3

import pytest

from app.database.database import Database
from app.database.migrations import SCHEMA_VERSION, current_version, migrate
from app.utils import paths


class TestPlatformPaths:
    def test_every_directory_is_absolute(self):
        for directory in (
            paths.config_dir(),
            paths.data_dir(),
            paths.cache_dir(),
            paths.logs_dir(),
            paths.thumbnails_dir(),
        ):
            assert directory.is_absolute()

    def test_the_home_override_contains_everything(self, mediary_home):
        for directory in (paths.config_dir(), paths.data_dir(), paths.cache_dir()):
            assert directory.is_relative_to(mediary_home)

    def test_config_and_data_are_distinct(self, mediary_home):
        assert paths.config_dir() != paths.data_dir()

    def test_ensure_app_dirs_creates_them_all(self):
        paths.ensure_app_dirs()
        for directory in (
            paths.config_dir(),
            paths.data_dir(),
            paths.cache_dir(),
            paths.logs_dir(),
            paths.thumbnails_dir(),
        ):
            assert directory.is_dir()

    def test_ensure_app_dirs_is_idempotent(self):
        paths.ensure_app_dirs()
        paths.ensure_app_dirs()

    def test_derived_paths_sit_inside_their_directories(self):
        assert paths.database_path().parent == paths.data_dir()
        assert paths.settings_path().parent == paths.config_dir()

    def test_exactly_one_platform_predicate_is_true(self):
        assert sum([paths.is_windows(), paths.is_macos(), paths.is_linux()]) == 1

    def test_default_library_root_is_absolute(self):
        assert paths.default_library_root().is_absolute()

    def test_no_path_is_hardcoded_to_a_foreign_platform(self):
        # A regression guard: a Windows drive letter must never appear on POSIX
        # and vice versa.
        rendered = str(paths.data_dir())
        if paths.is_windows():
            assert not rendered.startswith("/")
        else:
            assert ":" not in rendered[:3]


class TestMigrations:
    def test_a_fresh_database_reaches_the_current_version(self, database):
        assert database.schema_version == SCHEMA_VERSION
        assert current_version(database.connection) == SCHEMA_VERSION

    def test_all_expected_tables_exist(self, database):
        names = {
            row["name"]
            for row in database.query("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"media", "downloads", "categories", "tags", "media_tags", "app_state"} <= names

    def test_migrations_are_idempotent(self, database):
        migrate(database.connection)
        migrate(database.connection)
        assert current_version(database.connection) == SCHEMA_VERSION

    def test_builtin_categories_are_seeded_once(self, database):
        migrate(database.connection)
        count = database.scalar("SELECT COUNT(*) FROM categories")
        assert count == 8

    def test_a_newer_schema_is_left_alone(self, database):
        database.connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 5}")
        assert migrate(database.connection) == SCHEMA_VERSION + 5

    def test_the_database_survives_being_reopened(self, mediary_home):
        path = mediary_home / "library.db"
        first = Database(path)
        first.initialise()
        first.connection.execute(
            "INSERT INTO media (filename, file_path) VALUES ('a.mp3', '/a.mp3')"
        )
        first.connection.commit()
        first.close()

        second = Database(path)
        assert second.initialise() == SCHEMA_VERSION
        assert second.scalar("SELECT COUNT(*) FROM media") == 1
        second.close()


class TestDatabase:
    def test_integrity_check_passes(self, database):
        assert database.integrity_check() == "ok"

    def test_foreign_keys_are_enforced(self, database):
        with pytest.raises(sqlite3.IntegrityError):
            with database.write() as connection:
                connection.execute(
                    "INSERT INTO media_tags (media_id, tag_id) VALUES (999, 999)"
                )

    def test_deleting_media_cascades_to_its_tags(self, database):
        with database.write() as connection:
            connection.execute(
                "INSERT INTO media (id, filename, file_path) VALUES (1, 'a', '/a')"
            )
            connection.execute("INSERT INTO tags (id, name) VALUES (1, 't')")
            connection.execute("INSERT INTO media_tags VALUES (1, 1)")

        with database.write() as connection:
            connection.execute("DELETE FROM media WHERE id = 1")

        assert database.scalar("SELECT COUNT(*) FROM media_tags") == 0

    def test_a_failed_write_rolls_back(self, database):
        with pytest.raises(sqlite3.IntegrityError):
            with database.write() as connection:
                connection.execute(
                    "INSERT INTO media (id, filename, file_path) VALUES (1, 'a', '/a')"
                )
                connection.execute(
                    "INSERT INTO media (id, filename, file_path) VALUES (1, 'b', '/b')"
                )
        assert database.scalar("SELECT COUNT(*) FROM media") == 0

    def test_the_file_path_index_is_unique(self, database):
        with database.write() as connection:
            connection.execute("INSERT INTO media (filename, file_path) VALUES ('a', '/same')")
        with pytest.raises(sqlite3.IntegrityError):
            with database.write() as connection:
                connection.execute(
                    "INSERT INTO media (filename, file_path) VALUES ('b', '/same')"
                )

    def test_each_thread_gets_its_own_connection(self, database):
        import threading

        seen = []

        def worker():
            seen.append(id(database.connection))

        main = id(database.connection)
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        assert seen[0] != main

    def test_a_worker_thread_can_write_while_the_main_thread_reads(self, mediary_home):
        import threading

        db = Database(mediary_home / "concurrent.db")
        db.initialise()

        errors = []

        def worker():
            try:
                with db.write() as connection:
                    connection.execute(
                        "INSERT INTO media (filename, file_path) VALUES ('w', '/w')"
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

        assert errors == []
        assert db.scalar("SELECT COUNT(*) FROM media") == 1
        db.close()

    def test_stats(self, database):
        stats = database.stats()
        assert stats["schema_version"] == SCHEMA_VERSION
        assert stats["media_count"] == 0

    def test_scalar_default(self, database):
        assert database.scalar("SELECT id FROM media WHERE id = -1", default="none") == "none"

    def test_close_is_safe_to_call_twice(self, database):
        database.close()
        database.close()
