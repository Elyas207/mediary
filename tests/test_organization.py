"""Path generation, the folder tree and non-destructive file placement."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.download import DownloadOptions
from app.services.organization_service import OrganizationError, OrganizationService


class TestFolderTree:
    def test_creates_the_documented_structure(self, organizer, settings):
        root = Path(settings.library_root)
        for expected in (
            "Video",
            "Inspiration",
            "Other",
            "Audio/Music",
            "Audio/Sound Effects",
            "Audio/Voice",
            "Audio/Ambience",
            "Audio/Foley",
        ):
            assert (root / expected).is_dir(), f"missing {expected}"

    def test_is_idempotent(self, organizer):
        assert organizer.ensure_library_tree() == []

    def test_reports_writability(self, organizer):
        ok, error = organizer.ensure_writable()
        assert ok and error == ""

    def test_leaves_no_probe_file_behind(self, organizer, settings):
        organizer.ensure_writable()
        assert not (Path(settings.library_root) / ".mediary-write-test").exists()


class TestCategoryDirectories:
    @pytest.mark.parametrize(
        "category,relative",
        [
            ("Video", "Video"),
            ("Inspiration", "Inspiration"),
            ("Music", "Audio/Music"),
            ("Sound Effects", "Audio/Sound Effects"),
            ("Voice", "Audio/Voice"),
            ("Ambience", "Audio/Ambience"),
            ("Foley", "Audio/Foley"),
            ("Other", "Other"),
        ],
    )
    def test_maps_each_builtin_category(self, organizer, settings, category, relative):
        expected = Path(settings.library_root).joinpath(*relative.split("/"))
        assert organizer.category_dir(category) == expected

    def test_an_unknown_category_gets_a_top_level_folder(self, organizer, settings):
        assert organizer.category_dir("Podcasts") == Path(settings.library_root) / "Podcasts"

    def test_a_category_name_is_sanitised(self, organizer, settings):
        folder = organizer.category_dir("Bad/Name")
        assert "/" not in folder.name and "\\" not in folder.name

    def test_every_path_stays_under_the_root(self, organizer, settings):
        root = Path(settings.library_root).resolve()
        for category in ("Video", "Music", "Other", "../escape"):
            assert organizer.category_dir(category).resolve().is_relative_to(root)


class TestDestination:
    def test_builds_the_expected_path(self, organizer, settings):
        path = organizer.destination_for(
            title="Epic Cinematic Whoosh",
            extension="mp3",
            category="Sound Effects",
        )
        assert path == Path(settings.library_root) / "Audio" / "Sound Effects" / "Epic Cinematic Whoosh.mp3"

    def test_avoids_an_existing_file(self, organizer):
        first = organizer.destination_for(title="Clip", extension="mp4", category="Video")
        first.parent.mkdir(parents=True, exist_ok=True)
        first.write_text("x")
        second = organizer.destination_for(title="Clip", extension="mp4", category="Video")
        assert second.name == "Clip (1).mp4"

    def test_sanitises_the_title(self, organizer):
        path = organizer.destination_for(
            title='Bad: Name / With * Chars?', extension="mp3", category="Music"
        )
        assert not set(path.name) & set('<>:"/\\|?*')

    def test_honours_the_filename_template(self, settings):
        settings.filename_template = "{creator} - {title}"
        organizer = OrganizationService(settings)
        path = organizer.destination_for(
            title="Whoosh", extension="mp3", category="Music", creator="Studio"
        )
        assert path.name == "Studio - Whoosh.mp3"

    def test_template_date_token_is_formatted(self, settings):
        settings.filename_template = "{date} {title}"
        organizer = OrganizationService(settings)
        path = organizer.destination_for(
            title="Clip", extension="mp4", category="Video", upload_date="20250104"
        )
        assert path.name == "2025-01-04 Clip.mp4"

    def test_preview_matches_what_a_download_would_produce(self, organizer, settings):
        options = DownloadOptions(
            media_kind="audio", audio_format="mp3", audio_bitrate="320",
            category="Sound Effects",
        )
        preview = organizer.preview_destination(options, "Whoosh")
        actual = organizer.destination_for(
            title="Whoosh", extension="mp3", category="Sound Effects",
            quality=options.quality_label(),
        )
        assert preview == actual


class TestPlacement:
    def test_moves_the_file(self, organizer, settings, real_file):
        source = real_file("temp.mp3", size=32)
        destination = Path(settings.library_root) / "Audio" / "Music" / "Song.mp3"
        final = organizer.place(source, destination)
        assert final == destination
        assert final.is_file() and final.stat().st_size == 32
        assert not source.exists()

    def test_creates_missing_parent_directories(self, organizer, settings, real_file):
        source = real_file("temp.mp3")
        destination = Path(settings.library_root) / "Deep" / "Nested" / "Song.mp3"
        assert organizer.place(source, destination).is_file()

    def test_never_silently_overwrites(self, organizer, settings, real_file):
        destination = Path(settings.library_root) / "Video" / "Clip.mp4"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("original")

        final = organizer.place(real_file("new.mp4"), destination)
        assert final != destination
        assert final.name == "Clip (1).mp4"
        assert destination.read_text() == "original"

    def test_replace_is_explicit(self, organizer, settings, real_file):
        destination = Path(settings.library_root) / "Video" / "Clip.mp4"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("original")

        final = organizer.place(real_file("new.mp4", size=9), destination, replace=True)
        assert final == destination
        assert destination.stat().st_size == 9

    def test_a_missing_source_raises_a_clear_error(self, organizer, settings):
        with pytest.raises(OrganizationError, match="missing"):
            organizer.place(
                Path("/nowhere/gone.mp3"),
                Path(settings.library_root) / "Video" / "x.mp3",
            )

    def test_placing_a_file_onto_itself_is_a_no_op(self, organizer, settings, real_file):
        source = real_file("same.mp3")
        assert organizer.place(source, source) == source
        assert source.exists()


class TestThumbnails:
    def test_stores_a_thumbnail_in_the_cache(self, organizer, real_file):
        from app.utils.paths import thumbnails_dir

        source = real_file("art.jpg", size=16)
        stored = organizer.store_thumbnail(source, "youtube-abc123")
        assert stored
        assert Path(stored).is_file()
        assert Path(stored).parent == thumbnails_dir()

    def test_a_missing_thumbnail_returns_empty(self, organizer):
        assert organizer.store_thumbnail(Path("/nowhere/x.jpg"), "key") == ""

    def test_finds_a_sidecar_image(self, organizer, tmp_path):
        media = tmp_path / "clip.mp4"
        media.write_text("x")
        (tmp_path / "clip.jpg").write_text("x")
        assert OrganizationService.find_sidecar_thumbnail(media).name == "clip.jpg"

    def test_no_sidecar_returns_none(self, organizer, tmp_path):
        media = tmp_path / "clip.mp4"
        media.write_text("x")
        assert OrganizationService.find_sidecar_thumbnail(media) is None

    def test_cleanup_removes_sidecars_but_keeps_the_media(self, organizer, tmp_path):
        media = tmp_path / "clip.mp4"
        media.write_text("x")
        for name in ("clip.jpg", "clip.webp", "clip.part", "clip.ytdl"):
            (tmp_path / name).write_text("x")

        OrganizationService.cleanup_sidecars(media)

        assert media.exists()
        assert not (tmp_path / "clip.jpg").exists()
        assert not (tmp_path / "clip.part").exists()

    def test_cleanup_copes_with_glob_characters_in_the_name(self, organizer, tmp_path):
        media = tmp_path / "clip [special].mp4"
        media.write_text("x")
        (tmp_path / "clip [special].jpg").write_text("x")
        OrganizationService.cleanup_sidecars(media)
        assert media.exists()
        assert not (tmp_path / "clip [special].jpg").exists()
