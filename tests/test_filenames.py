"""Filename sanitisation, de-duplication and templating."""

from __future__ import annotations

import pytest

from app.utils.filenames import (
    MAX_STEM_BYTES,
    normalize_extension,
    render_template,
    sanitize_component,
    sanitize_filename,
    unique_path,
)


class TestSanitizeComponent:
    def test_leaves_a_clean_title_alone(self):
        assert sanitize_component("Epic Cinematic Whoosh") == "Epic Cinematic Whoosh"

    @pytest.mark.parametrize("char", list('<>:"/\\|?*'))
    def test_removes_every_illegal_character(self, char):
        result = sanitize_component(f"a{char}b")
        assert char not in result
        assert result

    def test_collapses_whitespace(self):
        assert sanitize_component("  too   many\tspaces \n") == "too many spaces"

    def test_strips_control_characters(self):
        assert sanitize_component("clean\x00\x1fname") == "cleanname"

    def test_strips_trailing_dots_and_spaces(self):
        # Windows silently drops these, so the name on disk would not match.
        assert sanitize_component("name...  ") == "name"
        assert sanitize_component("  .name") == "name"

    @pytest.mark.parametrize("name", ["CON", "con", "PRN", "NUL", "COM1", "LPT9", "aux"])
    def test_escapes_windows_reserved_device_names(self, name):
        result = sanitize_component(name)
        assert result.upper() != name.upper()
        assert result.startswith("_")

    def test_reserved_name_with_extension_is_still_escaped(self):
        assert sanitize_component("CON.mp3").startswith("_")

    def test_a_name_merely_containing_a_reserved_word_is_untouched(self):
        assert sanitize_component("CONCERT") == "CONCERT"

    def test_preserves_unicode(self):
        assert sanitize_component("Trällé — Ünïcödé") == "Trällé — Ünïcödé"

    def test_normalises_unicode_composition(self):
        # Composed and decomposed forms must produce the same filename so a
        # library stays consistent between macOS and everything else.
        assert sanitize_component("é") == sanitize_component("é")

    def test_truncates_an_over_long_title(self):
        result = sanitize_component("x" * 500)
        assert len(result.encode("utf-8")) <= MAX_STEM_BYTES

    def test_truncation_prefers_a_word_boundary(self):
        text = " ".join(["word"] * 100)
        result = sanitize_component(text)
        assert not result.endswith(" ")
        assert result.endswith("word")

    def test_truncation_never_splits_a_multibyte_character(self):
        result = sanitize_component("é" * 300)
        result.encode("utf-8").decode("utf-8")  # would raise if split

    @pytest.mark.parametrize("value", ["", "   ", "...", "///", None])
    def test_empty_input_falls_back(self, value):
        assert sanitize_component(value or "") == "Untitled"

    def test_custom_fallback(self):
        assert sanitize_component("", fallback="Media") == "Media"


class TestNormalizeExtension:
    @pytest.mark.parametrize(
        "value,expected",
        [("mp3", ".mp3"), (".MP3", ".mp3"), ("  .mp4 ", ".mp4"), ("", ""), (".", "")],
    )
    def test_normalises(self, value, expected):
        assert normalize_extension(value) == expected


class TestSanitizeFilename:
    def test_appends_the_extension(self):
        assert sanitize_filename("Whoosh", "mp3") == "Whoosh.mp3"

    def test_handles_a_dotted_extension(self):
        assert sanitize_filename("Whoosh", ".MP3") == "Whoosh.mp3"

    def test_no_extension(self):
        assert sanitize_filename("Whoosh") == "Whoosh"

    def test_total_length_stays_within_budget(self):
        result = sanitize_filename("x" * 600, "mp3")
        assert len(result.encode("utf-8")) < 255
        assert result.endswith(".mp3")


class TestUniquePath:
    def test_returns_the_path_when_it_is_free(self, tmp_path):
        target = tmp_path / "clip.mp4"
        assert unique_path(target) == target

    def test_adds_a_numeric_suffix(self, tmp_path):
        target = tmp_path / "clip.mp4"
        target.write_text("x")
        assert unique_path(target).name == "clip (1).mp4"

    def test_increments_past_existing_suffixes(self, tmp_path):
        (tmp_path / "clip.mp4").write_text("x")
        (tmp_path / "clip (1).mp4").write_text("x")
        (tmp_path / "clip (2).mp4").write_text("x")
        assert unique_path(tmp_path / "clip.mp4").name == "clip (3).mp4"

    def test_continues_an_existing_sequence_instead_of_nesting(self, tmp_path):
        (tmp_path / "clip (1).mp4").write_text("x")
        # Must not become "clip (1) (1).mp4".
        assert unique_path(tmp_path / "clip (1).mp4").name == "clip (2).mp4"

    def test_never_returns_an_existing_path(self, tmp_path):
        target = tmp_path / "a.mp3"
        for _ in range(5):
            resolved = unique_path(target)
            assert not resolved.exists()
            resolved.write_text("x")

    def test_preserves_the_directory(self, tmp_path):
        nested = tmp_path / "Audio" / "Music"
        nested.mkdir(parents=True)
        target = nested / "song.mp3"
        target.write_text("x")
        assert unique_path(target).parent == nested


class TestRenderTemplate:
    def test_default_template(self):
        assert render_template("{title}", {"title": "Whoosh"}) == "Whoosh"

    def test_multiple_tokens(self):
        result = render_template(
            "{creator} - {title} [{quality}]",
            {"creator": "Studio", "title": "Reel", "quality": "1080p"},
        )
        assert result == "Studio - Reel [1080p]"

    def test_empty_token_collapses_its_separator(self):
        result = render_template(
            "{creator} - {title}", {"creator": "", "title": "Whoosh"}
        )
        assert result == "Whoosh"

    def test_empty_token_removes_its_brackets(self):
        result = render_template("{title} [{quality}]", {"title": "Reel", "quality": ""})
        assert result == "Reel"

    def test_unknown_token_is_dropped(self):
        assert render_template("{title}{nope}", {"title": "A"}) == "A"

    def test_literal_separators_do_not_create_directories(self):
        result = render_template("{creator}/{title}", {"creator": "A", "title": "B"})
        assert "/" not in result and "\\" not in result

    def test_values_are_sanitised(self):
        result = render_template("{title}", {"title": "bad/name"})
        assert "/" not in result

    def test_everything_empty_falls_back(self):
        assert render_template("{creator} - {title}", {"creator": "", "title": ""}) == "Untitled"
