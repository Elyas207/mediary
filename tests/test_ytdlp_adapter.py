"""The yt-dlp boundary, exercised entirely against fixtures.

No test here touches the network: everything is driven from the JSON payloads
in ``tests/fixtures``.
"""

from __future__ import annotations

import pytest

from app.downloader.ytdlp_adapter import (
    RuntimeConfig,
    analysis_options,
    base_options,
    build_format_selector,
    build_postprocessors,
    download_options,
    info_from_dict,
    parse_formats,
)
from app.models.download import DownloadOptions, quality_to_height


class TestInfoNormalisation:
    def test_sound_effect_fixture(self, fixture_info):
        info = info_from_dict(fixture_info("sound_effect"))
        assert info.title == "Epic Cinematic Whoosh"
        assert info.creator == "Example Creator"
        assert info.platform == "YouTube"
        assert info.platform_id == "whoosh123"
        assert info.duration == 12
        assert info.upload_date == "20250104"

    def test_picks_the_largest_thumbnail(self, fixture_info):
        info = info_from_dict(fixture_info("sound_effect"))
        assert info.thumbnail_url.endswith("maxres.jpg")

    def test_uses_an_explicit_thumbnail_when_present(self, fixture_info):
        info = info_from_dict(fixture_info("video_reel"))
        assert info.thumbnail_url == "https://img.example.com/reel456.jpg"

    def test_audio_only_source_reports_no_video(self, fixture_info):
        info = info_from_dict(fixture_info("sound_effect"))
        assert info.has_video is False
        assert info.has_audio is True
        assert info.available_video_qualities == ["best"]

    def test_video_source_exposes_its_quality_ladder(self, fixture_info):
        info = info_from_dict(fixture_info("video_reel"))
        assert info.has_video is True
        assert info.best_height == 1080
        assert info.available_video_qualities == ["best", "1080p", "720p", "480p", "360p"]
        assert "1440p" not in info.available_video_qualities

    def test_a_playlist_falls_back_to_its_first_entry(self, fixture_info):
        info = info_from_dict(fixture_info("playlist"))
        assert info.title == "First Track"
        assert info.platform == "SoundCloud"

    def test_a_single_stream_source_still_yields_one_format(self, fixture_info):
        info = info_from_dict(fixture_info("no_formats"))
        assert len(info.formats) == 1
        assert info.formats[0].height == 720
        assert info.has_video is True

    def test_a_generic_extractor_is_named_from_its_host(self, fixture_info):
        info = info_from_dict(fixture_info("no_formats"))
        assert info.platform == "Example"

    def test_empty_payload_does_not_raise(self):
        info = info_from_dict({}, "https://example.com/x")
        assert info.title == "Untitled"
        assert info.formats == []


class TestCodecInference:
    """Several extractors never report codecs; a video must not become audio."""

    def test_unknown_codecs_are_inferred_from_the_container(self, fixture_info):
        info = info_from_dict(fixture_info("unknown_codecs"))
        assert info.has_video is True
        assert all(f.has_video for f in info.formats)
        assert info.available_video_qualities == ["best", "720p", "480p", "360p"]

    def test_explicit_none_still_means_absent(self, fixture_info):
        info = info_from_dict(fixture_info("sound_effect"))
        assert all(not f.has_video for f in info.formats)

    def test_an_unknown_codec_with_dimensions_counts_as_video(self):
        formats = parse_formats([{"format_id": "1", "ext": "bin", "height": 720}])
        assert formats[0].has_video is True

    def test_an_audio_container_with_no_codec_is_audio_only(self):
        formats = parse_formats([{"format_id": "1", "ext": "mp3"}])
        assert formats[0].has_audio is True
        assert formats[0].has_video is False

    def test_formats_are_sorted_best_first(self, fixture_info):
        info = info_from_dict(fixture_info("video_reel"))
        heights = [f.height for f in info.formats]
        assert heights == sorted(heights, reverse=True)

    def test_mhtml_storyboards_are_skipped(self):
        assert parse_formats([{"format_id": "sb0", "ext": "mhtml"}]) == []

    def test_formats_without_an_id_are_skipped(self):
        assert parse_formats([{"ext": "mp4", "height": 720}]) == []


class TestFormatSelector:
    def test_audio_selector(self):
        options = DownloadOptions(media_kind="audio", audio_format="mp3")
        assert build_format_selector(options, has_ffmpeg=True) == "bestaudio/best"

    def test_video_selector_merges_when_ffmpeg_is_available(self):
        options = DownloadOptions(media_kind="video", video_format="mp4", video_quality="1080p")
        selector = build_format_selector(options, has_ffmpeg=True)
        assert "bestvideo" in selector and "bestaudio" in selector
        assert "height<=?1080" in selector

    def test_video_selector_is_progressive_without_ffmpeg(self):
        options = DownloadOptions(media_kind="video", video_format="mp4", video_quality="720p")
        selector = build_format_selector(options, has_ffmpeg=False)
        # Without FFmpeg we cannot mux, so we must not ask for separate streams.
        assert "bestvideo" not in selector
        assert "acodec!=none" in selector

    def test_best_quality_imposes_no_height_cap(self):
        options = DownloadOptions(media_kind="video", video_quality="best")
        assert "height<=?" not in build_format_selector(options, has_ffmpeg=True)

    def test_mp4_prefers_mp4_and_m4a(self):
        options = DownloadOptions(media_kind="video", video_format="mp4")
        selector = build_format_selector(options, has_ffmpeg=True)
        assert "[ext=mp4]" in selector and "[ext=m4a]" in selector

    def test_mkv_accepts_anything(self):
        options = DownloadOptions(media_kind="video", video_format="mkv")
        assert "[ext=" not in build_format_selector(options, has_ffmpeg=True)

    def test_an_explicit_format_id_wins(self):
        options = DownloadOptions(media_kind="video", format_id="137+140")
        assert build_format_selector(options, has_ffmpeg=True) == "137+140"

    def test_every_selector_ends_with_a_fallback(self):
        for quality in ("best", "2160p", "720p", "360p"):
            options = DownloadOptions(media_kind="video", video_quality=quality)
            assert build_format_selector(options, has_ffmpeg=True).endswith("best")


class TestPostprocessors:
    def test_lossy_audio_gets_a_bitrate(self):
        options = DownloadOptions(media_kind="audio", audio_format="mp3", audio_bitrate="320")
        extract = build_postprocessors(options, has_ffmpeg=True)[0]
        assert extract["key"] == "FFmpegExtractAudio"
        assert extract["preferredcodec"] == "mp3"
        assert extract["preferredquality"] == "320"

    @pytest.mark.parametrize("fmt", ["wav", "flac"])
    def test_lossless_audio_gets_no_bitrate(self, fmt):
        # Claiming a bitrate for a lossless container would be meaningless.
        options = DownloadOptions(media_kind="audio", audio_format=fmt, audio_bitrate="320")
        extract = build_postprocessors(options, has_ffmpeg=True)[0]
        assert "preferredquality" not in extract

    def test_video_is_remuxed_to_the_chosen_container(self):
        options = DownloadOptions(media_kind="video", video_format="mkv")
        remux = build_postprocessors(options, has_ffmpeg=True)[0]
        assert remux["key"] == "FFmpegVideoRemuxer"
        assert remux["preferedformat"] == "mkv"

    def test_metadata_can_be_disabled(self):
        options = DownloadOptions(media_kind="audio", embed_metadata=False)
        keys = {p["key"] for p in build_postprocessors(options, has_ffmpeg=True)}
        assert "FFmpegMetadata" not in keys

    def test_thumbnails_are_only_embedded_in_capable_containers(self):
        capable = DownloadOptions(media_kind="audio", audio_format="mp3", embed_thumbnail=True)
        assert "EmbedThumbnail" in {p["key"] for p in build_postprocessors(capable, has_ffmpeg=True)}

        incapable = DownloadOptions(media_kind="audio", audio_format="wav", embed_thumbnail=True)
        assert "EmbedThumbnail" not in {
            p["key"] for p in build_postprocessors(incapable, has_ffmpeg=True)
        }

    def test_nothing_is_scheduled_without_ffmpeg(self):
        options = DownloadOptions(media_kind="audio", audio_format="mp3")
        assert build_postprocessors(options, has_ffmpeg=False) == []


class TestOptionDicts:
    def test_never_reads_credentials(self):
        """Mediary must not touch cookies, browser profiles or netrc."""
        options = base_options()
        assert options["cookiefile"] is None
        assert options["cookiesfrombrowser"] is None
        assert options["usenetrc"] is False

    def test_playlists_are_not_expanded(self):
        assert base_options()["noplaylist"] is True

    def test_rate_limit_is_applied_when_set(self):
        options = base_options(RuntimeConfig(max_speed_kbps=512))
        assert options["ratelimit"] == 512 * 1024

    def test_no_rate_limit_key_when_unlimited(self):
        assert "ratelimit" not in base_options(RuntimeConfig(max_speed_kbps=0))

    def test_retries_and_timeout_come_from_config(self):
        options = base_options(RuntimeConfig(retries=5, socket_timeout=45))
        assert options["retries"] == 5
        assert options["socket_timeout"] == 45

    def test_timeout_has_a_sane_floor(self):
        assert base_options(RuntimeConfig(socket_timeout=1))["socket_timeout"] >= 5

    def test_analysis_never_downloads(self):
        options = analysis_options()
        assert options["skip_download"] is True
        assert options["simulate"] is True

    def test_download_options_target_the_staging_directory(self, tmp_path):
        options = download_options(
            DownloadOptions(media_kind="audio"), tmp_path, has_ffmpeg=True
        )
        assert str(tmp_path) in options["outtmpl"]["default"]
        assert options["paths"]["home"] == str(tmp_path)

    def test_download_options_never_overwrite(self, tmp_path):
        options = download_options(DownloadOptions(), tmp_path, has_ffmpeg=True)
        assert options["overwrites"] is False

    def test_merge_format_is_set_only_for_video_with_ffmpeg(self, tmp_path):
        video = download_options(
            DownloadOptions(media_kind="video", video_format="mkv"), tmp_path, has_ffmpeg=True
        )
        assert video["merge_output_format"] == "mkv"

        audio = download_options(
            DownloadOptions(media_kind="audio"), tmp_path, has_ffmpeg=True
        )
        assert "merge_output_format" not in audio

        no_ffmpeg = download_options(
            DownloadOptions(media_kind="video"), tmp_path, has_ffmpeg=False
        )
        assert "merge_output_format" not in no_ffmpeg

    def test_hooks_are_registered_when_supplied(self, tmp_path):
        options = download_options(
            DownloadOptions(),
            tmp_path,
            has_ffmpeg=True,
            progress_hook=lambda d: None,
            postprocessor_hook=lambda d: None,
        )
        assert len(options["progress_hooks"]) == 1
        assert len(options["postprocessor_hooks"]) == 1


@pytest.mark.parametrize(
    "quality,height",
    [("best", 0), ("2160p", 2160), ("1080p", 1080), ("360p", 360), ("", 0), ("junk", 0)],
)
def test_quality_to_height(quality, height):
    assert quality_to_height(quality) == height
