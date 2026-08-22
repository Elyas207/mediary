"""Launch-at-sign-in registration, the tray, and background running."""

from __future__ import annotations

import os
import pathlib
import sys
import textwrap
import time
from unittest import mock

import pytest

from app.services.autostart_service import (
    HIDDEN_FLAG,
    AutostartService,
    launch_argv,
)


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


class TestLaunchCommand:
    def test_includes_an_interpreter_and_an_entry_point(self):
        arguments = launch_argv(hidden=False)
        assert len(arguments) >= 1
        assert all(isinstance(part, str) and part for part in arguments)

    def test_hidden_adds_the_flag(self):
        assert HIDDEN_FLAG in launch_argv(hidden=True)
        assert HIDDEN_FLAG not in launch_argv(hidden=False)

    def test_source_launch_targets_main_py_by_absolute_path(self):
        # The login session's working directory is not the project root, so
        # "-m app.main" would not resolve.
        with mock.patch.object(sys, "frozen", False, create=True):
            arguments = launch_argv(hidden=False)
        assert arguments[-1].endswith("main.py")
        assert "-m" not in arguments

    @pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows only")
    def test_windows_prefers_pythonw_so_no_console_flashes(self):
        arguments = launch_argv(hidden=True)
        interpreter = arguments[0].lower()
        # pythonw only if it actually exists beside python.
        from pathlib import Path

        if Path(sys.executable).with_name("pythonw.exe").is_file():
            assert interpreter.endswith("pythonw.exe")

    def test_frozen_launch_uses_the_executable_itself(self):
        with mock.patch.object(sys, "frozen", True, create=True), \
             mock.patch.object(sys, "executable", "/apps/Mediary"):
            arguments = launch_argv(hidden=True)
        assert arguments[0].endswith("Mediary")
        assert arguments[1] == HIDDEN_FLAG


class TestAutostartRegistration:
    """Exercised against the real per-user mechanism, then cleaned up."""

    @pytest.fixture(autouse=True)
    def restore(self):
        was_enabled = AutostartService.is_enabled()
        yield
        AutostartService.set_enabled(was_enabled)

    def test_supported_on_this_platform(self):
        assert AutostartService.is_supported()

    def test_enable_then_disable_round_trips(self):
        ok, error = AutostartService.set_enabled(True, hidden=False)
        assert ok, error
        assert AutostartService.is_enabled() is True

        ok, error = AutostartService.set_enabled(False)
        assert ok, error
        assert AutostartService.is_enabled() is False

    def test_the_hidden_flag_is_recorded(self):
        AutostartService.set_enabled(True, hidden=True)
        state = AutostartService.state()
        assert state.enabled is True
        assert state.hidden is True
        assert HIDDEN_FLAG in state.command

    def test_disabling_twice_is_harmless(self):
        assert AutostartService.set_enabled(False)[0]
        assert AutostartService.set_enabled(False)[0]

    def test_sync_rewrites_when_the_hidden_flag_changes(self):
        AutostartService.sync(True, False)
        assert AutostartService.state().hidden is False

        AutostartService.sync(True, True)
        assert AutostartService.state().hidden is True

    def test_sync_is_a_no_op_when_already_correct(self):
        AutostartService.sync(True, True)
        with mock.patch.object(AutostartService, "set_enabled") as setter:
            AutostartService.sync(True, True)
            setter.assert_not_called()

    def test_a_failure_is_reported_rather_than_raised(self):
        with mock.patch(
            "app.services.autostart_service._windows_set", side_effect=OSError("denied")
        ), mock.patch(
            "app.services.autostart_service._macos_set", side_effect=OSError("denied")
        ), mock.patch(
            "app.services.autostart_service._linux_set", side_effect=OSError("denied")
        ):
            ok, error = AutostartService.set_enabled(True)
        assert ok is False
        assert error

    def test_the_location_is_describable(self):
        assert AutostartService.describe_location()


class TestSettings:
    def test_the_new_options_default_to_off(self, settings):
        assert settings.launch_at_startup is False
        assert settings.start_hidden is False
        assert settings.close_to_tray is False
        assert settings.tray_notifications is True

    def test_wants_tray_is_derived_from_the_hiding_options(self, settings):
        assert settings.wants_tray is False
        settings.close_to_tray = True
        assert settings.wants_tray is True
        settings.close_to_tray = False
        settings.start_hidden = True
        assert settings.wants_tray is True

    def test_launch_at_startup_alone_needs_no_tray(self, settings):
        settings.launch_at_startup = True
        assert settings.wants_tray is False

    def test_they_persist(self, store):
        store.update({"launch_at_startup": True, "start_hidden": True, "close_to_tray": True})
        from app.config.settings import SettingsStore

        reloaded = SettingsStore().settings
        assert reloaded.launch_at_startup is True
        assert reloaded.start_hidden is True
        assert reloaded.close_to_tray is True


class TestTray:
    def test_it_builds_when_a_tray_is_available(self, qapp, theme):
        from app.ui.tray import MediaryTray, tray_available

        if not tray_available():
            pytest.skip("no system tray on this machine")
        tray = MediaryTray(qapp.windowIcon())
        assert tray.supported
        tray.deleteLater()

    def test_the_badge_updates_the_queue_entry(self, qapp, theme):
        from app.ui.tray import MediaryTray, tray_available

        if not tray_available():
            pytest.skip("no system tray on this machine")
        tray = MediaryTray(qapp.windowIcon())
        tray.set_active_downloads(3)
        assert "3" in tray._queue_action.text()
        tray.set_active_downloads(0)
        assert tray._queue_action.text() == "Queue"
        tray.deleteLater()

    def test_notifying_a_hidden_tray_is_a_no_op(self, qapp, theme):
        from app.ui.tray import MediaryTray

        tray = MediaryTray(qapp.windowIcon())
        tray.set_visible(False)
        tray.notify("Title", "Body")   # must not raise
        tray.deleteLater()


@pytest.fixture
def window(qapp, theme, store, library, settings, organizer):
    from app.ui.main_window import MainWindow

    store.update({"first_run_complete": True, "library_root": settings.library_root})
    main = MainWindow(store, theme, library)
    yield main
    main._manager.shutdown(500)
    main.deleteLater()


class TestBackgroundWindow:
    def test_closing_quits_normally_by_default(self, window):
        from PySide6.QtGui import QCloseEvent

        event = QCloseEvent()
        window.closeEvent(event)
        assert event.isAccepted()

    def test_close_to_tray_hides_instead_of_quitting(self, window, store):
        from PySide6.QtGui import QCloseEvent

        if window._tray is None:
            pytest.skip("no system tray on this machine")
        store.set("close_to_tray", True)
        window._settings = store.settings
        window._sync_tray_visibility()
        window.show()

        event = QCloseEvent()
        window.closeEvent(event)

        assert not event.isAccepted(), "the close must be swallowed"
        assert not window.isVisible(), "the window should be hidden, leaving the taskbar"

    def test_quit_from_the_tray_really_quits(self, window, store):
        from PySide6.QtGui import QCloseEvent

        if window._tray is None:
            pytest.skip("no system tray on this machine")
        store.set("close_to_tray", True)
        window._settings = store.settings
        window._quitting = True

        event = QCloseEvent()
        window.closeEvent(event)
        assert event.isAccepted()

    def test_show_from_tray_restores_the_window(self, window):
        window.hide()
        window.show_from_tray("queue")
        assert window.isVisible()
        assert window.sidebar.active_key() == "queue"

    def test_qt_does_not_exit_while_the_tray_holds_the_app(self, window, store):
        from PySide6.QtWidgets import QApplication

        if window._tray is None:
            pytest.skip("no system tray on this machine")
        store.set("close_to_tray", True)
        window._settings = store.settings
        window._sync_tray_visibility()
        assert QApplication.quitOnLastWindowClosed() is False

        store.set("close_to_tray", False)
        window._settings = store.settings
        window._sync_tray_visibility()
        assert QApplication.quitOnLastWindowClosed() is True

    def test_background_options_are_forced_off_without_a_tray(
        self, qapp, theme, store, library, settings, organizer
    ):
        from app.ui.main_window import MainWindow

        store.update(
            {
                "first_run_complete": True,
                "library_root": settings.library_root,
                "start_hidden": True,
                "close_to_tray": True,
            }
        )
        with mock.patch("app.ui.main_window.tray_available", return_value=False):
            main = MainWindow(store, theme, library)

        # A hidden window with no tray icon would be unreachable.
        assert store.settings.start_hidden is False
        assert store.settings.close_to_tray is False
        assert main.has_tray is False
        main._manager.shutdown(300)
        main.deleteLater()

    def test_the_settings_screen_exposes_the_options(self, window):
        window.navigate("settings")
        view = window.settings_view
        assert view._launch_at_startup is not None
        assert view._start_hidden is not None
        assert view._close_to_tray is not None

    def test_the_hidden_checkboxes_are_disabled_without_a_tray(
        self, qapp, theme, store, library
    ):
        from app.ui.views.settings_view import SettingsView

        with mock.patch("app.ui.tray.tray_available", return_value=False):
            view = SettingsView(store, theme, library)
        assert not view._start_hidden.isEnabled()
        assert not view._close_to_tray.isEnabled()
        view.deleteLater()


class TestCommandLine:
    def test_the_hidden_flag_is_parsed(self):
        from app.main import parse_arguments

        options, _ = parse_arguments(["mediary", "--hidden"])
        assert options.hidden is True

    def test_background_is_an_alias(self):
        from app.main import parse_arguments

        options, _ = parse_arguments(["mediary", "--background"])
        assert options.hidden is True

    def test_no_flag_means_a_visible_launch(self):
        from app.main import parse_arguments

        options, _ = parse_arguments(["mediary"])
        assert options.hidden is False

    def test_qt_arguments_are_passed_through(self):
        from app.main import parse_arguments

        options, extra = parse_arguments(["mediary", "--hidden", "-platform", "offscreen"])
        assert options.hidden is True
        assert "-platform" in extra and "offscreen" in extra


class TestSingleInstance:
    """Once Mediary can live in the tray, a second launch must hand off."""

    def _guard(self, suffix: str):
        # An isolated socket name, so the suite never collides with a Mediary
        # the developer happens to have running.
        from app.utils.single_instance import SingleInstanceGuard

        return SingleInstanceGuard(name=f"mediary-test-{os.getpid()}-{suffix}")

    def test_the_first_process_claims_the_lock(self, qapp):
        guard = self._guard("claim")
        try:
            assert guard.try_acquire() is True
            assert guard.is_primary is True
        finally:
            guard.release()

    def test_a_second_process_is_turned_away(self, qapp):
        first = self._guard("dup")
        second = self._guard("dup")
        try:
            assert first.try_acquire() is True
            assert second.try_acquire() is False, "a duplicate must not start"
            assert second.is_primary is False
        finally:
            second.release()
            first.release()

    def test_the_lock_is_reusable_after_release(self, qapp):
        first = self._guard("reuse")
        assert first.try_acquire() is True
        first.release()

        second = self._guard("reuse")
        try:
            assert second.try_acquire() is True
        finally:
            second.release()

    def test_the_running_instance_is_woken_by_a_real_second_launch(self, tmp_path):
        """The handoff, across genuine process boundaries.

        This cannot be exercised inside one process: a blocking wait on the
        client socket would starve the very event loop the server needs in
        order to read it.
        """
        import subprocess

        name = f"mediary-test-handoff-{os.getpid()}"
        root = str(pathlib.Path(__file__).resolve().parents[1])

        server_source = textwrap.dedent(
            f"""
            import os, sys
            sys.path.insert(0, {root!r})
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            from PySide6.QtWidgets import QApplication
            from PySide6.QtCore import QTimer
            from app.utils.single_instance import SingleInstanceGuard
            app = QApplication([])
            guard = SingleInstanceGuard(name={name!r})
            print("PRIMARY:" + str(guard.try_acquire()), flush=True)
            guard.wake_requested.connect(lambda: (print("WOKEN", flush=True), app.quit()))
            QTimer.singleShot(20000, app.quit)
            app.exec()
            """
        )
        client_source = textwrap.dedent(
            f"""
            import os, sys
            sys.path.insert(0, {root!r})
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            from PySide6.QtWidgets import QApplication
            from app.utils.single_instance import SingleInstanceGuard
            app = QApplication([])
            print("SECOND:" + str(SingleInstanceGuard(name={name!r}).try_acquire()), flush=True)
            """
        )

        server_file = tmp_path / "server.py"
        client_file = tmp_path / "client.py"
        server_file.write_text(server_source, encoding="utf-8")
        client_file.write_text(client_source, encoding="utf-8")

        server = subprocess.Popen(
            [sys.executable, str(server_file)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
        try:
            deadline = time.monotonic() + 40
            line = ""
            while time.monotonic() < deadline:
                line = server.stdout.readline()
                if not line or line.startswith("PRIMARY:"):
                    break
            assert line.strip() == "PRIMARY:True", "the first process should hold the lock"

            client = subprocess.run(
                [sys.executable, str(client_file)],
                capture_output=True, text=True, timeout=90,
            )
            assert "SECOND:False" in client.stdout, "the second launch must be refused"

            assert server.stdout.readline().strip() == "WOKEN", (
                "the running instance should have been asked to surface its window"
            )
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
