"""Human-readable formatting helpers shared across the UI."""

from __future__ import annotations

from datetime import datetime, timezone

_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def format_bytes(size: float | int | None, *, precision: int | None = None) -> str:
    """``15_800_000`` -> ``"15.8 MB"``. Returns an em dash for unknown sizes."""
    if size is None or size < 0:
        return "—"
    value = float(size)
    index = 0
    while value >= 1024 and index < len(_UNITS) - 1:
        value /= 1024
        index += 1
    if precision is None:
        precision = 0 if index == 0 else (1 if value < 100 else 0)
    return f"{value:.{precision}f} {_UNITS[index]}"


def format_speed(bytes_per_second: float | None) -> str:
    if not bytes_per_second or bytes_per_second <= 0:
        return "—"
    return f"{format_bytes(bytes_per_second)}/s"


def format_duration(seconds: float | int | None) -> str:
    """``3725`` -> ``"1:02:05"``; ``12`` -> ``"0:12"``."""
    if seconds is None or seconds < 0:
        return "—"
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_eta(seconds: float | int | None) -> str:
    """Compact remaining-time label used in the download queue.

    yt-dlp reports ``0`` when it cannot estimate, so zero reads as unknown
    rather than as "finishing right now".
    """
    if not seconds or seconds < 0:
        return "—"
    total = int(round(seconds))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def format_date(value: str | datetime | None, *, with_time: bool = False) -> str:
    """Render an ISO timestamp or ``YYYYMMDD`` upload date for display."""
    if not value:
        return "—"
    moment = parse_datetime(value)
    if moment is None:
        return str(value)
    return moment.strftime("%d %b %Y, %H:%M" if with_time else "%d %b %Y")


def parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit() and len(text) == 8:  # yt-dlp's upload_date
        try:
            return datetime.strptime(text, "%Y%m%d")
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def relative_date(value: str | datetime | None) -> str:
    """``"Today"``, ``"Yesterday"``, ``"4 days ago"`` or an absolute date."""
    moment = parse_datetime(value)
    if moment is None:
        return "—"
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    delta = datetime.utcnow() - moment
    days = delta.days
    if days < 0:
        return moment.strftime("%d %b %Y")
    if days == 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 30:
        weeks = days // 7
        return f"{weeks} week{'s' if weeks > 1 else ''} ago"
    return moment.strftime("%d %b %Y")


def format_bitrate(kbps: float | int | None) -> str:
    if not kbps or kbps <= 0:
        return "—"
    return f"{int(round(kbps))} kbps"


def truncate(text: str, limit: int = 60) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
