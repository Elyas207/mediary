"""Removing Mediary's local data.

The invariant these protect: nothing is deleted that the user did not tick, and
the media library is never collateral damage.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.uninstall_service import UninstallService
from app.utils.paths import cache_dir, config_dir, data_dir, logs_dir


@pytest.fixture
def populated_dirs(mediary_home, settings):
    """Put a recognisable file in every directory uninstall can touch."""
    from app.utils.paths import ensure_app_dirs

    ensure_app_dirs()
    written = {}
    for key, directory in (
        ("settings", config_dir()),
        ("database", data_dir()),
        ("cache", cache_dir()),
        ("logs", logs_dir()),
    ):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{key}.bin"
        path.write_bytes(b"x" * 100)
        written[key] = path

    library = Path(settings.library_root)
    (library / "Audio" / "Sound Effects").mkdir(parents=True, exist_ok=True)
    media = library / "Audio" / "Sound Effects" / "Precious Whoosh.mp3"
    media.write_bytes(b"y" * 5000)
    written["library"] = media
    return written


@pytest.fixture
def service(settings):
    return UninstallService(settings.library_root)


class TestPlan:
    def test_lists_every_removable_target(self, service, populated_dirs):
        keys = {t.key for t in service.plan().targets}
        assert {"settings", "database", "cache", "logs", "library"} == keys

    def test_measures_real_sizes(self, service, populated_dirs):
        target = service.plan().by_key("library")
        assert target.exists
        assert target.size >= 5000
        assert target.file_count >= 1

    def test_reports_absent_targets_rather_than_omitting_them(self, settings):
        service = UninstallService(settings.library_root)
        target = service.plan().by_key("library")
        assert target is not None
        assert target.exists is False
        assert target.size == 0

    def test_the_library_is_flagged_destructive(self, service, populated_dirs):
        plan = service.plan()
        assert plan.by_key("library").destructive is True
        assert plan.by_key("cache").destructive is False

    def test_planning_deletes_nothing(self, service, populated_dirs):
        service.plan()
        for path in populated_dirs.values():
            assert path.exists()

    def test_no_library_target_when_none_is_configured(self):
        assert UninstallService(None).plan().by_key("library") is None

    def test_total_size_covers_only_the_selection(self, service, populated_dirs):
        plan = service.plan()
        assert plan.total_size(["library"]) >= 5000
        assert plan.total_size([]) == 0


class TestExecute:
    def test_removes_only_what_was_selected(self, service, populated_dirs):
        result = service.execute(["cache"], remove_autostart=False)
        assert result.ok
        assert not cache_dir().exists()
        # Everything else must survive.
        assert populated_dirs["settings"].exists()
        assert populated_dirs["database"].exists()
        assert populated_dirs["library"].exists()

    def test_the_library_survives_a_normal_uninstall(self, service, populated_dirs):
        service.execute(["settings", "database", "cache", "logs"], remove_autostart=False)
        assert populated_dirs["library"].exists(), (
            "a default uninstall must never touch the user's media"
        )

    def test_the_library_goes_only_when_explicitly_chosen(self, service, populated_dirs):
        service.execute(["library"], remove_autostart=False)
        assert not populated_dirs["library"].exists()

    def test_reports_what_it_removed(self, service, populated_dirs):
        result = service.execute(["cache", "logs"], remove_autostart=False)
        assert len(result.removed) == 2
        assert "Removed 2 items" in result.summary()

    def test_absent_targets_are_skipped_silently(self, service):
        result = service.execute(["cache", "logs"], remove_autostart=False)
        assert result.ok
        assert result.removed == []

    def test_a_failure_is_reported_rather_than_raised(self, service, populated_dirs, monkeypatch):
        monkeypatch.setattr(
            UninstallService, "_remove", staticmethod(lambda path: (False, "in use"))
        )
        result = service.execute(["cache"], remove_autostart=False)
        assert result.ok is False
        assert result.failed[0][1] == "in use"
        assert "could not be removed" in result.summary()

    def test_the_library_is_deleted_last(self, service, populated_dirs, monkeypatch):
        """If an earlier step fails, the irreversible one has not happened yet."""
        order = []

        def record(path):
            order.append(Path(path).name)
            return True, ""

        monkeypatch.setattr(UninstallService, "_remove", staticmethod(record))
        service.execute(
            ["library", "cache", "settings", "database"], remove_autostart=False
        )
        assert order[-1] == Path(service.plan().by_key("library").path).name

    def test_autostart_is_cleared_when_asked(self, service, populated_dirs):
        from app.services.autostart_service import AutostartService

        AutostartService.set_enabled(True)
        try:
            result = service.execute(["cache"], remove_autostart=True)
            assert result.autostart_removed is True
            assert AutostartService.is_enabled() is False
        finally:
            AutostartService.set_enabled(False)

    def test_autostart_is_left_alone_when_not_asked(self, service, populated_dirs):
        from app.services.autostart_service import AutostartService

        AutostartService.set_enabled(True)
        try:
            result = service.execute(["cache"], remove_autostart=False)
            assert result.autostart_removed is False
            assert AutostartService.is_enabled() is True
        finally:
            AutostartService.set_enabled(False)

    def test_the_application_hint_is_platform_specific(self):
        assert UninstallService.application_hint()


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
        app.setStyle("Fusion")
    return app


@pytest.fixture
def theme(qapp):
    from app.ui.theme import Theme, set_theme

    instance = Theme(qapp, "dark")
    instance.apply()
    set_theme(instance)
    yield instance
    set_theme(None)


class TestDialog:
    def _dialog(self, service, parent=None):
        from app.ui.dialogs.uninstall_dialog import UninstallDialog

        return UninstallDialog(service, parent)

    def test_it_builds(self, qapp, theme, service, populated_dirs):
        dialog = self._dialog(service)
        assert dialog.windowTitle()
        dialog.deleteLater()

    def test_the_library_starts_unticked(self, qapp, theme, service, populated_dirs):
        dialog = self._dialog(service)
        assert dialog._checks["library"].isChecked() is False
        assert dialog._checks["cache"].isChecked() is True
        dialog.deleteLater()

    def test_deleting_the_library_needs_a_typed_confirmation(
        self, qapp, theme, service, populated_dirs
    ):
        from app.ui.dialogs.uninstall_dialog import CONFIRM_WORD

        dialog = self._dialog(service)
        dialog._checks["library"].setChecked(True)

        assert dialog._library_confirm_row.isVisibleTo(dialog)
        assert not dialog._remove_btn.isEnabled(), "must not arm without confirmation"

        dialog._confirm_input.setText("delete")     # wrong case
        assert not dialog._remove_btn.isEnabled()

        dialog._confirm_input.setText(CONFIRM_WORD)
        assert dialog._remove_btn.isEnabled()
        dialog.deleteLater()

    def test_unticking_the_library_hides_the_confirmation(
        self, qapp, theme, service, populated_dirs
    ):
        from app.ui.dialogs.uninstall_dialog import CONFIRM_WORD

        dialog = self._dialog(service)
        dialog._checks["library"].setChecked(True)
        dialog._confirm_input.setText(CONFIRM_WORD)
        dialog._checks["library"].setChecked(False)

        assert not dialog._library_confirm_row.isVisibleTo(dialog)
        assert dialog._confirm_input.text() == "", "a stale confirmation must not persist"
        dialog.deleteLater()

    def test_nothing_selected_disables_removal(self, qapp, theme, service, populated_dirs):
        dialog = self._dialog(service)
        for check in dialog._checks.values():
            check.setChecked(False)
        assert not dialog._remove_btn.isEnabled()
        assert "Nothing selected" in dialog._summary.text()
        dialog.deleteLater()
