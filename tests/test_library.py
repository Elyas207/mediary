"""Library service: CRUD, search, tags, favourites, duplicates and integrity."""

from __future__ import annotations

import pytest

from app.models.media import (
    ATTRIBUTION_YES,
    LICENSE_CREATIVE_COMMONS,
    LICENSE_UNKNOWN,
    MediaItem,
)
from app.services.library_service import DuplicateMatch, LibraryQuery


@pytest.fixture
def populated(library, make_item):
    """A small but realistic library."""
    items = {
        "whoosh": library.add(
            make_item(
                title="Epic Cinematic Whoosh",
                filename="Epic Cinematic Whoosh.mp3",
                file_path="/lib/Audio/Sound Effects/Epic Cinematic Whoosh.mp3",
                creator="Example Creator",
                category="Sound Effects",
                media_kind="audio",
                source_url="https://example.com/whoosh",
                platform="YouTube",
                platform_id="whoosh123",
                notes="Great for hard cuts.",
            ),
            tags=["Whoosh", "Cinematic", "Transition"],
        ),
        "bed": library.add(
            make_item(
                title="Dark Ambient Bed",
                filename="Dark Ambient Bed.wav",
                file_path="/lib/Audio/Music/Dark Ambient Bed.wav",
                creator="Nightsound",
                category="Music",
                media_kind="audio",
                source_url="https://example.com/bed",
                platform="SoundCloud",
                platform_id="bed456",
            ),
            tags=["Ambient", "Dark"],
        ),
        "reel": library.add(
            make_item(
                title="Handheld Reel Reference",
                filename="Handheld Reel Reference.mp4",
                file_path="/lib/Inspiration/Handheld Reel Reference.mp4",
                creator="Studio Kern",
                category="Inspiration",
                media_kind="video",
                source_url="https://example.com/reel",
                platform="Instagram",
                platform_id="reel789",
                width=1080,
                height=1920,
            ),
            tags=["Motion", "Cinematic"],
        ),
    }
    return items


class TestCrud:
    def test_add_returns_an_id(self, library, make_item):
        media_id = library.add(make_item())
        assert isinstance(media_id, int) and media_id > 0

    def test_add_then_get_round_trips(self, library, make_item):
        media_id = library.add(make_item(title="Round Trip", notes="hello"))
        item = library.get(media_id)
        assert item is not None
        assert item.title == "Round Trip"
        assert item.notes == "hello"
        assert item.id == media_id

    def test_get_missing_returns_none(self, library):
        assert library.get(9999) is None

    def test_get_by_path(self, library, make_item):
        library.add(make_item(file_path="/lib/x.mp3"))
        assert library.get_by_path("/lib/x.mp3") is not None
        assert library.get_by_path("/lib/nope.mp3") is None

    def test_update_persists(self, library, make_item):
        media_id = library.add(make_item(title="Before"))
        item = library.get(media_id)
        item.title = "After"
        item.license_type = LICENSE_CREATIVE_COMMONS
        item.attribution_required = ATTRIBUTION_YES
        item.license_url = "https://creativecommons.org/licenses/by/4.0/"
        item.license_notes = "Credit creator in the description."
        library.update(item)

        reloaded = library.get(media_id)
        assert reloaded.title == "After"
        assert reloaded.license_type == LICENSE_CREATIVE_COMMONS
        assert reloaded.attribution_required == ATTRIBUTION_YES
        assert "creativecommons.org" in reloaded.license_url
        assert reloaded.license_notes.startswith("Credit")

    def test_update_without_an_id_raises(self, library, make_item):
        with pytest.raises(ValueError):
            library.update(make_item())

    def test_update_fields_patches_only_what_is_given(self, library, make_item):
        media_id = library.add(make_item(title="Keep", creator="Original"))
        library.update_fields(media_id, creator="Changed")
        item = library.get(media_id)
        assert item.title == "Keep"
        assert item.creator == "Changed"

    def test_update_fields_ignores_unknown_columns(self, library, make_item):
        media_id = library.add(make_item())
        assert library.update_fields(media_id, not_a_column="x") is False

    def test_a_new_item_defaults_to_unknown_licensing(self, library, make_item):
        # Mediary must never assume anything about reuse rights.
        item = library.get(library.add(make_item()))
        assert item.license_type == LICENSE_UNKNOWN
        assert item.attribution_required == "Unknown"

    def test_duplicate_file_path_is_rejected(self, library, make_item):
        library.add(make_item(file_path="/lib/same.mp3"))
        import sqlite3

        with pytest.raises(sqlite3.IntegrityError):
            library.add(make_item(file_path="/lib/same.mp3"))


class TestSearch:
    def test_no_query_returns_everything(self, library, populated):
        assert len(library.search()) == 3

    def test_by_title(self, library, populated):
        results = library.search(LibraryQuery(text="whoosh"))
        assert [m.title for m in results] == ["Epic Cinematic Whoosh"]

    def test_is_case_insensitive(self, library, populated):
        assert len(library.search(LibraryQuery(text="WHOOSH"))) == 1

    def test_partial_matching(self, library, populated):
        # Matches the title of one item and the "Cinematic" tag on two.
        titles = {m.title for m in library.search(LibraryQuery(text="cinemat"))}
        assert titles == {"Epic Cinematic Whoosh", "Handheld Reel Reference"}
        assert library.search(LibraryQuery(text="cinematx")) == []

    def test_multiple_terms_are_and_ed(self, library, populated):
        assert len(library.search(LibraryQuery(text="cinematic whoosh"))) == 1
        assert len(library.search(LibraryQuery(text="cinematic zzz"))) == 0

    def test_by_creator(self, library, populated):
        results = library.search(LibraryQuery(text="nightsound"))
        assert [m.title for m in results] == ["Dark Ambient Bed"]

    def test_by_tag(self, library, populated):
        results = library.search(LibraryQuery(text="ambient"))
        assert any(m.title == "Dark Ambient Bed" for m in results)

    def test_by_notes(self, library, populated):
        results = library.search(LibraryQuery(text="hard cuts"))
        assert [m.title for m in results] == ["Epic Cinematic Whoosh"]

    def test_no_match_returns_empty(self, library, populated):
        assert library.search(LibraryQuery(text="zzzzzz")) == []

    def test_punctuation_in_the_query_does_not_break_it(self, library, populated):
        assert library.search(LibraryQuery(text='"whoosh" (cinematic)')) is not None

    def test_filter_by_kind(self, library, populated):
        assert len(library.search(LibraryQuery(media_kind="audio"))) == 2
        assert len(library.search(LibraryQuery(media_kind="video"))) == 1

    def test_filter_by_category(self, library, populated):
        results = library.search(LibraryQuery(category="Sound Effects"))
        assert [m.title for m in results] == ["Epic Cinematic Whoosh"]

    def test_filter_by_multiple_categories(self, library, populated):
        results = library.search(LibraryQuery(categories=["Music", "Inspiration"]))
        assert len(results) == 2

    def test_tag_filter_requires_every_tag(self, library, populated):
        assert len(library.search(LibraryQuery(tags=["Cinematic"]))) == 2
        assert len(library.search(LibraryQuery(tags=["Cinematic", "Whoosh"]))) == 1
        assert len(library.search(LibraryQuery(tags=["Cinematic", "Dark"]))) == 0

    def test_favourites_filter(self, library, populated):
        library.set_favorite(populated["whoosh"], True)
        results = library.search(LibraryQuery(favorites_only=True))
        assert [m.title for m in results] == ["Epic Cinematic Whoosh"]

    def test_combined_filters(self, library, populated):
        results = library.search(
            LibraryQuery(text="cinematic", media_kind="audio", tags=["Whoosh"])
        )
        assert len(results) == 1

    def test_sorting_by_title(self, library, populated):
        titles = [m.title for m in library.search(LibraryQuery(sort="title"))]
        assert titles == sorted(titles, key=str.lower)

    def test_sorting_by_title_descending(self, library, populated):
        titles = [m.title for m in library.search(LibraryQuery(sort="title_desc"))]
        assert titles == sorted(titles, key=str.lower, reverse=True)

    def test_limit_and_offset(self, library, populated):
        page1 = library.search(LibraryQuery(sort="title", limit=2, offset=0))
        page2 = library.search(LibraryQuery(sort="title", limit=2, offset=2))
        assert len(page1) == 2 and len(page2) == 1
        assert {m.id for m in page1}.isdisjoint({m.id for m in page2})

    def test_count_matches_search(self, library, populated):
        query = LibraryQuery(media_kind="audio")
        assert library.count(query) == len(library.search(query))

    def test_count_with_tag_filter(self, library, populated):
        query = LibraryQuery(tags=["Cinematic"])
        assert library.count(query) == len(library.search(query))

    def test_search_results_carry_their_tags(self, library, populated):
        item = next(m for m in library.search() if m.title == "Epic Cinematic Whoosh")
        assert set(item.tags) == {"Whoosh", "Cinematic", "Transition"}


class TestTags:
    def test_add_and_list(self, library, make_item):
        media_id = library.add(make_item())
        library.add_tag(media_id, "Whoosh")
        assert library.tags_for(media_id) == ["Whoosh"]

    def test_tags_are_deduplicated_case_insensitively(self, library, make_item):
        media_id = library.add(make_item())
        library.add_tag(media_id, "Whoosh")
        library.add_tag(media_id, "whoosh")
        assert len(library.all_tags()) == 1

    def test_whitespace_is_normalised(self, library, make_item):
        media_id = library.add(make_item())
        library.add_tag(media_id, "  Sound   Design  ")
        assert library.tags_for(media_id) == ["Sound Design"]

    def test_empty_tag_is_rejected(self, library, make_item):
        media_id = library.add(make_item())
        assert library.add_tag(media_id, "   ") is False
        assert library.tags_for(media_id) == []

    def test_remove_tag(self, library, make_item):
        media_id = library.add(make_item())
        library.set_tags(media_id, ["A", "B"])
        library.remove_tag(media_id, "A")
        assert library.tags_for(media_id) == ["B"]

    def test_set_tags_replaces(self, library, make_item):
        media_id = library.add(make_item())
        library.set_tags(media_id, ["A", "B"])
        library.set_tags(media_id, ["C"])
        assert library.tags_for(media_id) == ["C"]

    def test_rename_tag(self, library, populated):
        library.rename_tag("Cinematic", "Epic")
        assert "Epic" in library.all_tags()
        assert "Cinematic" not in library.all_tags()
        assert len(library.search(LibraryQuery(tags=["Epic"]))) == 2

    def test_rename_into_an_existing_tag_merges(self, library, populated):
        library.rename_tag("Whoosh", "Cinematic")
        assert "Whoosh" not in library.all_tags()
        item = library.get(populated["whoosh"])
        assert item.tags.count("Cinematic") == 1

    def test_rename_a_missing_tag_is_a_no_op(self, library):
        assert library.rename_tag("nope", "other") is False

    def test_delete_tag_removes_it_everywhere(self, library, populated):
        library.delete_tag("Cinematic")
        assert "Cinematic" not in library.all_tags()
        assert library.tags_for(populated["whoosh"]) == ["Transition", "Whoosh"]

    def test_counts(self, library, populated):
        counts = dict(library.all_tags(with_counts=True))
        assert counts["Cinematic"] == 2
        assert counts["Whoosh"] == 1

    def test_prune_orphans(self, library, make_item):
        media_id = library.add(make_item())
        library.add_tag(media_id, "Used")
        library.ensure_tag("Unused")
        assert library.prune_orphan_tags() == 1
        assert library.all_tags() == ["Used"]

    def test_deleting_media_releases_its_tags(self, library, populated):
        library.remove(populated["whoosh"])
        assert library.prune_orphan_tags() >= 1


class TestFavorites:
    def test_toggle(self, library, make_item):
        media_id = library.add(make_item())
        assert library.toggle_favorite(media_id) is True
        assert library.get(media_id).favorite is True
        assert library.toggle_favorite(media_id) is False
        assert library.get(media_id).favorite is False

    def test_set_explicitly(self, library, make_item):
        media_id = library.add(make_item())
        library.set_favorite(media_id, True)
        assert library.get(media_id).favorite is True


class TestDuplicates:
    def test_by_source_url(self, library, populated):
        match = library.find_duplicate(source_url="https://example.com/whoosh")
        assert match is not None
        assert match.reason == DuplicateMatch.BY_URL
        assert match.item.title == "Epic Cinematic Whoosh"

    def test_by_platform_id(self, library, populated):
        match = library.find_duplicate(
            source_url="https://other.example/x", platform="YouTube", platform_id="whoosh123"
        )
        assert match is not None
        assert match.reason == DuplicateMatch.BY_PLATFORM_ID

    def test_platform_id_must_match_the_same_platform(self, library, populated):
        match = library.find_duplicate(platform="Vimeo", platform_id="whoosh123")
        assert match is None

    def test_by_file_path(self, library, populated):
        match = library.find_duplicate(
            file_path="/lib/Audio/Sound Effects/Epic Cinematic Whoosh.mp3"
        )
        assert match is not None
        assert match.reason == DuplicateMatch.BY_PATH

    def test_by_filename(self, library, populated):
        match = library.find_duplicate(filename="Epic Cinematic Whoosh.mp3")
        assert match is not None
        assert match.reason == DuplicateMatch.BY_FILENAME

    def test_no_match(self, library, populated):
        assert library.find_duplicate(source_url="https://nowhere.example/x") is None

    def test_empty_platform_id_never_matches(self, library, make_item):
        library.add(make_item(platform="YouTube", platform_id=""))
        assert library.find_duplicate(platform="YouTube", platform_id="") is None

    def test_url_wins_over_filename(self, library, populated):
        match = library.find_duplicate(
            source_url="https://example.com/whoosh", filename="Dark Ambient Bed.wav"
        )
        assert match.reason == DuplicateMatch.BY_URL

    def test_has_a_readable_description(self, library, populated):
        match = library.find_duplicate(source_url="https://example.com/whoosh")
        assert "URL" in match.description or "url" in match.description


class TestRemoveVersusDelete:
    def test_remove_keeps_the_file(self, library, make_item, real_file):
        path = real_file("keepme.mp3")
        media_id = library.add(make_item(file_path=str(path), filename=path.name))
        library.remove(media_id)
        assert library.get(media_id) is None
        assert path.exists(), "Remove from Library must never touch the file"

    def test_delete_removes_the_file_and_the_entry(self, library, make_item, real_file):
        path = real_file("deleteme.mp3")
        media_id = library.add(make_item(file_path=str(path), filename=path.name))
        ok, _ = library.delete_file(media_id)
        assert ok
        assert not path.exists()
        assert library.get(media_id) is None

    def test_delete_also_removes_the_cached_thumbnail(self, library, make_item, real_file):
        media = real_file("a.mp3")
        thumb = real_file("a.jpg")
        media_id = library.add(
            make_item(file_path=str(media), filename=media.name, thumbnail_path=str(thumb))
        )
        library.delete_file(media_id)
        assert not thumb.exists()

    def test_delete_of_an_already_missing_file_still_clears_the_entry(self, library, make_item):
        media_id = library.add(make_item(file_path="/nowhere/gone.mp3"))
        ok, _ = library.delete_file(media_id)
        assert ok
        assert library.get(media_id) is None

    def test_delete_of_an_unknown_id_reports_failure(self, library):
        ok, message = library.delete_file(4242)
        assert ok is False
        assert message

    def test_remove_many(self, library, make_item):
        ids = [library.add(make_item()) for _ in range(3)]
        assert library.remove_many(ids) == 3
        assert library.count() == 0


class TestIntegrity:
    def test_verify_flags_a_missing_file(self, library, make_item):
        media_id = library.add(make_item(file_path="/nowhere/gone.mp3"))
        result = library.verify_files()
        assert result["missing"] == 1
        assert library.get(media_id).file_missing is True

    def test_verify_clears_the_flag_when_the_file_returns(
        self, library, make_item, real_file
    ):
        path = real_file("back.mp3")
        media_id = library.add(make_item(file_path=str(path), filename=path.name))
        library.update_fields(media_id, file_missing=1)
        result = library.verify_files()
        assert result["recovered"] == 1
        assert library.get(media_id).file_missing is False

    def test_verify_refreshes_the_recorded_size(self, library, make_item, real_file):
        path = real_file("sized.mp3", size=500)
        media_id = library.add(
            make_item(file_path=str(path), filename=path.name, file_size=1)
        )
        library.verify_files()
        assert library.get(media_id).file_size == 500

    def test_relocate_finds_a_moved_file(self, library, make_item, tmp_path):
        moved_dir = tmp_path / "moved"
        moved_dir.mkdir()
        moved = moved_dir / "clip.mp4"
        moved.write_bytes(b"x" * 10)

        media_id = library.add(
            make_item(file_path="/old/location/clip.mp4", filename="clip.mp4")
        )
        library.verify_files()
        assert library.relocate_missing([moved_dir]) == 1

        item = library.get(media_id)
        assert item.file_path == str(moved)
        assert item.file_missing is False

    def test_relocate_will_not_steal_a_path_another_entry_owns(
        self, library, make_item, tmp_path
    ):
        existing = tmp_path / "clip.mp4"
        existing.write_bytes(b"x")
        library.add(make_item(file_path=str(existing), filename="clip.mp4"))
        orphan = library.add(make_item(file_path="/old/clip.mp4", filename="clip.mp4"))
        library.verify_files()
        assert library.relocate_missing([tmp_path]) == 0
        assert library.get(orphan).file_missing is True

    def test_import_file_indexes_something_found_on_disk(self, library, real_file):
        path = real_file("found.mp3", size=42)
        media_id = library.import_file(path, category="Music", media_kind="audio")
        assert media_id is not None
        item = library.get(media_id)
        assert item.filename == "found.mp3"
        assert item.category == "Music"
        assert item.file_size == 42

    def test_import_file_skips_something_already_indexed(self, library, real_file, make_item):
        path = real_file("known.mp3")
        library.add(make_item(file_path=str(path), filename=path.name))
        assert library.import_file(path, category="Music", media_kind="audio") is None


class TestCategories:
    def test_builtin_categories_are_seeded(self, library):
        names = {c["name"] for c in library.all_categories()}
        assert {"Video", "Inspiration", "Music", "Sound Effects", "Other"} <= names

    def test_counts(self, library, populated):
        counts = library.category_counts()
        assert counts["Sound Effects"] == 1
        assert counts["Music"] == 1

    def test_kind_counts(self, library, populated):
        counts = library.kind_counts()
        assert counts["audio"] == 2
        assert counts["video"] == 1
        assert counts["all"] == 3

    def test_add_a_custom_category(self, library):
        assert library.add_category("Podcasts", "audio") is True
        assert "Podcasts" in {c["name"] for c in library.all_categories()}

    def test_deleting_a_custom_category_moves_its_media_to_other(self, library, make_item):
        library.add_category("Podcasts", "audio")
        media_id = library.add(make_item(category="Podcasts"))
        assert library.delete_category("Podcasts") is True
        assert library.get(media_id).category == "Other"

    def test_a_builtin_category_cannot_be_deleted(self, library):
        assert library.delete_category("Music") is False

    def test_set_category_updates_the_media_kind(self, library, make_item):
        media_id = library.add(make_item(category="Sound Effects", media_kind="audio"))
        library.set_category(media_id, "Inspiration")
        item = library.get(media_id)
        assert item.category == "Inspiration"
        assert item.media_kind == "video"


class TestSummaryAndHistory:
    def test_summary(self, library, make_item):
        library.add(make_item(file_size=100, duration=10))
        library.add(make_item(file_size=250, duration=5))
        summary = library.summary()
        assert summary["items"] == 2
        assert summary["bytes"] == 350
        assert summary["seconds"] == 15

    def test_download_history(self, library):
        library.record_download(
            task_id="t1",
            url="https://example.com/a",
            title="A",
            platform="YouTube",
            category="Music",
            format_label="MP3 - 320 kbps",
            status="Complete",
        )
        history = library.recent_downloads()
        assert len(history) == 1
        assert history[0]["status"] == "Complete"


class TestSearchIndex:
    def test_rebuild_reindexes_everything(self, library, populated):
        assert library.rebuild_index() == 3
        assert len(library.search(LibraryQuery(text="whoosh"))) == 1

    def test_index_follows_a_title_change(self, library, make_item):
        media_id = library.add(make_item(title="Original Name"))
        item = library.get(media_id)
        item.title = "Completely Different"
        library.update(item)
        assert library.search(LibraryQuery(text="Original")) == []
        assert len(library.search(LibraryQuery(text="Different"))) == 1

    def test_index_follows_a_tag_change(self, library, make_item):
        media_id = library.add(make_item(title="X"))
        library.add_tag(media_id, "Searchable")
        assert len(library.search(LibraryQuery(text="Searchable"))) == 1
        library.remove_tag(media_id, "Searchable")
        assert library.search(LibraryQuery(text="Searchable")) == []

    def test_removing_media_drops_it_from_the_index(self, library, make_item):
        media_id = library.add(make_item(title="Ephemeral"))
        library.remove(media_id)
        assert library.search(LibraryQuery(text="Ephemeral")) == []


def test_media_item_round_trips_through_a_row(library, make_item):
    media_id = library.add(make_item(title="Round", height=1080, width=1920, fps=29.97))
    item = library.get(media_id)
    assert item.resolution == "1920x1080"
    assert item.quality_label == "1080p"
    assert isinstance(item, MediaItem)
