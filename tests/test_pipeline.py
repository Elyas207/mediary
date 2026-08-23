"""The whole download pipeline with yt-dlp mocked out.

This is the acceptance test from the product brief - URL to organised, indexed,
searchable library entry - executed entirely offline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.downloader.manager import DownloadResult
from app.models.download import DownloadOptions, DownloadStatus, MediaInfo


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def pipeline(qapp, settings, library, organizer):
    """A DownloadService wired to a real library and organiser."""
    from app.downloader.manager import DownloadManager
    from app.services.download_service import DownloadService

    manager = DownloadManager(settings)
    service = DownloadService(settings, manager, library, organizer)
    yield service, manager, library, settings
    manager.shutdown(500)


def _downloaded(tmp_path: Path, name: str, size: int = 2048) -> Path:
    """Stand in for the file a worker just produced in staging."""
    staging = tmp_path / "staging"
    staging.mkdir(exist_ok=True)
    path = staging / name
    path.write_bytes(b"\0" * size)
    return path


def _complete(service, manager, task, file_path, info, probe=None, thumbnail=None):
    result = DownloadResult(task.id, file_path, info, probe or {}, thumbnail)
    manager.task_completed.emit(task, result)
    return task


class TestSoundEffectAcceptance:
    """Paste a URL, choose MP3 / 320 kbps / Sound Effects, download."""

    def test_lands_in_the_right_folder_and_the_library(self, pipeline, tmp_path):
        service, manager, library, settings = pipeline

        options = DownloadOptions(
            media_kind="audio", audio_format="mp3", audio_bitrate="320",
            category="Sound Effects",
        )
        info = MediaInfo(
            url="https://example.com/whoosh",
            title="Epic Cinematic Whoosh",
            creator="Example Creator",
            platform="YouTube",
            platform_id="whoosh123",
            duration=12,
        )
        task = manager.enqueue(info.url, options, info, start=False)
        source = _downloaded(tmp_path, "staged.mp3")

        _complete(
            service, manager, task, source, info,
            probe={"duration": 12.0, "audio_codec": "mp3", "audio_bitrate": 320,
                   "sample_rate": 44100},
        )

        expected = (
            Path(settings.library_root)
            / "Audio" / "Sound Effects" / "Epic Cinematic Whoosh.mp3"
        )
        assert expected.is_file(), "file must be organised into its category folder"
        assert not source.exists(), "the staging copy must be moved, not copied"

        item = library.get_by_path(str(expected))
        assert item is not None
        assert item.title == "Epic Cinematic Whoosh"
        assert item.category == "Sound Effects"
        assert item.media_kind == "audio"
        assert item.audio_bitrate == 320
        assert item.source_url == "https://example.com/whoosh"
        assert item.platform == "YouTube"

        assert task.status == DownloadStatus.COMPLETE
        assert task.media_id == item.id

    def test_it_is_findable_by_search(self, pipeline, tmp_path):
        from app.services.library_service import LibraryQuery

        service, manager, library, _ = pipeline
        info = MediaInfo(url="https://x/1", title="Epic Cinematic Whoosh", platform="YouTube")
        task = manager.enqueue(
            info.url, DownloadOptions(media_kind="audio", category="Sound Effects"), info,
            start=False,
        )
        _complete(service, manager, task, _downloaded(tmp_path, "a.mp3"), info)

        assert len(library.search(LibraryQuery(text="whoosh"))) == 1

    def test_licensing_starts_unknown_and_persists_once_set(self, pipeline, tmp_path):
        from app.models.media import ATTRIBUTION_YES, LICENSE_ROYALTY_FREE

        service, manager, library, _ = pipeline
        info = MediaInfo(url="https://x/2", title="A Track", platform="Web")
        task = manager.enqueue(
            info.url, DownloadOptions(media_kind="audio", audio_format="m4a", category="Music"),
            info, start=False,
        )
        _complete(service, manager, task, _downloaded(tmp_path, "b.m4a"), info)

        item = library.get(task.media_id)
        assert item.license_type == "Unknown", "Mediary must never assume a licence"

        item.license_type = LICENSE_ROYALTY_FREE
        item.license_url = "https://example.com/license"
        item.attribution_required = ATTRIBUTION_YES
        item.license_notes = "Credit creator."
        library.update(item)

        reloaded = library.get(item.id)
        assert reloaded.license_type == LICENSE_ROYALTY_FREE
        assert reloaded.attribution_required == ATTRIBUTION_YES
        assert reloaded.license_notes == "Credit creator."


class TestInspirationAcceptance:
    def test_video_lands_in_inspiration(self, pipeline, tmp_path):
        service, manager, library, settings = pipeline
        info = MediaInfo(
            url="https://www.instagram.com/reel/abc/",
            title="Handheld Reel Reference",
            creator="Studio Kern",
            platform="Instagram",
            platform_id="abc",
        )
        options = DownloadOptions(
            media_kind="video", video_format="mp4", video_quality="1080p",
            category="Inspiration",
        )
        task = manager.enqueue(info.url, options, info, start=False)

        _complete(
            service, manager, task, _downloaded(tmp_path, "reel.mp4"), info,
            probe={"width": 1080, "height": 1920, "fps": 30.0, "video_codec": "h264",
                   "audio_codec": "aac", "duration": 34.0},
        )

        expected = Path(settings.library_root) / "Inspiration" / "Handheld Reel Reference.mp4"
        assert expected.is_file()

        item = library.get_by_path(str(expected))
        assert item.category == "Inspiration"
        assert item.media_kind == "video"
        assert item.resolution == "1080x1920"
        assert item.fps == 30.0
        assert item.source_url == info.url


class TestBatchAcceptance:
    def test_ten_downloads_all_land_correctly(self, pipeline, tmp_path):
        service, manager, library, settings = pipeline

        for index in range(10):
            info = MediaInfo(
                url=f"https://example.com/item{index}",
                title=f"Batch Item {index:02d}",
                platform="Web",
                platform_id=f"item{index}",
            )
            options = DownloadOptions(
                media_kind="audio", audio_format="mp3", category="Sound Effects"
            )
            task = manager.enqueue(info.url, options, info, start=False)
            _complete(service, manager, task, _downloaded(tmp_path, f"batch{index}.mp3"), info)

        assert library.count() == 10
        folder = Path(settings.library_root) / "Audio" / "Sound Effects"
        assert len(list(folder.glob("*.mp3"))) == 10
        assert all(t.status == DownloadStatus.COMPLETE for t in manager.tasks)

    def test_a_failure_does_not_stop_the_rest(self, pipeline, tmp_path):
        service, manager, library, _ = pipeline

        good = manager.enqueue(
            "https://example.com/ok",
            DownloadOptions(media_kind="audio", category="Music"),
            MediaInfo(url="https://example.com/ok", title="Good"),
            start=False,
        )
        bad = manager.enqueue(
            "https://example.com/private",
            DownloadOptions(media_kind="audio", category="Music"),
            MediaInfo(url="https://example.com/private", title="Private"),
            start=False,
        )

        manager.mark_failed(bad, "This content is private.", "raw detail")
        _complete(service, manager, good, _downloaded(tmp_path, "ok.mp3"), good.info)

        assert good.status == DownloadStatus.COMPLETE
        assert bad.status == DownloadStatus.FAILED
        assert library.count() == 1

        counts = manager.counts()
        assert counts["complete"] == 1 and counts["failed"] == 1


class TestDuplicateHandling:
    def test_a_second_download_of_the_same_url_is_detected(self, pipeline, tmp_path):
        service, manager, library, _ = pipeline
        info = MediaInfo(url="https://example.com/dup", title="Dup", platform="Web",
                         platform_id="dup1")
        task = manager.enqueue(
            info.url, DownloadOptions(media_kind="audio", category="Music"), info, start=False
        )
        _complete(service, manager, task, _downloaded(tmp_path, "dup.mp3"), info)

        match = service.check_duplicate(info.url, info)
        assert match is not None
        assert match.item.title == "Dup"

    def test_a_deliberate_duplicate_is_never_blocked(self, pipeline, tmp_path):
        service, manager, library, settings = pipeline
        info = MediaInfo(url="https://example.com/twice", title="Twice", platform="Web")

        for name in ("first.mp3", "second.mp3"):
            task = manager.enqueue(
                info.url, DownloadOptions(media_kind="audio", category="Music"), info,
                start=False,
            )
            _complete(service, manager, task, _downloaded(tmp_path, name), info)

        folder = Path(settings.library_root) / "Audio" / "Music"
        names = sorted(p.name for p in folder.glob("*.mp3"))
        assert names == ["Twice (1).mp3", "Twice.mp3"]
        assert library.count() == 2

    def test_replace_overwrites_in_place(self, pipeline, tmp_path):
        service, manager, library, settings = pipeline
        info = MediaInfo(url="https://example.com/rep", title="Replaceable", platform="Web")

        first = manager.enqueue(
            info.url, DownloadOptions(media_kind="audio", category="Music"), info, start=False
        )
        _complete(service, manager, first, _downloaded(tmp_path, "v1.mp3", size=100), info)

        original = library.get(first.media_id)
        library.update_fields(original.id, notes="keep me")

        second = service.queue(
            info.url,
            DownloadOptions(media_kind="audio", category="Music"),
            info,
            replace_path=original.file_path,
            start=False,        # the suite must never touch the network
        )
        _complete(service, manager, second, _downloaded(tmp_path, "v2.mp3", size=500), info)

        assert library.count() == 1, "replacing must not create a second entry"
        updated = library.get(original.id)
        assert updated.file_size == 500
        assert updated.notes == "keep me", "user data must survive a replace"


class TestOrganisationToggles:
    def test_auto_organise_off_saves_to_the_root(self, pipeline, tmp_path):
        service, manager, library, settings = pipeline
        settings.auto_organize = False

        info = MediaInfo(url="https://x/flat", title="Flat File", platform="Web")
        task = manager.enqueue(
            info.url, DownloadOptions(media_kind="audio", category="Music"), info, start=False
        )
        _complete(service, manager, task, _downloaded(tmp_path, "flat.mp3"), info)

        assert (Path(settings.library_root) / "Flat File.mp3").is_file()

    def test_auto_index_off_still_saves_the_file(self, pipeline, tmp_path):
        service, manager, library, settings = pipeline
        settings.auto_add_to_library = False

        info = MediaInfo(url="https://x/unindexed", title="Unindexed", platform="Web")
        task = manager.enqueue(
            info.url, DownloadOptions(media_kind="audio", category="Music"), info, start=False
        )
        _complete(service, manager, task, _downloaded(tmp_path, "un.mp3"), info)

        assert (Path(settings.library_root) / "Audio" / "Music" / "Unindexed.mp3").is_file()
        assert library.count() == 0

    def test_the_filename_template_is_applied(self, pipeline, tmp_path):
        service, manager, library, settings = pipeline
        settings.filename_template = "{creator} - {title}"

        info = MediaInfo(url="https://x/t", title="Track", creator="Artist", platform="Web")
        task = manager.enqueue(
            info.url, DownloadOptions(media_kind="audio", category="Music"), info, start=False
        )
        _complete(service, manager, task, _downloaded(tmp_path, "t.mp3"), info)

        assert (Path(settings.library_root) / "Audio" / "Music" / "Artist - Track.mp3").is_file()


class TestFailureHandling:
    def test_a_vanished_staging_file_fails_gracefully(self, pipeline, tmp_path):
        service, manager, library, _ = pipeline
        info = MediaInfo(url="https://x/lost", title="Lost", platform="Web")
        task = manager.enqueue(
            info.url, DownloadOptions(media_kind="audio", category="Music"), info, start=False
        )

        _complete(service, manager, task, tmp_path / "staging" / "never-existed.mp3", info)

        assert task.status == DownloadStatus.FAILED
        assert task.error
        assert library.count() == 0

    def test_download_history_records_both_outcomes(self, pipeline, tmp_path):
        service, manager, library, _ = pipeline

        ok_info = MediaInfo(url="https://x/ok", title="OK", platform="Web")
        ok = manager.enqueue(
            ok_info.url, DownloadOptions(media_kind="audio", category="Music"), ok_info,
            start=False,
        )
        _complete(service, manager, ok, _downloaded(tmp_path, "ok.mp3"), ok_info)

        bad = manager.enqueue(
            "https://x/bad", DownloadOptions(media_kind="audio", category="Music"),
            MediaInfo(url="https://x/bad", title="Bad"), start=False,
        )
        manager.mark_failed(bad, "Nope")

        statuses = {row["status"] for row in library.recent_downloads()}
        assert statuses == {"Complete", "Failed"}


class TestThumbnails:
    def test_a_sidecar_thumbnail_is_cached_and_linked(self, pipeline, tmp_path):
        from app.utils.paths import thumbnails_dir

        service, manager, library, _ = pipeline
        info = MediaInfo(url="https://x/art", title="With Art", platform="Web",
                         platform_id="art1")
        task = manager.enqueue(
            info.url, DownloadOptions(media_kind="audio", category="Music"), info, start=False
        )

        thumb = tmp_path / "staging" / "art.jpg"
        thumb.parent.mkdir(exist_ok=True)
        thumb.write_bytes(b"\xff\xd8\xff")

        _complete(
            service, manager, task, _downloaded(tmp_path, "art.mp3"), info, thumbnail=thumb
        )

        item = library.get(task.media_id)
        assert item.thumbnail_path
        assert Path(item.thumbnail_path).is_file()
        assert Path(item.thumbnail_path).parent == thumbnails_dir()


def test_no_test_starts_a_real_download(pipeline, tmp_path, monkeypatch):
    """A guard against the suite quietly acquiring a network dependency.

    DownloadService.queue() starts a worker by default, which is correct in
    production and wrong in a test. This fails loudly if anything in the suite
    ever reaches the real downloader again.
    """
    service, manager, _library, _settings = pipeline

    started = []
    monkeypatch.setattr(manager, "_start", lambda task: started.append(task))

    service.queue(
        "https://example.com/guard",
        DownloadOptions(media_kind="audio", category="Music"),
        MediaInfo(url="https://example.com/guard", title="Guard"),
        start=False,
    )
    assert started == [], "queue(start=False) must not launch a worker"

    service.queue(
        "https://example.com/live",
        DownloadOptions(media_kind="audio", category="Music"),
        MediaInfo(url="https://example.com/live", title="Live"),
    )
    assert len(started) == 1, "the production default must still start the download"
