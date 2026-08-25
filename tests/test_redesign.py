"""The three-pane shell and the widgets the redesign introduced.

These cover the places where the design and the truth can drift apart: format
rows that promise a file the source cannot produce, a queue row squeezed until
its title disappears, and a licence panel that looks like a verdict.
"""

from __future__ import annotations

import pytest

from app.models.download import FormatOption, MediaInfo
from app.ui.widgets.format_list import audio_choices, video_choices


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

    instance = Theme(qapp, "light")
    instance.apply()
    set_theme(instance)
    yield instance
    set_theme(None)


def ladder(*heights: int, audio: bool = True, duration: float = 200.0) -> MediaInfo:
    formats = [
        FormatOption(
            format_id=str(h), ext="mp4", width=h * 16 // 9, height=h,
            vcodec="avc1", acodec="none", filesize=h * 100_000,
        )
        for h in heights
    ]
    if audio:
        formats.append(
            FormatOption(format_id="a", ext="m4a", acodec="mp4a", abr=128, filesize=3_000_000)
        )
    return MediaInfo(url="https://example.com/x", title="t", duration=duration, formats=formats)


class TestVideoChoices:
    """A row is a promise about the file you will get."""

    def test_every_row_maps_to_a_real_stream(self):
        rows = video_choices(ladder(1080, 720, 480))
        assert [r.title for r in rows] == ["Best quality", "720p", "480p"]

    def test_a_quality_the_source_lacks_is_not_offered(self):
        rows = video_choices(ladder(1080, 480))
        assert "360p" not in [r.title for r in rows]

    def test_two_rows_never_share_a_stream(self):
        rows = video_choices(ladder(1080, 720))
        specs = [r.spec for r in rows if r.title != "Best quality"]
        assert len(specs) == len(set(specs))

    def test_a_muxed_size_includes_the_audio_it_is_paired_with(self):
        rows = video_choices(ladder(1080))
        assert rows[0].size == 1080 * 100_000 + 3_000_000

    def test_a_source_with_no_video_offers_no_rows(self):
        info = MediaInfo(
            url="u", title="t", duration=10.0,
            formats=[FormatOption(format_id="a", ext="mp3", acodec="mp3", abr=320)],
        )
        assert video_choices(info) == []

    def test_exactly_one_row_is_the_best(self):
        rows = video_choices(ladder(1080, 720, 480))
        assert sum(1 for r in rows if r.best) == 1


class TestAudioChoices:
    """Sizes here are arithmetic about a file that does not exist yet."""

    def test_a_conversion_size_is_marked_as_an_estimate(self):
        rows = audio_choices(ladder(1080))
        mp3 = next(r for r in rows if r.title == "MP3" and "320" in r.spec)
        assert mp3.estimated
        assert mp3.size_label().startswith("~")

    def test_a_size_the_source_reported_is_not_marked(self):
        rows = audio_choices(ladder(1080))
        best = rows[0]
        assert best.title == "Best quality"
        assert not best.estimated
        assert not best.size_label().startswith("~")

    def test_the_ladder_stays_short_enough_to_read(self):
        assert len(audio_choices(ladder(1080))) <= 8

    def test_lossless_rows_do_not_claim_a_bitrate(self):
        rows = audio_choices(ladder(1080))
        for name in ("WAV", "FLAC"):
            row = next(r for r in rows if r.title == name)
            assert row.spec == "Lossless"

    def test_an_unknown_duration_gives_no_invented_size(self):
        info = MediaInfo(url="u", title="t", duration=0.0, formats=[])
        assert all(r.size == 0 for r in audio_choices(info))


class TestFormatList:
    def test_picking_a_row_reports_its_value(self, qapp, theme):
        from app.ui.widgets.format_list import FormatList

        widget = FormatList("Video")
        widget.set_choices(video_choices(ladder(1080, 720)))
        seen: list = []
        widget.changed.connect(seen.append)

        widget._rows["720p"].radio.setChecked(True)
        assert widget.value() == "720p"
        assert seen == ["720p"]

    def test_auto_takes_the_rows_out_of_play(self, qapp, theme):
        """A control that looks live and ignores you is worse than a disabled one."""
        from app.ui.widgets.format_list import FormatList

        widget = FormatList("Video")
        widget.set_choices(video_choices(ladder(1080, 720)))
        widget.set_value("720p")
        widget.set_auto(True)

        assert not widget._rows_holder.isEnabled()
        assert widget.value() == "best"

    def test_an_empty_source_says_so(self, qapp, theme):
        from app.ui.widgets.format_list import FormatList

        widget = FormatList("Video")
        widget.set_choices([])
        assert widget._empty.isVisibleTo(widget)
        assert widget.value() == ""


class TestDownloadCardFormats:
    """The card, where the two panels decide the media kind between them."""

    @pytest.fixture
    def card(self, qapp, theme, settings, library):
        from app.services.filing_service import FilingService
        from app.ui.views.download_view import AnalysisCard

        return AnalysisCard(
            "r1", "https://example.com/x", settings, FilingService(library, settings)
        )

    def test_choosing_audio_switches_the_kind(self, card):
        card.set_info(ladder(1080))
        card.audio_formats._rows["mp3@320"].radio.setChecked(True)

        options = card.options()
        assert options.media_kind == "audio"
        assert options.audio_format == "mp3"
        assert options.audio_bitrate == "320"

    def test_choosing_video_switches_back(self, card):
        card.set_info(ladder(1080, 720))
        card.audio_formats._rows["mp3@320"].radio.setChecked(True)
        card.video_formats._rows["720p"].radio.setChecked(True)

        options = card.options()
        assert options.media_kind == "video"
        assert options.video_quality == "720p"

    def test_only_one_panel_holds_a_selection(self, card):
        card.set_info(ladder(1080, 720))
        card.audio_formats._rows["mp3@320"].radio.setChecked(True)
        assert card.video_formats.value() == ""
        assert card.audio_formats.value() == "mp3@320"

    def test_an_audio_only_source_hides_the_video_panel(self, card):
        info = MediaInfo(
            url="u", title="t", duration=10.0,
            formats=[FormatOption(format_id="a", ext="mp3", acodec="mp3", abr=320)],
        )
        card.set_info(info)
        assert not card.video_formats.isVisibleTo(card)
        assert card.options().media_kind == "audio"

    def test_best_quality_keeps_the_source_container(self, card):
        """Re-encoding an M4A into MP3 is not what best quality means."""
        info = MediaInfo(
            url="u", title="t", duration=10.0,
            formats=[FormatOption(format_id="a", ext="m4a", acodec="mp4a", abr=192)],
        )
        card.set_info(info)
        card.audio_formats.set_value("source")
        assert card.options().audio_format == "m4a"

    def test_tags_reach_the_download_options(self, card):
        card.set_info(ladder(1080))
        card.tag_input.setText("Cinematic")
        card.tag_input.returnPressed.emit()
        assert card.options().tags == ["Cinematic"]

    def test_the_same_tag_twice_is_still_one_tag(self, card):
        card.set_info(ladder(1080))
        for _ in range(2):
            card.tag_input.setText("cinematic")
            card.tag_input.returnPressed.emit()
        assert card.options().tags == ["cinematic"]


class TestQueueRowColumns:
    """Inline on the Download screen the row is far narrower than the queue."""

    def test_the_title_survives_a_narrow_row(self, qapp, theme):
        from app.models.download import DownloadOptions, DownloadTask
        from app.ui.widgets.queue_row import QueueRow

        task = DownloadTask(url="https://example.com/x", options=DownloadOptions())
        task.info = MediaInfo(url=task.url, title="A title long enough to matter")
        row = QueueRow(task)
        row.resize(560, 58)
        row.layout().activate()

        assert row.title.width() >= 100


class TestDetailPane:
    def test_it_starts_empty(self, qapp, theme):
        from app.ui.detail_pane import DetailPane

        pane = DetailPane()
        assert pane.item is None
        assert pane._empty.isVisibleTo(pane)

    def test_showing_an_item_fills_the_rows(self, qapp, theme, make_item):
        from app.ui.detail_pane import DetailPane

        item = make_item(title="Alpine Wind Bed", container="wav", duration=372.0)
        pane = DetailPane()
        pane.show_item(item)

        assert pane.item is item
        assert pane.title.text() == "Alpine Wind Bed"
        assert pane._rows["format"]._value.fullText() == "WAV"

    def test_clearing_goes_back_to_the_empty_state(self, qapp, theme, make_item):
        from app.ui.detail_pane import DetailPane

        pane = DetailPane()
        pane.show_item(make_item())
        pane.clear()
        assert pane.item is None
        assert pane._empty.isVisibleTo(pane)

    def test_licensing_defaults_to_unknown(self, qapp, theme, make_item):
        """Mediary must never present a licence as settled. These fields are the
        user's record of what they checked, not a verdict Mediary reached."""
        from app.models.media import ATTRIBUTION_UNKNOWN, LICENSE_UNKNOWN
        from app.ui.detail_pane import DetailPane

        pane = DetailPane()
        pane.show_item(make_item())
        assert pane.license_box.currentData() == LICENSE_UNKNOWN
        assert pane.attribution_box.currentData() == ATTRIBUTION_UNKNOWN

    def test_editing_a_licence_field_reports_the_change(self, qapp, theme, make_item):
        from app.ui.detail_pane import DetailPane

        pane = DetailPane()
        pane.show_item(make_item())
        seen: list = []
        pane.item_changed.connect(seen.append)

        pane.license_url.setText("https://example.com/licence")
        pane.license_url.editingFinished.emit()

        assert seen and seen[0].license_url == "https://example.com/licence"

    def test_loading_an_item_is_not_an_edit(self, qapp, theme, make_item):
        from app.ui.detail_pane import DetailPane

        pane = DetailPane()
        seen: list = []
        pane.item_changed.connect(seen.append)
        pane.show_item(make_item())
        assert seen == []

    def test_a_tag_can_be_added_and_removed(self, qapp, theme, make_item):
        from app.ui.detail_pane import DetailPane

        pane = DetailPane()
        pane.show_item(make_item(tags=[]))

        pane.tag_input.setText("Whoosh")
        pane.tag_input.returnPressed.emit()
        assert pane.item.tags == ["Whoosh"]

        pane._remove_tag("Whoosh")
        assert pane.item.tags == []

    def test_a_note_is_saved_when_focus_leaves_it(self, qapp, theme, make_item):
        """Notes commit on blur rather than per keystroke, so the commit path
        has to actually fire - a dropped note is invisible until it is gone."""
        from PySide6.QtCore import QEvent

        from app.ui.detail_pane import DetailPane

        pane = DetailPane()
        pane.show_item(make_item())
        seen: list = []
        pane.item_changed.connect(seen.append)

        pane.notes.setPlainText("Used in the March cut")
        pane.eventFilter(pane.notes, QEvent(QEvent.Type.FocusOut))

        assert seen and seen[0].notes == "Used in the March cut"

    def test_a_licence_note_commits_the_same_way(self, qapp, theme, make_item):
        from PySide6.QtCore import QEvent

        from app.ui.detail_pane import DetailPane

        pane = DetailPane()
        pane.show_item(make_item())
        seen: list = []
        pane.item_changed.connect(seen.append)

        pane.license_notes.setPlainText("Credit in description")
        pane.eventFilter(pane.license_notes, QEvent(QEvent.Type.FocusOut))

        assert seen and seen[0].license_notes == "Credit in description"
