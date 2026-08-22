"""Download-queue value objects: the request, its live progress and its state.

These types are shared between the UI thread and the worker threads, so they
carry no Qt dependency and no database handle.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.models.category import KIND_AUDIO, KIND_VIDEO


class DownloadStatus(str, Enum):
    """Lifecycle of a queue item. The string values are what the UI renders."""

    QUEUED = "Queued"
    ANALYZING = "Analyzing"
    DOWNLOADING = "Downloading"
    PROCESSING = "Processing"
    ORGANIZING = "Organizing"
    COMPLETE = "Complete"
    FAILED = "Failed"
    CANCELLED = "Cancelled"
    PAUSED = "Paused"

    @property
    def is_terminal(self) -> bool:
        return self in (
            DownloadStatus.COMPLETE,
            DownloadStatus.FAILED,
            DownloadStatus.CANCELLED,
        )

    @property
    def is_active(self) -> bool:
        return self in (
            DownloadStatus.ANALYZING,
            DownloadStatus.DOWNLOADING,
            DownloadStatus.PROCESSING,
            DownloadStatus.ORGANIZING,
        )

    @property
    def is_pending(self) -> bool:
        return self in (DownloadStatus.QUEUED, DownloadStatus.PAUSED)


# Video quality ladder, best first. Only entries the source actually offers are
# ever shown to the user.
VIDEO_QUALITIES: tuple[str, ...] = ("best", "2160p", "1440p", "1080p", "720p", "480p", "360p")
VIDEO_FORMATS: tuple[str, ...] = ("mp4", "mkv", "webm")
AUDIO_FORMATS: tuple[str, ...] = ("mp3", "m4a", "wav", "flac")
MP3_BITRATES: tuple[str, ...] = ("128", "192", "256", "320")

#: Audio formats where a bitrate choice is meaningful. WAV and FLAC are
#: lossless containers, so Mediary does not pretend a bitrate applies.
LOSSY_AUDIO_FORMATS = frozenset({"mp3", "m4a"})


def quality_to_height(quality: str) -> int:
    """``"1080p"`` -> ``1080``; ``"best"`` -> ``0`` (meaning unconstrained)."""
    if not quality or quality == "best":
        return 0
    try:
        return int(str(quality).rstrip("pP"))
    except ValueError:
        return 0


@dataclass
class DownloadOptions:
    """What the user chose on the Download screen for one item."""

    media_kind: str = KIND_VIDEO         # video | audio
    video_format: str = "mp4"
    video_quality: str = "best"
    audio_format: str = "mp3"
    audio_bitrate: str = "320"
    category: str = "Video"
    format_id: str = ""                  # explicit yt-dlp format, when picked
    embed_thumbnail: bool = True
    embed_metadata: bool = True

    @property
    def is_audio(self) -> bool:
        return self.media_kind == KIND_AUDIO

    @property
    def target_extension(self) -> str:
        return self.audio_format if self.is_audio else self.video_format

    def quality_label(self) -> str:
        """Short label for the queue row, e.g. ``"MP3 - 320 kbps"``."""
        if self.is_audio:
            fmt = self.audio_format.upper()
            if self.audio_format in LOSSY_AUDIO_FORMATS:
                return f"{fmt} - {self.audio_bitrate} kbps"
            return fmt
        quality = "Best" if self.video_quality == "best" else self.video_quality
        return f"{self.video_format.upper()} - {quality}"


@dataclass
class MediaInfo:
    """Normalised result of a yt-dlp metadata probe (no download performed)."""

    url: str = ""
    title: str = ""
    creator: str = ""
    platform: str = ""
    platform_id: str = ""
    duration: float = 0.0
    upload_date: str = ""
    description: str = ""
    thumbnail_url: str = ""
    thumbnail_path: str = ""
    is_live: bool = False
    formats: list = field(default_factory=list)   # list[FormatOption]
    raw: dict = field(default_factory=dict)

    @property
    def available_video_qualities(self) -> list:
        """Ladder entries the source actually provides, best first."""
        heights = {f.height for f in self.formats if f.has_video and f.height}
        available = ["best"]
        for quality in VIDEO_QUALITIES[1:]:
            target = quality_to_height(quality)
            if any(h >= target for h in heights):
                available.append(quality)
        return available

    @property
    def has_video(self) -> bool:
        return any(f.has_video for f in self.formats)

    @property
    def has_audio(self) -> bool:
        return any(f.has_audio for f in self.formats)

    @property
    def best_height(self) -> int:
        heights = [f.height for f in self.formats if f.has_video and f.height]
        return max(heights) if heights else 0


#: Container extensions that carry a video track.
VIDEO_EXTENSIONS = frozenset(
    {"mp4", "mkv", "webm", "mov", "avi", "flv", "m4v", "wmv", "ogv", "mpg", "mpeg", "ts", "3gp"}
)
#: Container extensions that are audio-only.
AUDIO_EXTENSIONS = frozenset(
    {"mp3", "m4a", "wav", "flac", "aac", "ogg", "oga", "opus", "wma", "aiff", "alac"}
)

#: yt-dlp uses the literal string ``"none"`` to mean "this stream is absent".
#: A *missing* codec field means "the extractor does not know", which is very
#: different - several extractors (archive.org among them) never report codecs.
CODEC_ABSENT = "none"
CODEC_UNKNOWN = ""


@dataclass
class FormatOption:
    """One selectable yt-dlp format."""

    format_id: str = ""
    ext: str = ""
    height: int = 0
    width: int = 0
    fps: float = 0.0
    vcodec: str = ""
    acodec: str = ""
    filesize: int = 0
    tbr: float = 0.0          # total bitrate, kbps
    abr: float = 0.0          # audio bitrate, kbps
    note: str = ""

    @property
    def has_video(self) -> bool:
        if self.vcodec == CODEC_ABSENT:
            return False
        if self.vcodec:
            return True
        # Codec unknown: fall back to what the dimensions and container imply.
        return bool(self.height or self.width) or self.ext.lower() in VIDEO_EXTENSIONS

    @property
    def has_audio(self) -> bool:
        if self.acodec == CODEC_ABSENT:
            return False
        if self.acodec:
            return True
        if self.abr:
            return True
        ext = self.ext.lower()
        # A muxed video container almost always carries an audio track too.
        return ext in AUDIO_EXTENSIONS or ext in VIDEO_EXTENSIONS

    @property
    def is_audio_only(self) -> bool:
        return self.has_audio and not self.has_video

    @property
    def resolution(self) -> str:
        if self.height:
            return f"{self.height}p"
        return "audio only" if self.is_audio_only else "—"


@dataclass
class Progress:
    """A single progress sample emitted by the download worker."""

    downloaded_bytes: int = 0
    total_bytes: int = 0
    speed: float = 0.0        # bytes/second
    eta: int = 0              # seconds
    fragment_index: int = 0
    fragment_count: int = 0

    @property
    def percent(self) -> float:
        if self.total_bytes > 0:
            return min(100.0, self.downloaded_bytes / self.total_bytes * 100.0)
        if self.fragment_count > 0:
            return min(100.0, self.fragment_index / self.fragment_count * 100.0)
        return 0.0


@dataclass
class DownloadTask:
    """A queue entry: the URL, the chosen options and its live state."""

    url: str
    options: DownloadOptions = field(default_factory=DownloadOptions)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: DownloadStatus = DownloadStatus.QUEUED
    info: MediaInfo | None = None
    progress: Progress = field(default_factory=Progress)
    error: str = ""
    error_detail: str = ""
    output_path: str = ""
    media_id: int | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    finished_at: str = ""
    attempts: int = 0
    stage_note: str = ""

    @property
    def display_title(self) -> str:
        if self.info and self.info.title:
            return self.info.title
        return self.url

    @property
    def platform(self) -> str:
        return self.info.platform if self.info else ""

    def reset_for_retry(self) -> None:
        self.status = DownloadStatus.QUEUED
        self.progress = Progress()
        self.error = ""
        self.error_detail = ""
        self.stage_note = ""
        self.finished_at = ""


__all__ = [
    "AUDIO_FORMATS",
    "DownloadOptions",
    "DownloadStatus",
    "DownloadTask",
    "FormatOption",
    "LOSSY_AUDIO_FORMATS",
    "MP3_BITRATES",
    "MediaInfo",
    "Progress",
    "VIDEO_FORMATS",
    "VIDEO_QUALITIES",
    "quality_to_height",
    "KIND_AUDIO",
    "KIND_VIDEO",
]
