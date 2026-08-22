"""FFmpeg discovery and probing.

Mediary never *requires* FFmpeg to start: if it is missing the app degrades to
progressive (single-stream) downloads and tells the user what they are losing.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.utils.logging import get_logger
from app.utils.paths import bundled_binary, is_windows

log = get_logger("ffmpeg")

_VERSION_RE = re.compile(r"ffmpeg version (\S+)")

#: Hide the console window when spawning helpers from a windowed build.
_CREATE_NO_WINDOW = 0x08000000 if is_windows() else 0


def _run(args: list, timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=_CREATE_NO_WINDOW,
        encoding="utf-8",
        errors="replace",
    )


@dataclass
class FFmpegInfo:
    """Where FFmpeg is and whether it works."""

    available: bool = False
    path: str = ""
    ffprobe_path: str = ""
    version: str = ""
    source: str = ""     # "configured" | "bundled" | "path" | "common"

    @property
    def directory(self) -> str:
        return str(Path(self.path).parent) if self.path else ""

    @property
    def summary(self) -> str:
        if not self.available:
            return "Not found"
        return self.version or "Installed"


#: Locations checked when FFmpeg is not on PATH. Covers the usual installers
#: (Homebrew, Chocolatey/Scoop, winget, apt) on each platform.
def _common_locations() -> list:
    if is_windows():
        return [
            Path("C:/ffmpeg/bin/ffmpeg.exe"),
            Path("C:/Program Files/ffmpeg/bin/ffmpeg.exe"),
            Path.home() / "scoop" / "shims" / "ffmpeg.exe",
            Path("C:/ProgramData/chocolatey/bin/ffmpeg.exe"),
        ]
    return [
        Path("/opt/homebrew/bin/ffmpeg"),
        Path("/usr/local/bin/ffmpeg"),
        Path("/usr/bin/ffmpeg"),
        Path("/snap/bin/ffmpeg"),
        Path("/var/lib/flatpak/exports/bin/ffmpeg"),
    ]


def _probe_binary(path: Path | str) -> str | None:
    """Return the version string if ``path`` is a working ffmpeg."""
    try:
        result = _run([str(path), "-version"], timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("ffmpeg probe failed for %s: %s", path, exc)
        return None
    if result.returncode != 0:
        return None
    match = _VERSION_RE.search(result.stdout or "")
    return match.group(1) if match else "unknown"


def _sibling_ffprobe(ffmpeg_path: Path) -> str:
    name = "ffprobe.exe" if is_windows() else "ffprobe"
    candidate = ffmpeg_path.parent / name
    if candidate.is_file():
        return str(candidate)
    found = shutil.which("ffprobe")
    return found or ""


def detect_ffmpeg(configured_path: str = "") -> FFmpegInfo:
    """Locate FFmpeg, preferring an explicit user setting.

    Search order: configured path -> binary bundled with the app -> PATH ->
    well-known install locations.
    """
    candidates: list = []
    if configured_path:
        path = Path(configured_path).expanduser()
        # Accept either the executable itself or the directory containing it.
        if path.is_dir():
            path = path / ("ffmpeg.exe" if is_windows() else "ffmpeg")
        candidates.append((path, "configured"))

    bundled = bundled_binary("ffmpeg")
    if bundled is not None:
        candidates.append((bundled, "bundled"))

    on_path = shutil.which("ffmpeg")
    if on_path:
        candidates.append((Path(on_path), "path"))

    candidates.extend((location, "common") for location in _common_locations())

    for path, source in candidates:
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        version = _probe_binary(path)
        if version is None:
            continue
        info = FFmpegInfo(
            available=True,
            path=str(path),
            ffprobe_path=_sibling_ffprobe(path),
            version=version,
            source=source,
        )
        log.info("FFmpeg %s found via %s at %s", version, source, path)
        return info

    log.warning("FFmpeg not found; merged and converted downloads are unavailable")
    return FFmpegInfo()


_cached: FFmpegInfo | None = None


def get_ffmpeg(configured_path: str = "", *, refresh: bool = False) -> FFmpegInfo:
    """Cached FFmpeg lookup - detection spawns a process, so do it once."""
    global _cached
    if _cached is None or refresh:
        _cached = detect_ffmpeg(configured_path)
    return _cached


def clear_cache() -> None:
    global _cached
    _cached = None


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------


def probe_media(path: Path | str, ffprobe_path: str = "") -> dict:
    """Read technical metadata from a local file using ffprobe.

    Returns an empty dict when ffprobe is unavailable or the file is unreadable;
    callers treat every field as optional.
    """
    probe = ffprobe_path or get_ffmpeg().ffprobe_path
    if not probe:
        return {}

    args = [
        probe, "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    try:
        result = _run(args, timeout=30)
        if result.returncode != 0:
            return {}
        payload = json.loads(result.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError) as exc:
        log.debug("ffprobe failed for %s: %s", path, exc)
        return {}

    streams = payload.get("streams") or []
    fmt = payload.get("format") or {}
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    info: dict = {
        "duration": _as_float(fmt.get("duration")),
        "container": (fmt.get("format_name") or "").split(",")[0],
        "size": _as_int(fmt.get("size")),
        "overall_bitrate": _as_int(fmt.get("bit_rate")) // 1000 or 0,
    }
    if video is not None:
        info.update(
            {
                "width": _as_int(video.get("width")),
                "height": _as_int(video.get("height")),
                "fps": _parse_fraction(video.get("avg_frame_rate") or video.get("r_frame_rate")),
                "video_codec": video.get("codec_name") or "",
            }
        )
    if audio is not None:
        info.update(
            {
                "audio_codec": audio.get("codec_name") or "",
                "audio_bitrate": _as_int(audio.get("bit_rate")) // 1000 or 0,
                "sample_rate": _as_int(audio.get("sample_rate")),
                "channels": _as_int(audio.get("channels")),
            }
        )
    if not info.get("audio_bitrate") and audio is not None and info.get("overall_bitrate"):
        # Some containers only report an overall rate; for audio-only files
        # that *is* the audio bitrate.
        if video is None:
            info["audio_bitrate"] = info["overall_bitrate"]
    if not info.get("duration"):
        stream_duration = _as_float((video or audio or {}).get("duration"))
        if stream_duration:
            info["duration"] = stream_duration
    return info


def _as_int(value) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _as_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_fraction(value) -> float:
    """``"30000/1001"`` -> ``29.97``."""
    if not value:
        return 0.0
    text = str(value)
    if "/" in text:
        numerator, _, denominator = text.partition("/")
        try:
            den = float(denominator)
            if den == 0:
                return 0.0
            return round(float(numerator) / den, 3)
        except ValueError:
            return 0.0
    return _as_float(text)
