"""The library's core record types.

``MediaItem`` mirrors one row of the ``media`` table plus its tags. It is a
plain dataclass so services and the UI can pass it around without dragging a
database connection along.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.models.category import KIND_AUDIO, KIND_OTHER, KIND_VIDEO

# --- Licensing -----------------------------------------------------------
#
# Mediary never infers any of these. They exist purely so the user can record
# what they have determined themselves.

LICENSE_ROYALTY_FREE = "Royalty Free"
LICENSE_CREATIVE_COMMONS = "Creative Commons"
LICENSE_PUBLIC_DOMAIN = "Public Domain"
LICENSE_LICENSED = "Licensed"
LICENSE_PERSONAL_USE = "Personal Use"
LICENSE_UNKNOWN = "Unknown"
LICENSE_OTHER = "Other"

LICENSE_OPTIONS: tuple[str, ...] = (
    LICENSE_UNKNOWN,
    LICENSE_ROYALTY_FREE,
    LICENSE_CREATIVE_COMMONS,
    LICENSE_PUBLIC_DOMAIN,
    LICENSE_LICENSED,
    LICENSE_PERSONAL_USE,
    LICENSE_OTHER,
)

ATTRIBUTION_YES = "Yes"
ATTRIBUTION_NO = "No"
ATTRIBUTION_UNKNOWN = "Unknown"
ATTRIBUTION_OPTIONS: tuple[str, ...] = (
    ATTRIBUTION_UNKNOWN,
    ATTRIBUTION_YES,
    ATTRIBUTION_NO,
)


@dataclass
class MediaItem:
    """One entry in the Mediary library."""

    id: int | None = None

    # Identity on disk
    filename: str = ""
    file_path: str = ""
    file_size: int = 0
    file_missing: bool = False

    # Provenance - never discarded
    source_url: str = ""
    platform: str = ""
    platform_id: str = ""
    title: str = ""
    creator: str = ""
    upload_date: str = ""
    downloaded_at: str = ""

    # Classification
    media_kind: str = KIND_VIDEO      # video | audio | other
    category: str = "Video"
    #: How the category was decided - see models/filing.SOURCE_*. Smart filing
    #: weights its evidence by this, so it cannot train on its own guesses.
    category_source: str = ""

    # Technical
    duration: float = 0.0
    container: str = ""               # mp4, mkv, mp3 ...
    width: int = 0
    height: int = 0
    fps: float = 0.0
    video_codec: str = ""
    audio_codec: str = ""
    audio_bitrate: int = 0
    sample_rate: int = 0

    # Presentation
    thumbnail_path: str = ""

    # Licensing - user-supplied only
    license_type: str = LICENSE_UNKNOWN
    license_url: str = ""
    attribution_required: str = ATTRIBUTION_UNKNOWN
    license_notes: str = ""

    # User data
    notes: str = ""
    favorite: bool = False
    play_count: int = 0
    tags: list = field(default_factory=list)

    # -- Derived ----------------------------------------------------------

    @property
    def path(self) -> Path:
        return Path(self.file_path)

    @property
    def exists(self) -> bool:
        try:
            return bool(self.file_path) and Path(self.file_path).is_file()
        except OSError:
            return False

    @property
    def is_audio(self) -> bool:
        return self.media_kind == KIND_AUDIO

    @property
    def is_video(self) -> bool:
        return self.media_kind == KIND_VIDEO

    @property
    def resolution(self) -> str:
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        return ""

    @property
    def quality_label(self) -> str:
        """``1080p``-style label, derived from the stored height."""
        if not self.height:
            return ""
        return f"{self.height}p"

    @property
    def display_title(self) -> str:
        return self.title or self.filename or "Untitled"

    def stem(self) -> str:
        return Path(self.filename).stem if self.filename else self.display_title

    def to_row(self) -> dict:
        """Column values for the ``media`` table (tags handled separately)."""
        return {
            "filename": self.filename,
            "file_path": self.file_path,
            "file_size": int(self.file_size or 0),
            "file_missing": int(bool(self.file_missing)),
            "source_url": self.source_url,
            "platform": self.platform,
            "platform_id": self.platform_id,
            "title": self.title,
            "creator": self.creator,
            "upload_date": self.upload_date,
            "downloaded_at": self.downloaded_at or datetime.now().isoformat(timespec="seconds"),
            "media_kind": self.media_kind,
            "category": self.category,
            "category_source": self.category_source,
            "duration": float(self.duration or 0.0),
            "container": self.container,
            "width": int(self.width or 0),
            "height": int(self.height or 0),
            "fps": float(self.fps or 0.0),
            "video_codec": self.video_codec,
            "audio_codec": self.audio_codec,
            "audio_bitrate": int(self.audio_bitrate or 0),
            "sample_rate": int(self.sample_rate or 0),
            "thumbnail_path": self.thumbnail_path,
            "license_type": self.license_type,
            "license_url": self.license_url,
            "attribution_required": self.attribution_required,
            "license_notes": self.license_notes,
            "notes": self.notes,
            "favorite": int(bool(self.favorite)),
            "play_count": int(self.play_count or 0),
        }

    @classmethod
    def from_row(cls, row, tags: list | None = None) -> MediaItem:
        data = dict(row)
        item = cls(
            id=data.get("id"),
            filename=data.get("filename") or "",
            file_path=data.get("file_path") or "",
            file_size=data.get("file_size") or 0,
            file_missing=bool(data.get("file_missing")),
            source_url=data.get("source_url") or "",
            platform=data.get("platform") or "",
            platform_id=data.get("platform_id") or "",
            title=data.get("title") or "",
            creator=data.get("creator") or "",
            upload_date=data.get("upload_date") or "",
            downloaded_at=data.get("downloaded_at") or "",
            media_kind=data.get("media_kind") or KIND_OTHER,
            category=data.get("category") or "Other",
            category_source=data.get("category_source") or "",
            duration=data.get("duration") or 0.0,
            container=data.get("container") or "",
            width=data.get("width") or 0,
            height=data.get("height") or 0,
            fps=data.get("fps") or 0.0,
            video_codec=data.get("video_codec") or "",
            audio_codec=data.get("audio_codec") or "",
            audio_bitrate=data.get("audio_bitrate") or 0,
            sample_rate=data.get("sample_rate") or 0,
            thumbnail_path=data.get("thumbnail_path") or "",
            license_type=data.get("license_type") or LICENSE_UNKNOWN,
            license_url=data.get("license_url") or "",
            attribution_required=data.get("attribution_required") or ATTRIBUTION_UNKNOWN,
            license_notes=data.get("license_notes") or "",
            notes=data.get("notes") or "",
            favorite=bool(data.get("favorite")),
            play_count=data.get("play_count") or 0,
        )
        item.tags = list(tags or [])
        return item


def kind_from_container(container: str) -> str:
    """Best-effort media kind for a file extension."""
    ext = (container or "").lower().lstrip(".")
    if ext in {"mp3", "m4a", "wav", "flac", "aac", "ogg", "opus", "wma", "aiff", "alac"}:
        return KIND_AUDIO
    if ext in {"mp4", "mkv", "webm", "mov", "avi", "flv", "m4v", "wmv", "ts", "mpg", "mpeg"}:
        return KIND_VIDEO
    return KIND_OTHER
