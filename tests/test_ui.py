"""UI smoke tests: every screen builds, themes apply, widgets behave.

These run headless via the offscreen Qt platform.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


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


@pytest.fixture
def window(qapp, theme, store, library, settings, organizer):
    from app.ui.main_window import MainWindow

    store.update({"first_run_complete": True, "library_root": settings.library_root})
    main = MainWindow(store, theme, library)
    yield main
    main._manager.shutdown(500)
    main.deleteLater()


class TestTheme:
    def test_both_palettes_render_a_complete_stylesheet(self, qapp, theme):
        import re

        for preference in ("dark", "light"):
            theme.apply(preference)
            qss = qapp.styleSheet()
            assert len(qss) > 5000
            assert re.search(r"\{[a-z_]+\}", qss) is None, "unresolved token in the stylesheet"

    def test_palettes_define_every_token(self):
        from dataclasses import fields

        from app.ui.theme.tokens import DARK, LIGHT

        for palette in (DARK, LIGHT):
            for token in fields(palette):
                value = getattr(palette, token.name)
                assert value not in (None, ""), f"{palette.name}.{token.name} is empty"

    def test_the_two_palettes_expose_identical_keys(self):
        from app.ui.theme.tokens import DARK, LIGHT

        assert set(DARK.as_dict()) == set(LIGHT.as_dict())
        assert set(DARK.categories) == set(LIGHT.categories)

    def test_light_and_dark_actually_differ(self):
        from app.ui.theme.tokens import DARK, LIGHT

        assert DARK.surface != LIGHT.surface
        assert DARK.text != LIGHT.text

    def test_every_icon_renders(self, theme):
        from app.ui.theme.icons import available_icons

        for name in available_icons():
            assert not theme.pixmap(name, 16).isNull(), f"{name} failed to render"

    def test_an_unknown_icon_falls_back_instead_of_crashing(self, theme):
        assert not theme.pixmap("no-such-icon", 16).isNull()

    def test_switching_theme_regenerates_icons(self, theme):
        dark = theme.pixmap("download", 16, "text").toImage()
        theme.apply("light")
        light = theme.pixmap("download", 16, "text").toImage()
        assert dark != light


class TestMainWindow:
    def test_it_builds(self, window):
        assert window.windowTitle() == "Mediary"

    @pytest.mark.parametrize(
        "key",
        ["download", "queue", "all", "video", "audio", "sfx", "music",
         "inspiration", "favorites", "tags", "settings"],
    )
    def test_every_nav_destination_works(self, window, key):
        window.navigate(key)
        assert window.stack.currentWidget() is not None
        assert window.sidebar.active_key() == key

    def test_navigation_survives_a_theme_switch(self, window, theme):
        window.navigate("all")
        theme.apply("light")
        window.sidebar.refresh_theme()
        window.library_view.refresh_theme()
        window.navigate("settings")
        assert window.stack.currentWidget() is window.settings_view

    def test_the_last_view_is_remembered(self, window, store):
        window.navigate("music")
        assert store.settings.last_view == "music"

    def test_sidebar_counts_refresh_without_error(self, window):
        window._refresh_counts()


class TestLibraryView:
    def test_empty_state_shows_when_there_is_nothing(self, window):
        window.navigate("all")
        assert window.library_view._empty.isVisibleTo(window.library_view)

    def test_items_render_in_both_view_modes(self, window, library, make_item):
        for _ in range(5):
            library.add(make_item())
        window.navigate("all")

        window.library_view._on_view_changed("grid")
        assert len(window.library_view._widgets) == 5

        window.library_view._on_view_changed("list")
        assert len(window.library_view._widgets) == 5

    def test_search_filters_the_result_set(self, window, library, make_item):
        library.add(make_item(title="Findable Whoosh"))
        library.add(make_item(title="Something Else"))
        window.navigate("all")

        window.library_view.search.setText("whoosh")
        window.library_view._run_search()
        assert len(window.library_view._items) == 1

    def test_a_nav_filter_narrows_the_query(self, window, library, make_item):
        library.add(make_item(category="Sound Effects", media_kind="audio"))
        library.add(make_item(category="Music", media_kind="audio"))
        window.navigate("sfx")
        assert len(window.library_view._items) == 1

    def test_clear_filters_restores_everything(self, window, library, make_item):
        library.add(make_item(title="A"))
        library.add(make_item(title="B"))
        window.navigate("all")
        window.library_view.search.setText("A")
        window.library_view._run_search()
        window.library_view.clear_filters()
        assert len(window.library_view._items) == 2

    def test_toggling_a_favourite_updates_the_record(self, window, library, make_item):
        media_id = library.add(make_item())
        window.navigate("all")
        item = window.library_view._items[0]
        window.library_view._toggle_favorite(item)
        assert library.get(media_id).favorite is True

    def test_the_view_mode_is_reported_for_persistence(self, window):
        window.navigate("all")
        window.library_view._on_view_changed("list")
        assert window.library_view.current_view_mode() == "list"


class TestDownloadView:
    def test_analyse_is_disabled_without_a_url(self, window):
        window.navigate("download")
        assert not window.download_view.analyze_btn.isEnabled()

    def test_analyse_enables_once_a_url_is_typed(self, window):
        window.navigate("download")
        window.download_view.url_input.setPlainText("https://example.com/video")
        assert window.download_view.analyze_btn.isEnabled()

    def test_prose_does_not_enable_analyse(self, window):
        window.navigate("download")
        window.download_view.url_input.setPlainText("this is not a url at all")
        assert not window.download_view.analyze_btn.isEnabled()

    def test_the_url_count_is_reported(self, window):
        window.navigate("download")
        window.download_view.url_input.setPlainText(
            "https://a.com/1\nhttps://b.com/2\nhttps://c.com/3"
        )
        assert "3 URL" in window.download_view.url_count.text()

    def test_option_bar_produces_valid_options(self, window):
        options = window.download_view.default_options.options()
        assert options.media_kind in ("video", "audio")
        assert options.category
        assert options.quality_label()

    def test_switching_to_audio_offers_audio_categories(self, window):
        bar = window.download_view.default_options
        bar.kind.set_value("audio", emit=True)
        categories = {bar.category_box.itemText(i) for i in range(bar.category_box.count())}
        assert "Sound Effects" in categories and "Music" in categories

    def test_switching_to_video_offers_video_categories(self, window):
        bar = window.download_view.default_options
        bar.kind.set_value("video", emit=True)
        categories = {bar.category_box.itemText(i) for i in range(bar.category_box.count())}
        assert "Inspiration" in categories

    def test_a_lossless_format_disables_the_bitrate_picker(self, window):
        bar = window.download_view.default_options
        bar.kind.set_value("audio", emit=True)
        index = bar.format_box.findData("wav")
        bar.format_box.setCurrentIndex(index)
        assert not bar.quality_box.isEnabled()

    def test_only_available_resolutions_are_offered(self, window):
        bar = window.download_view.default_options
        bar.kind.set_value("video", emit=True)
        bar.set_available_qualities(["best", "720p", "360p"])
        offered = {bar.quality_box.itemData(i) for i in range(bar.quality_box.count())}
        assert offered == {"best", "720p", "360p"}
        assert "2160p" not in offered


class TestQueueView:
    def test_empty_state(self, window):
        window.navigate("queue")
        assert window.queue_view._empty.isVisibleTo(window.queue_view)

    def test_a_task_produces_a_row(self, window):
        from app.models.download import DownloadOptions

        window.navigate("queue")
        window._manager.enqueue(
            "https://example.com/x", DownloadOptions(category="Video"), start=False
        )
        assert len(window.queue_view._rows) == 1

    def test_filters_hide_non_matching_rows(self, window):
        from app.models.download import DownloadOptions, DownloadStatus

        window.navigate("queue")
        task = window._manager.enqueue(
            "https://example.com/x", DownloadOptions(category="Video"), start=False
        )
        task.status = DownloadStatus.COMPLETE
        window.queue_view._on_task_updated(task)

        window.queue_view._on_filter_changed("failed")
        assert not window.queue_view._rows[task.id].isVisibleTo(window.queue_view)

        window.queue_view._on_filter_changed("complete")
        assert window.queue_view._rows[task.id].isVisibleTo(window.queue_view)

    def test_the_summary_reflects_the_queue(self, window):
        from app.models.download import DownloadOptions, DownloadStatus

        window.navigate("queue")
        task = window._manager.enqueue(
            "https://example.com/x", DownloadOptions(), start=False
        )
        task.status = DownloadStatus.DOWNLOADING
        window.queue_view.refresh_summary()
        assert "downloading" in window.queue_view._summary.text()


class TestSettingsView:
    def test_it_loads_current_values(self, window, store):
        store.set("concurrent_downloads", 3)
        window.settings_view.reload()
        assert window.settings_view._concurrency.value() == 3

    def test_changing_a_control_persists_it(self, window, store):
        window.navigate("settings")
        window.settings_view._concurrency.setValue(4)
        assert store.settings.concurrent_downloads == 4

    def test_the_filename_preview_updates(self, window):
        window.navigate("settings")
        window.settings_view._filename_template.setText("{creator} - {title}")
        assert "Example Creator - Epic Cinematic Whoosh" in (
            window.settings_view._template_preview.fullText()
        )

    def test_ffmpeg_status_is_reported_either_way(self, window):
        window.navigate("settings")
        assert window.settings_view._ffmpeg_badge.text()


class TestTagsView:
    def test_empty_state(self, window):
        window.navigate("tags")
        assert window.tags_view._empty.isVisibleTo(window.tags_view)

    def test_tags_are_listed_with_counts(self, window, library, make_item):
        media_id = library.add(make_item())
        library.set_tags(media_id, ["Whoosh", "Cinematic"])
        window.navigate("tags")
        assert len(window.tags_view._tags) == 2
        assert "2 TAGS" in window.tags_view._summary.text()


class TestMediaDetailDialog:
    def test_it_builds_for_audio(self, window, library, make_item, settings):
        from app.ui.dialogs.media_detail_dialog import MediaDetailDialog

        media_id = library.add(make_item(media_kind="audio", category="Sound Effects"))
        dialog = MediaDetailDialog(library.get(media_id), library, settings, window)
        assert dialog.windowTitle()
        dialog.deleteLater()

    def test_it_builds_for_video(self, window, library, make_item, settings):
        from app.ui.dialogs.media_detail_dialog import MediaDetailDialog

        media_id = library.add(
            make_item(media_kind="video", category="Inspiration", width=1920, height=1080)
        )
        dialog = MediaDetailDialog(library.get(media_id), library, settings, window)
        dialog.deleteLater()

    def test_saving_writes_the_edits_back(self, window, library, make_item, settings):
        from app.ui.dialogs.media_detail_dialog import MediaDetailDialog

        media_id = library.add(make_item(title="Before"))
        dialog = MediaDetailDialog(library.get(media_id), library, settings, window)
        dialog._title_input.setText("After")
        dialog._license_box.setCurrentIndex(dialog._license_box.findData("Creative Commons"))
        dialog._save()

        item = library.get(media_id)
        assert item.title == "After"
        assert item.license_type == "Creative Commons"
        dialog.deleteLater()

    def test_adding_a_tag_persists(self, window, library, make_item, settings):
        from app.ui.dialogs.media_detail_dialog import MediaDetailDialog

        media_id = library.add(make_item())
        dialog = MediaDetailDialog(library.get(media_id), library, settings, window)
        dialog._add_tag("Whoosh")
        assert library.tags_for(media_id) == ["Whoosh"]
        dialog.deleteLater()


class TestWidgets:
    def test_wrapped_label_reports_a_multi_line_height(self, qapp, theme):
        from app.ui.widgets.common import WrappedLabel

        short = WrappedLabel("Short", width=400)
        long_text = WrappedLabel(
            "A considerably longer sentence that must wrap onto several lines "
            "when constrained to a four hundred pixel measure, and report the "
            "height that wrapping actually requires.",
            width=400,
        )
        assert long_text.sizeHint().height() > short.sizeHint().height() * 2

    def test_elided_label_keeps_its_full_text(self, qapp, theme):
        from app.ui.widgets.common import ElidedLabel

        label = ElidedLabel("A very long title that will certainly be elided")
        label.resize(60, 20)
        assert label.fullText().startswith("A very long")

    def test_a_badge_never_stretches(self, qapp, theme):
        from app.ui.widgets.common import Badge

        badge = Badge("MP3")
        assert badge.height() == Badge.HEIGHT

    def test_segmented_control_is_exclusive(self, qapp, theme):
        from app.ui.widgets.common import SegmentedControl

        control = SegmentedControl([("a", "A"), ("b", "B")])
        assert control.value() == "a"
        control.set_value("b")
        assert control.value() == "b"

    def test_empty_state_text_can_be_swapped(self, qapp, theme):
        from app.ui.widgets.common import EmptyState

        state = EmptyState(title="First", body="One")
        state.set_text("Second", "Two")
        assert state._title.text() == "Second"

    def test_thumbnail_handles_a_missing_file(self, qapp, theme):
        from app.ui.widgets.thumbnail import Thumbnail

        thumb = Thumbnail()
        assert thumb.set_source("/nowhere/missing.jpg") is False
        assert thumb.has_image() is False

    def test_flow_layout_wraps(self, qapp, theme):
        from PySide6.QtWidgets import QLabel, QWidget

        from app.ui.widgets.common import FlowLayout

        host = QWidget()
        layout = FlowLayout(host)
        for _ in range(10):
            label = QLabel("chip")
            label.setFixedSize(100, 20)
            layout.addWidget(label)
        assert layout.heightForWidth(250) > 20


class TestOnboarding:
    def test_it_builds_and_completes(self, qapp, theme, store, settings):
        from app.ui.views.onboarding import OnboardingDialog

        store.update({"first_run_complete": False})
        wizard = OnboardingDialog(store)

        wizard._root_input.setText(settings.library_root)
        wizard._next()   # welcome -> folder
        wizard._next()   # folder -> tools (creates the tree)
        wizard._finish()

        assert store.settings.first_run_complete is True
        from pathlib import Path

        assert (Path(settings.library_root) / "Audio" / "Sound Effects").is_dir()
        wizard.deleteLater()

    def test_an_unwritable_folder_is_reported_rather_than_crashing(self, qapp, theme, store):
        from app.ui.views.onboarding import OnboardingDialog

        wizard = OnboardingDialog(store)
        wizard._root_input.setText("")
        wizard._step = 1
        assert wizard._commit_folder() is False
        assert wizard._folder_error.isVisible() or wizard._folder_error.text()
        wizard.deleteLater()
