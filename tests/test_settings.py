"""Settings persistence, validation and recovery."""

from __future__ import annotations

import json

import pytest

from app.config.settings import (
    THEME_DARK,
    THEME_SYSTEM,
    Settings,
    SettingsStore,
)


class TestDefaults:
    def test_a_library_root_is_always_present(self):
        assert Settings().library_root

    def test_sensible_download_defaults(self):
        settings = Settings()
        assert settings.concurrent_downloads == 2, "should not hammer source sites"
        assert settings.default_video_format == "mp4"
        assert settings.auto_organize is True
        assert settings.auto_add_to_library is True
        assert settings.theme == THEME_SYSTEM

    def test_first_run_is_not_complete_by_default(self):
        assert Settings().first_run_complete is False


class TestClamping:
    @pytest.mark.parametrize(
        "value,expected", [(0, 1), (-5, 1), (99, 8), (3, 3), ("4", 4), (None, 2), ("x", 2)]
    )
    def test_concurrency_is_bounded(self, value, expected):
        settings = Settings(concurrent_downloads=value)
        settings.clamp()
        assert settings.concurrent_downloads == expected

    def test_retry_count_is_bounded(self):
        settings = Settings(retry_count=100)
        settings.clamp()
        assert settings.retry_count == 10

    def test_timeout_has_a_floor_and_a_ceiling(self):
        low, high = Settings(socket_timeout=1), Settings(socket_timeout=9999)
        low.clamp()
        high.clamp()
        assert low.socket_timeout == 5
        assert high.socket_timeout == 300

    def test_speed_limit_cannot_be_negative(self):
        settings = Settings(max_speed_kbps=-1)
        settings.clamp()
        assert settings.max_speed_kbps == 0

    def test_an_invalid_theme_falls_back_to_system(self):
        settings = Settings(theme="chartreuse")
        settings.clamp()
        assert settings.theme == THEME_SYSTEM

    def test_an_invalid_view_falls_back_to_grid(self):
        settings = Settings(library_view="carousel")
        settings.clamp()
        assert settings.library_view == "grid"

    def test_an_empty_filename_template_falls_back(self):
        settings = Settings(filename_template="   ")
        settings.clamp()
        assert settings.filename_template == "{title}"

    def test_custom_categories_must_be_a_list(self):
        settings = Settings(custom_categories="oops")
        settings.clamp()
        assert settings.custom_categories == []


class TestPersistence:
    def test_saves_and_reloads(self, store):
        store.set("default_category", "Music")
        store.set("concurrent_downloads", 4)
        assert SettingsStore().settings.default_category == "Music"
        assert SettingsStore().settings.concurrent_downloads == 4

    def test_writes_valid_json(self, store):
        store.set("theme", THEME_DARK)
        payload = json.loads(store.path.read_text(encoding="utf-8"))
        assert payload["theme"] == THEME_DARK
        assert payload["version"] >= 1

    def test_setting_an_unknown_key_raises(self, store):
        with pytest.raises(KeyError):
            store.set("not_a_setting", 1)

    def test_update_ignores_unknown_keys(self, store):
        store.update({"theme": THEME_DARK, "bogus": 1})
        assert store.settings.theme == THEME_DARK
        assert not hasattr(store.settings, "bogus")

    def test_values_are_clamped_on_save(self, store):
        store.set("concurrent_downloads", 500)
        assert SettingsStore().settings.concurrent_downloads == 8

    def test_missing_file_yields_defaults(self, store):
        assert not store.path.exists()
        assert store.settings.default_video_format == "mp4"

    def test_a_corrupt_file_falls_back_and_is_backed_up(self, store):
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text("{not json at all", encoding="utf-8")

        fresh = SettingsStore()
        assert fresh.settings.default_video_format == "mp4"
        assert store.path.with_suffix(".json.corrupt").exists()

    def test_a_json_array_is_treated_as_corrupt(self, store):
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text("[1, 2, 3]", encoding="utf-8")
        assert SettingsStore().settings.theme == THEME_SYSTEM

    def test_unknown_keys_in_the_file_are_dropped(self, store):
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text(
            json.dumps({"theme": "dark", "removed_in_a_later_version": True}),
            encoding="utf-8",
        )
        assert SettingsStore().settings.theme == "dark"

    def test_a_partial_file_keeps_defaults_for_everything_else(self, store):
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
        settings = SettingsStore().settings
        assert settings.theme == "dark"
        assert settings.concurrent_downloads == 2

    def test_the_save_is_atomic(self, store):
        # No temporary file should survive a successful write.
        store.set("theme", THEME_DARK)
        leftovers = list(store.path.parent.glob(".settings-*"))
        assert leftovers == []

    def test_root_path_expands_the_user_directory(self):
        settings = Settings(library_root="~/Mediary")
        assert "~" not in str(settings.root_path)
