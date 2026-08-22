"""The yt-dlp boundary.

Everything that knows about yt-dlp's option dictionary, its format selectors and
its error strings lives here, so the rest of Mediary deals only in
:class:`MediaInfo` / :class:`DownloadOptions`.

Scope note: this adapter performs ordinary public extraction only. It never
supplies credentials or cookies, and it does not retry differently when a
failure is due to a private, paywalled or DRM-protected item - such failures are
reported to the user as-is.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from app.models.download import (
    LOSSY_AUDIO_FORMATS,
    DownloadOptions,
    FormatOption,
    MediaInfo,
    quality_to_height,
)
from app.utils.logging import get_logger, redact
from app.utils.paths import cache_dir

log = get_logger("ytdlp")


class DownloadCancelled(Exception):
    """Raised inside a yt-dlp progress hook to abort a download cleanly."""


class ExtractionError(Exception):
    """A user-facing extraction failure with the raw detail kept separately."""

    def __init__(self, message: str, detail: str = "", *, category: str = "error") -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail
        self.category = category


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------

#: ``(pattern, category, human message)`` - first match wins.
_ERROR_RULES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"private video|this video is private|private account", re.I), "private",
     "This content is private. Mediary only downloads publicly accessible media."),
    (re.compile(r"login required|sign in to confirm|requires authentication|"
                r"account.{0,20}required|members[- ]only|premium", re.I), "auth",
     "This content requires signing in. Mediary does not bypass authentication."),
    (re.compile(r"drm|protected content|widevine|encrypted", re.I), "drm",
     "This content is DRM-protected and cannot be downloaded."),
    (re.compile(r"paid|purchase|subscri(be|ption)|paywall", re.I), "paywall",
     "This content sits behind a paywall or subscription."),
    # Rate limiting must be classified before the generic 4xx rule below,
    # since a 429 is also an HTTP 4xx.
    (re.compile(r"rate[- ]?limit|too many requests|\b429\b", re.I), "ratelimit",
     "The site is rate-limiting requests. Wait a moment and retry."),
    (re.compile(r"available in your country|geo[- ]restricted|geo blocked|"
                r"blocked it in your country|not available from your location", re.I), "region",
     "This content is not available in your region."),
    (re.compile(r"video unavailable|has been removed|no longer available|"
                r"account.{0,20}terminated|deleted", re.I), "unavailable",
     "This content is no longer available at that URL."),
    (re.compile(r"age[- ]restricted|confirm your age|inappropriate for some users", re.I), "age",
     "This content is age-restricted and needs a signed-in account."),
    (re.compile(r"unsupported url|no video formats found|unable to extract|"
                r"is not a valid url", re.I), "unsupported",
     "Mediary could not find downloadable media at that URL."),
    (re.compile(r"requested format (is )?not available", re.I), "format",
     "The requested format is not available for this item. Try a different quality."),
    (re.compile(r"unable to download webpage|failed to resolve|name or service not known|"
                r"connection (reset|refused|aborted)|timed out|temporary failure", re.I),
     "network",
     "Mediary could not reach that site. Check your connection and try again."),
    (re.compile(r"http error 4\d\d", re.I), "http",
     "The server refused the request for that URL."),
    (re.compile(r"http error 5\d\d", re.I), "server",
     "The server had a problem. Try again in a moment."),
    (re.compile(r"no space left|disk full", re.I), "disk",
     "There is not enough free disk space to finish this download."),
    (re.compile(r"permission denied|access is denied|errno 13", re.I), "permission",
     "Mediary does not have permission to write to that folder."),
    (re.compile(r"ffmpeg|ffprobe", re.I), "ffmpeg",
     "This download needs FFmpeg, which is not configured."),
)


def translate_error(raw: str) -> tuple:
    """Map a yt-dlp error into ``(category, human message, safe detail)``."""
    text = redact(str(raw or "").strip())
    # yt-dlp prefixes most messages with "ERROR: " and the extractor name.
    cleaned = re.sub(r"^ERROR:\s*", "", text)
    cleaned = re.sub(r"^\[[^\]]+\]\s*", "", cleaned)
    for pattern, category, message in _ERROR_RULES:
        if pattern.search(cleaned):
            return category, message, text
    if not cleaned:
        return "error", "The download failed for an unknown reason.", text
    return "error", "The download failed. See the details for the exact message.", text


# ---------------------------------------------------------------------------
# Platform naming
# ---------------------------------------------------------------------------

_PLATFORM_NAMES: dict[str, str] = {
    "youtube": "YouTube",
    "youtu.be": "YouTube",
    "youtube:tab": "YouTube",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "tiktok": "TikTok",
    "vimeo": "Vimeo",
    "soundcloud": "SoundCloud",
    "twitter": "X",
    "x": "X",
    "twitch": "Twitch",
    "dailymotion": "Dailymotion",
    "bandcamp": "Bandcamp",
    "reddit": "Reddit",
    "pixabay": "Pixabay",
    "archive.org": "Internet Archive",
    "archiveorg": "Internet Archive",
    "internetarchive": "Internet Archive",
    "wikimedia": "Wikimedia",
    "freesound": "Freesound",
    "mixcloud": "Mixcloud",
    "bilibili": "Bilibili",
    "rumble": "Rumble",
    "odysee": "Odysee",
    "peertube": "PeerTube",
    "nrk": "NRK",
    "generic": "Web",
}


def platform_name(extractor: str, url: str = "") -> str:
    """A tidy display name for the source platform."""
    key = (extractor or "").split(":")[0].strip().lower()
    # "generic" means yt-dlp had no dedicated extractor, so the host is a far
    # better label than the word "generic".
    if key and key != "generic":
        if key in _PLATFORM_NAMES:
            return _PLATFORM_NAMES[key]
        return extractor.split(":")[0].strip().title()

    host = urlparse(url).netloc.lower().split("@")[-1].split(":")[0].removeprefix("www.")
    if not host:
        return "Web"

    # Match whole host labels, not substrings: a one-letter platform key such
    # as "x" would otherwise match the "x" inside "example.com".
    labels = host.split(".")
    for needle, name in _PLATFORM_NAMES.items():
        if needle == "generic":
            continue
        if needle in labels or ("." in needle and needle in host):
            return name
    return labels[0].title()


URL_RE = re.compile(r"^https?://[^\s/$.?#][^\s]*$", re.I)

#: A bare token only becomes a URL if it looks like ``host.tld`` with a
#: plausible TLD. Without this, pasting prose would turn every word into a URL.
_BARE_DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,24}(?::\d{1,5})?(?:[/?#].*)?$",
    re.I,
)


def is_probable_url(text: str) -> bool:
    """Loose URL check used to validate pasted input before any network call."""
    candidate = (text or "").strip()
    if not candidate or any(c.isspace() for c in candidate):
        return False
    if candidate.lower().startswith(("http://", "https://")):
        if not URL_RE.match(candidate):
            return False
        host = urlparse(candidate).netloc.split("@")[-1].split(":")[0]
        return "." in host and not host.startswith(".") and not host.endswith(".")
    return bool(_BARE_DOMAIN_RE.match(candidate))


def normalize_url(text: str) -> str:
    """Trim decoration and add a scheme, but only to something domain-shaped."""
    candidate = (text or "").strip().strip("<>\"'`,;")
    if not candidate:
        return ""
    if candidate.lower().startswith(("http://", "https://")):
        return candidate
    if _BARE_DOMAIN_RE.match(candidate):
        return "https://" + candidate
    return candidate


def parse_urls(text: str) -> list:
    """Split pasted text into a de-duplicated list of candidate URLs.

    Accepts newline-, comma- and whitespace-separated input, which is what
    people actually paste from a notes app or a spreadsheet.
    """
    if not text:
        return []
    tokens = re.split(r"[\s,;]+", str(text))
    seen: dict = {}
    for token in tokens:
        candidate = normalize_url(token)
        if candidate and is_probable_url(candidate) and candidate not in seen:
            seen[candidate] = True
    return list(seen)


# ---------------------------------------------------------------------------
# Format selection
# ---------------------------------------------------------------------------


def build_format_selector(options: DownloadOptions, *, has_ffmpeg: bool) -> str:
    """Translate the user's choices into a yt-dlp format string.

    Without FFmpeg we cannot merge separate video and audio streams, so we ask
    for a progressive (already-muxed) stream instead of silently producing a
    video with no sound.
    """
    if options.format_id:
        return options.format_id

    if options.is_audio:
        return "bestaudio/best"

    height = quality_to_height(options.video_quality)
    container = options.video_format

    if not has_ffmpeg:
        # Progressive streams only.
        if height:
            return f"best[height<=?{height}][acodec!=none][vcodec!=none]/best[height<=?{height}]/best"
        return "best[acodec!=none][vcodec!=none]/best"

    if container == "mp4":
        preference = "[ext=mp4]"
        audio_preference = "[ext=m4a]"
    elif container == "webm":
        preference = "[ext=webm]"
        audio_preference = "[ext=webm]"
    else:  # mkv accepts anything
        preference = ""
        audio_preference = ""

    limit = f"[height<=?{height}]" if height else ""
    return (
        f"bestvideo{limit}{preference}+bestaudio{audio_preference}/"
        f"bestvideo{limit}+bestaudio/"
        f"best{limit}{preference}/best{limit}/best"
    )


def build_postprocessors(options: DownloadOptions, *, has_ffmpeg: bool) -> list:
    """FFmpeg post-processing steps for the chosen output."""
    if not has_ffmpeg:
        return []

    processors: list = []

    if options.is_audio:
        extractor = {
            "key": "FFmpegExtractAudio",
            "preferredcodec": options.audio_format,
            "nopostoverwrites": False,
        }
        # A bitrate only means something for lossy codecs. Passing one for WAV
        # or FLAC would be meaningless, so we omit it.
        if options.audio_format in LOSSY_AUDIO_FORMATS:
            extractor["preferredquality"] = str(options.audio_bitrate)
        processors.append(extractor)
    else:
        processors.append({"key": "FFmpegVideoRemuxer", "preferedformat": options.video_format})

    if options.embed_metadata:
        processors.append(
            {"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": True}
        )
    if options.embed_thumbnail:
        # Only containers that can actually carry cover art.
        target = options.target_extension
        if target in {"mp3", "m4a", "mp4", "mkv", "flac"}:
            processors.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})

    return processors


# ---------------------------------------------------------------------------
# Option building
# ---------------------------------------------------------------------------


@dataclass
class RuntimeConfig:
    """Non-format runtime knobs pulled from user settings."""

    ffmpeg_location: str = ""
    max_speed_kbps: int = 0
    retries: int = 3
    socket_timeout: int = 30
    write_thumbnail: bool = True

    @property
    def rate_limit(self):
        return self.max_speed_kbps * 1024 if self.max_speed_kbps > 0 else None


def base_options(config: RuntimeConfig | None = None) -> dict:
    """yt-dlp options shared by analysis and download."""
    config = config or RuntimeConfig()
    options: dict = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "ignoreerrors": False,
        "no_color": True,
        "socket_timeout": max(5, int(config.socket_timeout)),
        "retries": max(0, int(config.retries)),
        "fragment_retries": max(0, int(config.retries)),
        "extractor_retries": 1,
        "cachedir": str(cache_dir() / "ytdlp"),
        # Mediary is strictly local-first: never write cookies, netrc or any
        # credential material, and never read the user's browser profile.
        "cookiefile": None,
        "cookiesfrombrowser": None,
        "usenetrc": False,
        "consoletitle": False,
    }
    if config.ffmpeg_location:
        options["ffmpeg_location"] = config.ffmpeg_location
    if config.rate_limit:
        options["ratelimit"] = config.rate_limit
    return options


def analysis_options(config: RuntimeConfig | None = None) -> dict:
    options = base_options(config)
    options.update({"skip_download": True, "simulate": True})
    return options


def download_options(
    task_options: DownloadOptions,
    destination: Path,
    *,
    config: RuntimeConfig | None = None,
    has_ffmpeg: bool = True,
    progress_hook=None,
    postprocessor_hook=None,
    outtmpl_stem: str = "%(title)s",
) -> dict:
    """Full yt-dlp option dict for one download into ``destination``."""
    config = config or RuntimeConfig()
    options = base_options(config)
    options.update(
        {
            "format": build_format_selector(task_options, has_ffmpeg=has_ffmpeg),
            "outtmpl": {"default": str(Path(destination) / f"{outtmpl_stem}.%(ext)s")},
            "paths": {"home": str(destination), "temp": str(destination)},
            "postprocessors": build_postprocessors(task_options, has_ffmpeg=has_ffmpeg),
            "writethumbnail": bool(
                config.write_thumbnail or (task_options.embed_thumbnail and has_ffmpeg)
            ),
            "overwrites": False,
            "continuedl": True,
            "windowsfilenames": os.name == "nt",
            "trim_file_name": 180,
            "restrictfilenames": False,
        }
    )
    if not task_options.is_audio and has_ffmpeg:
        options["merge_output_format"] = task_options.video_format
    if progress_hook is not None:
        options["progress_hooks"] = [progress_hook]
    if postprocessor_hook is not None:
        options["postprocessor_hooks"] = [postprocessor_hook]
    return options


# ---------------------------------------------------------------------------
# Info normalisation
# ---------------------------------------------------------------------------


def parse_formats(raw_formats: list) -> list:
    """Turn yt-dlp's format dicts into :class:`FormatOption`s, best first."""
    parsed: list = []
    for entry in raw_formats or []:
        if not isinstance(entry, dict):
            continue
        format_id = str(entry.get("format_id") or "")
        if not format_id or entry.get("ext") in (None, "mhtml"):
            continue
        parsed.append(
            FormatOption(
                format_id=format_id,
                ext=str(entry.get("ext") or ""),
                height=_int(entry.get("height")),
                width=_int(entry.get("width")),
                fps=_float(entry.get("fps")),
                # Preserve the distinction between "no such stream" ("none")
                # and "the extractor did not say" (missing -> empty string).
                vcodec=_codec(entry.get("vcodec")),
                acodec=_codec(entry.get("acodec")),
                filesize=_int(entry.get("filesize") or entry.get("filesize_approx")),
                tbr=_float(entry.get("tbr")),
                abr=_float(entry.get("abr")),
                note=str(entry.get("format_note") or ""),
            )
        )
    parsed.sort(key=lambda f: (f.height, f.tbr, f.abr), reverse=True)
    return parsed


def info_from_dict(payload: dict, url: str = "") -> MediaInfo:
    """Normalise a yt-dlp ``extract_info`` result into :class:`MediaInfo`."""
    payload = payload or {}
    # A playlist page yields entries; Mediary analyses the first item so the
    # user always sees something concrete rather than an opaque failure.
    if payload.get("_type") == "playlist" and payload.get("entries"):
        entries = [e for e in payload["entries"] if e]
        if entries:
            payload = entries[0]

    extractor = str(payload.get("extractor_key") or payload.get("extractor") or "")
    source_url = str(payload.get("webpage_url") or url or "")

    info = MediaInfo(
        url=source_url,
        title=str(payload.get("title") or payload.get("id") or "Untitled").strip(),
        creator=str(
            payload.get("uploader")
            or payload.get("channel")
            or payload.get("artist")
            or payload.get("creator")
            or ""
        ).strip(),
        platform=platform_name(extractor, source_url),
        platform_id=str(payload.get("id") or ""),
        duration=_float(payload.get("duration")),
        upload_date=str(payload.get("upload_date") or ""),
        description=str(payload.get("description") or ""),
        thumbnail_url=_best_thumbnail(payload),
        is_live=bool(payload.get("is_live")),
        formats=parse_formats(payload.get("formats") or []),
        raw=payload,
    )
    if not info.formats and payload.get("url"):
        # Single-format extractors (many generic sites) expose no format list.
        info.formats = [
            FormatOption(
                format_id=str(payload.get("format_id") or "0"),
                ext=str(payload.get("ext") or ""),
                height=_int(payload.get("height")),
                width=_int(payload.get("width")),
                fps=_float(payload.get("fps")),
                vcodec=_codec(payload.get("vcodec")),
                acodec=_codec(payload.get("acodec")),
                filesize=_int(payload.get("filesize") or payload.get("filesize_approx")),
            )
        ]
    return info


def _codec(value) -> str:
    """Normalise a yt-dlp codec field.

    ``"none"`` (the stream is absent) is preserved verbatim; a missing value
    becomes an empty string meaning "unknown", which downstream code resolves
    from the resolution and container instead of guessing wrong.
    """
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in ("null", "unknown", "?"):
        return ""
    return text


def _best_thumbnail(payload: dict) -> str:
    direct = payload.get("thumbnail")
    if direct:
        return str(direct)
    thumbnails = payload.get("thumbnails") or []
    best, best_area = "", -1
    for entry in thumbnails:
        if not isinstance(entry, dict) or not entry.get("url"):
            continue
        area = _int(entry.get("width")) * _int(entry.get("height"))
        if area >= best_area:
            best, best_area = str(entry["url"]), area
    return best


def _int(value) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def ytdlp_version() -> str:
    try:
        from yt_dlp.version import __version__

        return str(__version__)
    except Exception:  # pragma: no cover - yt-dlp always ships this
        return "unknown"
