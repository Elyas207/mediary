"""Generated artwork, motion, system-accent integration and the preview dock."""

from __future__ import annotations

import pytest

from app.ui.theme.artwork import gradient_colors


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


class TestGeneratedArtwork:
    """Placeholders carry information, so they must be stable and distinct."""

    def test_the_same_item_always_looks_the_same(self):
        first = gradient_colors("Epic Cinematic Whoosh", "#E0A94A", dark=True)
        second = gradient_colors("Epic Cinematic Whoosh", "#E0A94A", dark=True)
        assert [c.name() for c in first] == [c.name() for c in second]

    def test_different_items_look_different(self):
        a = gradient_colors("Whoosh One", "#E0A94A", dark=True)[0]
        b = gradient_colors("Whoosh Two", "#E0A94A", dark=True)[0]
        assert a.name() != b.name()

    def test_a_category_stays_one_colour_family(self):
        """Two items in the same category must be recognisably related."""
        hues = [
            gradient_colors(f"Item {i}", "#E0A94A", dark=True)[0].hslHue()
            for i in range(12)
        ]
        spread = max(hues) - min(hues)
        assert spread <= 40, f"hue spread of {spread} is too wide to read as one category"

    def test_categories_are_distinguishable_from_each_other(self):
        amber = gradient_colors("X", "#E0A94A", dark=True)[0].hslHue()
        magenta = gradient_colors("X", "#D96BB4", dark=True)[0].hslHue()
        assert abs(amber - magenta) > 40

    def test_dark_placeholders_stay_dark_enough_for_white_text(self):
        for title in ("A", "Something Longer", "Zzz"):
            for base in ("#E0A94A", "#D96BB4", "#5B8CFF", "#57B26A"):
                top, bottom = gradient_colors(title, base, dark=True)
                assert top.lightnessF() < 0.62, f"{title}/{base} too light for dark mode"
                assert bottom.lightnessF() < top.lightnessF() + 0.01

    def test_light_placeholders_stay_light_enough_for_dark_text(self):
        for base in ("#B37A11", "#C4489B", "#3F6FE8"):
            top, _ = gradient_colors("Item", base, dark=False)
            assert top.lightnessF() > 0.62

    def test_a_greyscale_base_still_produces_a_hue(self):
        # A colourless category would otherwise yield a flat grey slab.
        top, _ = gradient_colors("Item", "#808080", dark=True)
        assert top.hslHue() >= 0

    def test_empty_key_does_not_raise(self):
        assert gradient_colors("", "#E0A94A", dark=True)

    def test_thumbnail_uses_the_placeholder(self, qapp, theme):
        from app.ui.widgets.thumbnail import Thumbnail

        thumb = Thumbnail()
        thumb.set_placeholder("Epic Cinematic Whoosh", "#E0A94A")
        assert thumb.has_image() is False   # still no real artwork
        thumb.resize(200, 112)
        thumb.grab()                        # must paint without raising
        thumb.deleteLater()


class TestMotion:
    def test_reduce_motion_collapses_durations(self, qapp, theme):
        from PySide6.QtWidgets import QWidget

        from app.ui.theme import motion

        widget = QWidget()
        try:
            motion.set_reduce_motion(True)
            assert motion.reduce_motion() is True
            animation = motion.animate(widget, b"windowOpacity", 1.0, start=0.0)
            assert animation.duration() == 0
        finally:
            motion.set_reduce_motion(False)
            widget.deleteLater()

    def test_normal_motion_has_a_real_duration(self, qapp, theme):
        from PySide6.QtWidgets import QWidget

        from app.ui.theme import motion

        widget = QWidget()
        animation = motion.animate(widget, b"windowOpacity", 1.0, start=0.0)
        assert animation.duration() > 0
        widget.deleteLater()

    def test_fade_in_shows_the_widget_even_with_motion_off(self, qapp, theme):
        from PySide6.QtWidgets import QWidget

        from app.ui.theme import motion

        parent = QWidget()
        child = QWidget(parent)
        child.hide()
        try:
            motion.set_reduce_motion(True)
            motion.fade_in(child)
            assert child.isVisibleTo(parent), "reduced motion must not hide content"
        finally:
            motion.set_reduce_motion(False)
            parent.deleteLater()

    def test_fade_in_does_not_stack_opacity_effects(self, qapp, theme):
        from PySide6.QtWidgets import QWidget

        from app.ui.theme import motion

        widget = QWidget()
        motion.fade_in(widget)
        first = widget.graphicsEffect()
        motion.fade_in(widget)
        assert widget.graphicsEffect() is first
        widget.deleteLater()

    def test_stagger_caps_its_delay(self, qapp, theme):
        from app.ui.theme import motion

        delays = []
        motion.stagger(list(range(60)), lambda _w, delay: delays.append(delay), step=20, cap=10)
        assert max(delays) == 200, "a long list must not animate for many seconds"


class TestSystemTheme:
    def test_colour_scheme_is_reported(self, qapp):
        from app.ui.theme.system import system_color_scheme

        assert system_color_scheme() in ("dark", "light", "unknown")

    def test_accent_reading_never_raises(self, qapp):
        from app.ui.theme.system import system_accent

        system_accent()   # may be None; must not raise

    def test_an_extreme_accent_is_pulled_into_a_usable_range(self, qapp, monkeypatch):
        from PySide6.QtGui import QColor

        from app.ui.theme import system

        monkeypatch.setattr(system, "system_accent", lambda: QColor("#000000"))
        adjusted = system.usable_accent(dark=True)
        assert adjusted is not None
        assert system.MIN_LIGHTNESS <= adjusted.lightnessF() <= system.MAX_LIGHTNESS

    def test_a_reasonable_accent_is_left_alone(self, qapp, monkeypatch):
        from PySide6.QtGui import QColor

        from app.ui.theme import system

        monkeypatch.setattr(system, "system_accent", lambda: QColor("#3D5FE8"))
        assert system.usable_accent(dark=True).name() == "#3d5fe8"

    def test_variants_pick_readable_text(self, qapp):
        from PySide6.QtGui import QColor

        from app.ui.theme.system import accent_variants

        # White text on navy, dark text on yellow.
        assert accent_variants(QColor("#12206E"))["accent_text"] == "#FFFFFF"
        assert accent_variants(QColor("#FFD400"))["accent_text"] == "#14161A"

    def test_the_theme_applies_a_system_accent(self, qapp, monkeypatch):
        from PySide6.QtGui import QColor

        from app.ui.theme import DARK, Theme, system

        monkeypatch.setattr(system, "system_accent", lambda: QColor("#C4489B"))
        themed = Theme(qapp, "dark", use_system_accent=True)
        palette = themed.apply()
        assert palette.accent.lower() == "#c4489b"
        # Only the accent family moves; surfaces stay Mediary's.
        assert palette.surface == DARK.surface
        assert palette.text == DARK.text

    def test_turning_it_off_restores_the_built_in_accent(self, qapp, monkeypatch):
        from PySide6.QtGui import QColor

        from app.ui.theme import DARK, Theme, system

        monkeypatch.setattr(system, "system_accent", lambda: QColor("#C4489B"))
        themed = Theme(qapp, "dark", use_system_accent=True)
        themed.apply()
        themed.set_use_system_accent(False)
        assert themed.apply().accent == DARK.accent

    def test_an_unreadable_system_accent_does_not_break_theming(self, qapp, monkeypatch):
        from app.ui.theme import Theme, system

        monkeypatch.setattr(system, "system_accent", lambda: None)
        themed = Theme(qapp, "dark", use_system_accent=True)
        assert themed.apply().accent


class TestPreviewDock:
    def _bar(self, parent=None):
        from app.ui.widgets.preview_bar import PreviewBar

        return PreviewBar(parent)

    def test_it_starts_collapsed(self, qapp, theme):
        bar = self._bar()
        assert bar.maximumHeight() == 0
        bar.deleteLater()

    def test_previewing_expands_and_loads_the_item(
        self, qapp, theme, library, make_item, real_file
    ):
        path = real_file("whoosh.mp3")
        item = make_item(
            title="Epic Cinematic Whoosh", file_path=str(path), filename=path.name,
            media_kind="audio", category="Sound Effects",
        )
        bar = self._bar()
        bar.preview(item)

        assert bar.item is item
        assert bar.maximumHeight() > 0
        assert "Whoosh" in bar.title.fullText()
        bar.deleteLater()

    def test_closing_clears_the_item(self, qapp, theme, make_item, real_file):
        path = real_file("whoosh.mp3")
        item = make_item(file_path=str(path), filename=path.name, media_kind="audio")
        bar = self._bar()
        bar.preview(item)
        bar.close_preview()
        assert bar.item is None
        bar.deleteLater()

    def test_a_missing_file_is_reported_not_played(self, qapp, theme, make_item):
        item = make_item(file_path="/nowhere/gone.mp3", media_kind="audio")
        bar = self._bar()
        bar.preview(item)
        assert "unavailable" in bar.subtitle.fullText().lower()
        assert not bar.play_btn.isEnabled()
        bar.deleteLater()

    def test_it_survives_without_qtmultimedia(self, qapp, theme, make_item, real_file):
        import sys as _sys
        from unittest import mock

        real_import = (
            __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__
        )

        def blocked(name, *args, **kwargs):
            if name.startswith("PySide6.QtMultimedia"):
                raise ImportError("libpulse.so.0: cannot open shared object file")
            return real_import(name, *args, **kwargs)

        for module in ("app.ui.widgets.preview_bar", "app.ui.widgets.audio_player"):
            _sys.modules.pop(module, None)
        try:
            with mock.patch("builtins.__import__", side_effect=blocked):
                import importlib

                module = importlib.import_module("app.ui.widgets.preview_bar")
            bar = module.PreviewBar()
            assert bar.is_available is False
            assert not bar.play_btn.isEnabled()

            path = real_file("x.mp3")
            item = make_item(file_path=str(path), filename=path.name, media_kind="audio")
            bar.preview(item)          # must not raise
            bar.toggle()
            bar.close_preview()
            bar.deleteLater()
        finally:
            import importlib

            for module_name in ("app.ui.widgets.preview_bar", "app.ui.widgets.audio_player"):
                _sys.modules.pop(module_name, None)
                importlib.import_module(module_name)


class TestLibraryAuditioning:
    @pytest.fixture
    def window(self, qapp, theme, store, library, settings, organizer):
        from app.ui.main_window import MainWindow

        store.update({"first_run_complete": True, "library_root": settings.library_root})
        main = MainWindow(store, theme, library)
        yield main
        main._manager.shutdown(500)
        main.deleteLater()

    def test_previewing_audio_opens_the_dock(self, window, library, make_item, real_file):
        path = real_file("audition.mp3")
        library.add(
            make_item(file_path=str(path), filename=path.name, media_kind="audio")
        )
        window.navigate("all")
        item = window.library_view._items[0]

        window.library_view.preview_item(item)
        assert window.library_view.preview.item is item

    def test_previewing_video_hands_off_to_the_system_player(
        self, window, library, make_item, real_file
    ):
        path = real_file("clip.mp4")
        library.add(
            make_item(
                file_path=str(path), filename=path.name,
                media_kind="video", category="Video",
            )
        )
        window.navigate("all")

        opened = []
        window.library_view.open_path_requested.connect(opened.append)
        window.library_view.preview_item(window.library_view._items[0])

        assert opened == [str(path)], "video has no in-app player; it must be handed off"
        assert window.library_view.preview.item is None

    def test_space_auditions_the_selection(self, window, library, make_item, real_file):
        path = real_file("space.mp3")
        library.add(
            make_item(file_path=str(path), filename=path.name, media_kind="audio")
        )
        window.navigate("all")
        item = window.library_view._items[0]
        window.library_view._on_selected(item)

        window.library_view.toggle_preview_selected()
        assert window.library_view.preview.item is item

    def test_the_playing_row_is_marked(self, window, library, make_item, real_file):
        path = real_file("marked.mp3")
        media_id = library.add(
            make_item(file_path=str(path), filename=path.name, media_kind="audio")
        )
        window.navigate("all")
        window.library_view._on_view_changed("list")

        item = window.library_view._items[0]
        window.library_view._on_preview_state(item, True)
        assert window.library_view._widgets[media_id].property("playing") == "true"


class TestDownloadFriction:
    """The paste-to-download path is the most-used flow; it must be short."""

    @pytest.fixture
    def window(self, qapp, theme, store, library, settings, organizer):
        from app.ui.main_window import MainWindow

        store.update({"first_run_complete": True, "library_root": settings.library_root})
        main = MainWindow(store, theme, library)
        yield main
        main._manager.shutdown(500)
        main.deleteLater()

    def test_a_clipboard_url_is_offered(self, window, qapp):
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.clipboard().setText("https://example.com/a-sound-effect")
        window.navigate("download")

        view = window.download_view
        assert view.clipboard_hint.isVisibleTo(view)
        assert "example.com" in view._clipboard_btn.text()

    def test_prose_on_the_clipboard_is_not_offered(self, window, qapp):
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.clipboard().setText("just some notes I copied earlier")
        window.navigate("download")
        assert not window.download_view.clipboard_hint.isVisibleTo(window.download_view)

    def test_a_url_already_typed_is_not_offered_again(self, window, qapp):
        from PySide6.QtGui import QGuiApplication

        url = "https://example.com/already"
        QGuiApplication.clipboard().setText(url)
        window.navigate("download")
        window.download_view.url_input.setPlainText(url)
        window.download_view.refresh_clipboard_hint()

        assert not window.download_view.clipboard_hint.isVisibleTo(window.download_view)

    def test_multiple_clipboard_urls_are_summarised(self, window, qapp):
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.clipboard().setText(
            "https://example.com/1\nhttps://example.com/2\nhttps://example.com/3"
        )
        window.navigate("download")
        assert "3 URLs" in window.download_view._clipboard_btn.text()

    def test_an_empty_clipboard_is_harmless(self, window, qapp):
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.clipboard().clear()
        window.navigate("download")
        assert not window.download_view.clipboard_hint.isVisibleTo(window.download_view)


class TestSidebarProgress:
    @pytest.fixture
    def window(self, qapp, theme, store, library, settings, organizer):
        from app.ui.main_window import MainWindow

        store.update({"first_run_complete": True, "library_root": settings.library_root})
        main = MainWindow(store, theme, library)
        yield main
        main._manager.shutdown(500)
        main.deleteLater()

    def test_idle_shows_no_progress(self, window):
        assert window._overall_progress() == 0.0

    def test_running_downloads_average_their_progress(self, window):
        from app.models.download import DownloadOptions, DownloadStatus, Progress

        first = window._manager.enqueue("https://a/1", DownloadOptions(), start=False)
        second = window._manager.enqueue("https://a/2", DownloadOptions(), start=False)
        first.status = DownloadStatus.DOWNLOADING
        second.status = DownloadStatus.DOWNLOADING
        first.progress = Progress(downloaded_bytes=100, total_bytes=100)
        second.progress = Progress(downloaded_bytes=0, total_bytes=100)

        assert window._overall_progress() == pytest.approx(0.5)

    def test_finished_downloads_stop_counting(self, window):
        from app.models.download import DownloadOptions, DownloadStatus

        task = window._manager.enqueue("https://a/1", DownloadOptions(), start=False)
        task.status = DownloadStatus.COMPLETE
        assert window._overall_progress() == 0.0


class TestWrappedCopy:
    """Empty-state copy has clipped its last line twice; guard it properly."""

    def test_a_paragraph_reports_room_for_every_line(self, qapp, theme):
        from app.ui.widgets.common import WrappedLabel

        text = (
            "Paste a link above and Mediary will show you the title, creator, "
            "length and every format the source offers before anything downloads."
        )
        wrapped = WrappedLabel(text, "heroBody", 420)
        wrapped.show()

        metrics = wrapped.fontMetrics()
        lines = max(1, round(wrapped.minimumHeight() / metrics.lineSpacing()))
        assert lines >= 3, "a three-line paragraph must reserve three lines"
        assert wrapped.minimumHeight() >= wrapped.heightForWidth(420)
        wrapped.deleteLater()

    def test_the_height_is_binding_not_advisory(self, qapp, theme):
        from app.ui.widgets.common import WrappedLabel

        wrapped = WrappedLabel("word " * 60, "heroBody", 300)
        wrapped.show()
        # A parent inside a stretch can ignore sizeHint; minimumHeight it cannot.
        assert wrapped.minimumHeight() == wrapped.sizeHint().height()
        wrapped.deleteLater()

    def test_changing_the_text_remeasures(self, qapp, theme):
        from app.ui.widgets.common import WrappedLabel

        wrapped = WrappedLabel("Short", "heroBody", 300)
        wrapped.show()
        short = wrapped.minimumHeight()
        wrapped.setText("word " * 80)
        assert wrapped.minimumHeight() > short
        wrapped.deleteLater()

    def test_empty_state_copy_is_not_clipped(self, qapp, theme):
        from app.ui.widgets.common import EmptyState

        state = EmptyState(
            icon="download",
            title="Nothing analysed yet",
            body=(
                "Paste a link above and Mediary will show you the title, creator, "
                "length and every format the source offers before anything downloads."
            ),
        )
        state.resize(700, 500)
        state.show()
        assert state._body.height() >= state._body.heightForWidth(state.TEXT_WIDTH)
        state.deleteLater()
