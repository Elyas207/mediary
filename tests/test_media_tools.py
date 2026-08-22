"""FFmpeg detection and probing, plus formatting and log redaction.

FFmpeg is mocked throughout: the suite must pass on a machine that has never
installed it.
"""

from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from app.media import ffmpeg as ffmpeg_module
from app.utils.formatting import (
    format_bitrate,
    format_bytes,
    format_duration,
    format_eta,
    format_speed,
    parse_datetime,
    relative_date,
    truncate,
)
from app.utils.logging import redact


@pytest.fixture(autouse=True)
def clear_ffmpeg_cache():
    ffmpeg_module.clear_cache()
    yield
    ffmpeg_module.clear_cache()


def _completed(stdout: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


class TestFFmpegDetection:
    def test_finds_ffmpeg_on_the_path(self, tmp_path):
        binary = tmp_path / "ffmpeg"
        binary.write_text("#!/bin/sh")
        with mock.patch.object(ffmpeg_module.shutil, "which", return_value=str(binary)), \
             mock.patch.object(
                 ffmpeg_module, "_run", return_value=_completed("ffmpeg version 6.1.1 Copyright")
             ):
            info = ffmpeg_module.detect_ffmpeg()
        assert info.available
        assert info.version == "6.1.1"
        assert info.source == "path"

    def test_prefers_an_explicitly_configured_binary(self, tmp_path):
        configured = tmp_path / "custom-ffmpeg"
        configured.write_text("#!/bin/sh")
        other = tmp_path / "path-ffmpeg"
        other.write_text("#!/bin/sh")

        with mock.patch.object(ffmpeg_module.shutil, "which", return_value=str(other)), \
             mock.patch.object(
                 ffmpeg_module, "_run", return_value=_completed("ffmpeg version 7.0 Copyright")
             ):
            info = ffmpeg_module.detect_ffmpeg(str(configured))
        assert info.source == "configured"
        assert info.path == str(configured)

    def test_accepts_a_directory_as_the_configured_path(self, tmp_path):
        binary = tmp_path / ("ffmpeg.exe" if ffmpeg_module.is_windows() else "ffmpeg")
        binary.write_text("#!/bin/sh")
        with mock.patch.object(ffmpeg_module.shutil, "which", return_value=None), \
             mock.patch.object(
                 ffmpeg_module, "_run", return_value=_completed("ffmpeg version 7.0 Copyright")
             ):
            info = ffmpeg_module.detect_ffmpeg(str(tmp_path))
        assert info.available

    def test_reports_unavailable_rather_than_raising(self):
        with mock.patch.object(ffmpeg_module.shutil, "which", return_value=None), \
             mock.patch.object(ffmpeg_module, "_common_locations", return_value=[]), \
             mock.patch.object(ffmpeg_module, "bundled_binary", return_value=None):
            info = ffmpeg_module.detect_ffmpeg()
        assert info.available is False
        assert info.summary == "Not found"

    def test_a_binary_that_does_not_run_is_skipped(self, tmp_path):
        broken = tmp_path / "ffmpeg"
        broken.write_text("nope")
        with mock.patch.object(ffmpeg_module.shutil, "which", return_value=str(broken)), \
             mock.patch.object(ffmpeg_module, "_common_locations", return_value=[]), \
             mock.patch.object(ffmpeg_module, "bundled_binary", return_value=None), \
             mock.patch.object(ffmpeg_module, "_run", return_value=_completed("", 1)):
            info = ffmpeg_module.detect_ffmpeg()
        assert info.available is False

    def test_a_crashing_binary_does_not_propagate(self, tmp_path):
        broken = tmp_path / "ffmpeg"
        broken.write_text("nope")
        with mock.patch.object(ffmpeg_module.shutil, "which", return_value=str(broken)), \
             mock.patch.object(ffmpeg_module, "_common_locations", return_value=[]), \
             mock.patch.object(ffmpeg_module, "bundled_binary", return_value=None), \
             mock.patch.object(ffmpeg_module, "_run", side_effect=OSError("boom")):
            assert ffmpeg_module.detect_ffmpeg().available is False

    def test_a_timeout_does_not_propagate(self, tmp_path):
        binary = tmp_path / "ffmpeg"
        binary.write_text("x")
        with mock.patch.object(ffmpeg_module.shutil, "which", return_value=str(binary)), \
             mock.patch.object(ffmpeg_module, "_common_locations", return_value=[]), \
             mock.patch.object(ffmpeg_module, "bundled_binary", return_value=None), \
             mock.patch.object(
                 ffmpeg_module, "_run",
                 side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=15),
             ):
            assert ffmpeg_module.detect_ffmpeg().available is False

    def test_the_lookup_is_cached(self, tmp_path):
        binary = tmp_path / "ffmpeg"
        binary.write_text("x")
        with mock.patch.object(ffmpeg_module.shutil, "which", return_value=str(binary)), \
             mock.patch.object(
                 ffmpeg_module, "_run", return_value=_completed("ffmpeg version 7.0 Copyright")
             ) as run:
            ffmpeg_module.get_ffmpeg()
            ffmpeg_module.get_ffmpeg()
            first_calls = run.call_count
            ffmpeg_module.get_ffmpeg(refresh=True)
            assert run.call_count > first_calls


class TestProbe:
    _PAYLOAD = """
    {
      "format": {"duration": "12.42", "format_name": "mp3", "size": "199447", "bit_rate": "128000"},
      "streams": [
        {"codec_type": "audio", "codec_name": "mp3", "bit_rate": "128000",
         "sample_rate": "44100", "channels": 2}
      ]
    }
    """

    _VIDEO_PAYLOAD = """
    {
      "format": {"duration": "596.5", "format_name": "mov,mp4,m4a", "size": "61878609"},
      "streams": [
        {"codec_type": "video", "codec_name": "h264", "width": 640, "height": 360,
         "avg_frame_rate": "30000/1001"},
        {"codec_type": "audio", "codec_name": "aac", "bit_rate": "128000", "sample_rate": "44100"}
      ]
    }
    """

    def test_parses_audio_metadata(self):
        with mock.patch.object(ffmpeg_module, "_run", return_value=_completed(self._PAYLOAD)):
            info = ffmpeg_module.probe_media("/x.mp3", "ffprobe")
        assert info["duration"] == pytest.approx(12.42)
        assert info["audio_codec"] == "mp3"
        assert info["audio_bitrate"] == 128
        assert info["sample_rate"] == 44100

    def test_parses_video_metadata(self):
        with mock.patch.object(
            ffmpeg_module, "_run", return_value=_completed(self._VIDEO_PAYLOAD)
        ):
            info = ffmpeg_module.probe_media("/x.mp4", "ffprobe")
        assert info["width"] == 640 and info["height"] == 360
        assert info["video_codec"] == "h264"
        assert info["fps"] == pytest.approx(29.97, abs=0.01)

    def test_returns_empty_without_ffprobe(self):
        with mock.patch.object(ffmpeg_module, "get_ffmpeg",
                               return_value=ffmpeg_module.FFmpegInfo()):
            assert ffmpeg_module.probe_media("/x.mp3") == {}

    def test_returns_empty_on_a_probe_failure(self):
        with mock.patch.object(ffmpeg_module, "_run", return_value=_completed("", 1)):
            assert ffmpeg_module.probe_media("/x.mp3", "ffprobe") == {}

    def test_returns_empty_on_malformed_output(self):
        with mock.patch.object(ffmpeg_module, "_run", return_value=_completed("not json")):
            assert ffmpeg_module.probe_media("/x.mp3", "ffprobe") == {}

    @pytest.mark.parametrize(
        "value,expected", [("30000/1001", 29.97), ("25/1", 25.0), ("0/0", 0.0), (None, 0.0)]
    )
    def test_frame_rate_fractions(self, value, expected):
        assert ffmpeg_module._parse_fraction(value) == pytest.approx(expected, abs=0.01)


class TestFormatting:
    @pytest.mark.parametrize(
        "value,expected",
        [(0, "0 B"), (512, "512 B"), (1024, "1.0 KB"), (15_800_000, "15.1 MB"),
         (None, "—"), (-1, "—")],
    )
    def test_bytes(self, value, expected):
        assert format_bytes(value) == expected

    @pytest.mark.parametrize(
        "value,expected", [(0, "0:00"), (12, "0:12"), (95, "1:35"), (3725, "1:02:05"), (None, "—")]
    )
    def test_duration(self, value, expected):
        assert format_duration(value) == expected

    @pytest.mark.parametrize(
        "value,expected", [(0, "—"), (30, "30s"), (185, "3m 05s"), (7325, "2h 02m"), (None, "—")]
    )
    def test_eta(self, value, expected):
        assert format_eta(value) == expected

    def test_speed(self):
        assert format_speed(8_400_000) == "8.0 MB/s"
        assert format_speed(0) == "—"

    def test_bitrate(self):
        assert format_bitrate(320) == "320 kbps"
        assert format_bitrate(0) == "—"

    def test_parses_a_yt_dlp_upload_date(self):
        moment = parse_datetime("20250104")
        assert (moment.year, moment.month, moment.day) == (2025, 1, 4)

    def test_parses_an_iso_timestamp(self):
        assert parse_datetime("2026-08-22T13:40:00").hour == 13

    def test_unparseable_dates_return_none(self):
        assert parse_datetime("not a date") is None
        assert parse_datetime("") is None

    def test_relative_dates(self):
        from datetime import datetime, timedelta

        now = datetime.utcnow()
        assert relative_date(now.isoformat()) == "Today"
        assert relative_date((now - timedelta(days=1)).isoformat()) == "Yesterday"
        assert relative_date((now - timedelta(days=3)).isoformat()) == "3 days ago"

    def test_truncate(self):
        assert truncate("short", 10) == "short"
        assert truncate("a" * 20, 10).endswith("…")
        assert len(truncate("a" * 20, 10)) == 10


class TestRedaction:
    @pytest.mark.parametrize(
        "text,secret",
        [
            ("cookie: sessionid=abc123def", "abc123def"),
            ("Set-Cookie: x=y", "x=y"),
            ("Authorization: Bearer eyJhbGciOi", "eyJhbGciOi"),
            ("password=hunter2", "hunter2"),
            ("api_key=sk-live-1234", "sk-live-1234"),
            ("access_token=tok_abc", "tok_abc"),
            ("token=PLAIN_TOKEN", "PLAIN_TOKEN"),
            ("client_secret=shh", "shh"),
            ("https://cdn.example.com/v?token=SIGNED123&x=1", "SIGNED123"),
            ("https://user:pass@example.com/x", "user:pass"),
        ],
    )
    def test_secrets_never_reach_a_log(self, text, secret):
        assert secret not in redact(text)

    def test_ordinary_text_is_untouched(self):
        message = "Downloading https://example.com/video.mp4 at 8 MB/s"
        assert redact(message) == message

    def test_redaction_is_applied_by_the_log_filter(self, caplog):
        import logging

        from app.utils.logging import RedactingFilter

        logger = logging.getLogger("test.redaction")
        logger.addFilter(RedactingFilter())
        with caplog.at_level(logging.INFO, logger="test.redaction"):
            logger.info("failing with password=hunter2")
        assert "hunter2" not in caplog.text
