"""URL validation, platform naming and error translation - all offline."""

from __future__ import annotations

import pytest

from app.downloader.ytdlp_adapter import (
    is_probable_url,
    normalize_url,
    parse_urls,
    platform_name,
    translate_error,
)


class TestIsProbableUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://www.youtube.com/watch?v=abc123",
            "http://example.com/media.mp4",
            "https://youtu.be/abc",
            "youtube.com/watch?v=abc",
            "https://archive.org/details/thing",
            "https://sub.domain.co.uk/path?a=b#c",
        ],
    )
    def test_accepts_real_urls(self, url):
        assert is_probable_url(url)

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   ",
            "hello",
            "not a url",
            "just some prose about a video",
            "https://",
            "https:// spaced.com",
            "ftp://files.example.com/a",
            "file:///c:/thing.mp4",
        ],
    )
    def test_rejects_non_urls(self, text):
        assert not is_probable_url(text)


class TestNormalizeUrl:
    def test_adds_a_scheme_to_a_bare_domain(self):
        assert normalize_url("youtube.com/watch?v=x") == "https://youtube.com/watch?v=x"

    def test_leaves_an_explicit_scheme_alone(self):
        assert normalize_url("http://a.com/b") == "http://a.com/b"

    def test_strips_surrounding_decoration(self):
        assert normalize_url("<https://a.com/b>") == "https://a.com/b"
        assert normalize_url("'https://a.com/b',") == "https://a.com/b"

    def test_does_not_invent_a_scheme_for_prose(self):
        assert normalize_url("hello") == "hello"


class TestParseUrls:
    def test_single_url(self):
        assert parse_urls("https://a.com/1") == ["https://a.com/1"]

    def test_newline_separated(self):
        text = "https://a.com/1\nhttps://b.com/2\nhttps://c.com/3"
        assert len(parse_urls(text)) == 3

    def test_comma_and_whitespace_separated(self):
        assert len(parse_urls("https://a.com/1, https://b.com/2  https://c.com/3")) == 3

    def test_deduplicates_while_preserving_order(self):
        text = "https://b.com/2\nhttps://a.com/1\nhttps://b.com/2"
        assert parse_urls(text) == ["https://b.com/2", "https://a.com/1"]

    def test_ignores_prose_mixed_with_urls(self):
        text = "check this out https://a.com/1 it is great\nand also not a url"
        assert parse_urls(text) == ["https://a.com/1"]

    def test_empty_input(self):
        assert parse_urls("") == []
        assert parse_urls("   \n  ") == []


class TestPlatformName:
    @pytest.mark.parametrize(
        "extractor,url,expected",
        [
            ("Youtube", "https://youtu.be/x", "YouTube"),
            ("youtube:tab", "", "YouTube"),
            ("Instagram", "", "Instagram"),
            ("Facebook", "", "Facebook"),
            ("SoundCloud", "", "SoundCloud"),
            ("archiveorg", "", "Internet Archive"),
            ("", "https://www.instagram.com/reel/x", "Instagram"),
            ("generic", "https://cool-site.example.com/v", "Cool-Site"),
        ],
    )
    def test_maps_to_a_display_name(self, extractor, url, expected):
        assert platform_name(extractor, url) == expected

    def test_falls_back_to_web_with_no_information(self):
        assert platform_name("", "") == "Web"


class TestTranslateError:
    @pytest.mark.parametrize(
        "raw,category",
        [
            ("ERROR: [youtube] x: Private video. Sign in if you have access", "private"),
            ("ERROR: Video unavailable", "unavailable"),
            ("ERROR: This video is DRM protected", "drm"),
            ("ERROR: Sign in to confirm you are not a bot", "auth"),
            ("ERROR: The uploader has not made this video available in your country", "region"),
            ("ERROR: Requested format is not available", "format"),
            ("ERROR: Unable to download webpage: getaddrinfo failed", "network"),
            ("ERROR: HTTP Error 403: Forbidden", "http"),
            ("ERROR: HTTP Error 503: Service Unavailable", "server"),
            ("OSError: [Errno 28] No space left on device", "disk"),
            ("PermissionError: [Errno 13] Permission denied", "permission"),
            ("ERROR: Unsupported URL: https://example.com/page", "unsupported"),
            ("ERROR: HTTP Error 429: Too Many Requests", "ratelimit"),
            ("ERROR: This video is age-restricted", "age"),
        ],
    )
    def test_classifies_known_failures(self, raw, category):
        assert translate_error(raw)[0] == category

    def test_message_is_human_readable(self):
        _, message, _ = translate_error("ERROR: Private video")
        assert "private" in message.lower()
        assert "ERROR:" not in message
        assert message.endswith(".")

    def test_keeps_the_raw_detail(self):
        raw = "ERROR: [youtube] abc: Video unavailable"
        _, _, detail = translate_error(raw)
        assert "Video unavailable" in detail

    def test_redacts_credentials_from_the_detail(self):
        _, _, detail = translate_error("ERROR: failed with token=SUPERSECRET123")
        assert "SUPERSECRET123" not in detail

    def test_unknown_error_still_returns_something_usable(self):
        category, message, detail = translate_error("something totally unexpected")
        assert category == "error"
        assert message
        assert "something totally unexpected" in detail

    def test_empty_error(self):
        category, message, _ = translate_error("")
        assert category == "error"
        assert message
