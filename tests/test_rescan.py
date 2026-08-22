"""Rescan Library: reconciling the index with what is actually on disk."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.rescan_service import RescanService


@pytest.fixture
def rescan(settings, library, organizer):
    return RescanService(settings, library, organizer)


def _write(root: Path, relative: str, size: int = 128) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * size)
    return path


class TestImport:
    def test_indexes_a_file_dropped_into_the_library(self, rescan, library, settings):
        root = Path(settings.library_root)
        _write(root, "Audio/Sound Effects/Dropped In.mp3")

        result = rescan.run()

        assert result.imported == 1
        item = library.search()[0]
        assert item.title == "Dropped In"
        assert item.category == "Sound Effects"
        assert item.media_kind == "audio"

    def test_infers_the_category_from_the_folder(self, rescan, library, settings):
        root = Path(settings.library_root)
        _write(root, "Inspiration/A Reel.mp4")
        _write(root, "Audio/Music/A Track.m4a")
        _write(root, "Video/A Clip.mp4")

        rescan.run()

        categories = {m.title: m.category for m in library.search()}
        assert categories == {
            "A Reel": "Inspiration",
            "A Track": "Music",
            "A Clip": "Video",
        }

    def test_a_loose_file_still_gets_a_sensible_home(self, rescan, library, settings):
        _write(Path(settings.library_root), "Random Folder/Stray.mp3")
        rescan.run()
        assert library.search()[0].category in ("Music", "Other")

    def test_ignores_non_media_files(self, rescan, library, settings):
        root = Path(settings.library_root)
        _write(root, "Video/notes.txt")
        _write(root, "Video/cover.jpg")
        _write(root, "Video/archive.zip")

        result = rescan.run()

        assert result.imported == 0
        assert library.count() == 0

    def test_skips_hidden_directories(self, rescan, library, settings):
        _write(Path(settings.library_root), ".hidden/Secret.mp3")
        assert rescan.run().imported == 0

    def test_does_not_reimport_something_already_indexed(self, rescan, library, settings):
        _write(Path(settings.library_root), "Video/Once.mp4")
        assert rescan.run().imported == 1
        assert rescan.run().imported == 0
        assert library.count() == 1

    def test_import_can_be_disabled(self, rescan, library, settings):
        _write(Path(settings.library_root), "Video/Ignored.mp4")
        assert rescan.run(import_new=False).imported == 0

    def test_a_missing_library_root_does_not_crash(self, settings, library):
        settings.library_root = "/nowhere/at/all"
        result = RescanService(settings, library).run()
        assert result.imported == 0


class TestReconciliation:
    def test_flags_a_deleted_file(self, rescan, library, settings, make_item):
        library.add(make_item(file_path=str(Path(settings.library_root) / "gone.mp3")))
        result = rescan.run()
        assert result.missing == 1
        assert library.search()[0].file_missing is True

    def test_recovers_a_file_that_came_back(self, rescan, library, settings, make_item):
        path = _write(Path(settings.library_root), "Video/Back.mp4")
        media_id = library.add(
            make_item(file_path=str(path), filename=path.name, media_kind="video")
        )
        library.update_fields(media_id, file_missing=1)

        assert rescan.run().recovered == 1
        assert library.get(media_id).file_missing is False

    def test_relocates_a_file_the_user_moved(self, rescan, library, settings, make_item):
        root = Path(settings.library_root)
        moved = _write(root, "Audio/Music/Moved Track.m4a")
        media_id = library.add(
            make_item(
                file_path=str(root / "Audio" / "Sound Effects" / "Moved Track.m4a"),
                filename="Moved Track.m4a",
            )
        )

        result = rescan.run()

        assert result.relocated == 1
        assert library.get(media_id).file_path == str(moved)

    def test_updates_a_size_that_changed_on_disk(self, rescan, library, settings, make_item):
        path = _write(Path(settings.library_root), "Video/Resized.mp4", size=999)
        library.add(
            make_item(file_path=str(path), filename=path.name, file_size=1, media_kind="video")
        )
        assert rescan.run().resized == 1
        assert library.search()[0].file_size == 999

    def test_summary_reads_sensibly(self, rescan, settings):
        _write(Path(settings.library_root), "Video/New.mp4")
        assert "1 new file" in rescan.run().summary()

    def test_summary_when_nothing_changed(self, rescan):
        assert "up to date" in rescan.run().summary()

    def test_imported_files_are_searchable(self, rescan, library, settings):
        from app.services.library_service import LibraryQuery

        _write(Path(settings.library_root), "Audio/Sound Effects/Findable Whoosh.mp3")
        rescan.run()
        assert len(library.search(LibraryQuery(text="whoosh"))) == 1
