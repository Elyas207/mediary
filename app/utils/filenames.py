"""Filename generation and sanitisation that is safe on Windows, macOS and Linux.

The rules implemented here are deliberately the *intersection* of the three
platforms' restrictions, so a library created on one OS stays portable to the
others (a very common case when media lives on an external drive).
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

#: Characters forbidden by NTFS/exFAT, plus the POSIX path separator.
_ILLEGAL_CHARS = r'<>:"/\|?*'
_ILLEGAL_RE = re.compile(f"[{re.escape(_ILLEGAL_CHARS)}]")
#: Control characters that are *whitespace* become a space; the rest vanish.
#: Deleting a tab outright would silently glue two words together.
_CONTROL_WHITESPACE_RE = re.compile(r"[\t\n\r\v\f]")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"\s+")
#: Characters trimmed from both ends. A leading dash can be read as a CLI flag,
#: and a trailing dot or space is silently dropped by Windows.
_EDGE_CHARS = " .-_–—·"

#: Device names that Windows refuses to use, with or without an extension.
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
    "COM¹", "COM²", "COM³",
    "LPT¹", "LPT²", "LPT³",
}

#: Conservative per-component budget. NTFS/APFS/ext4 all allow 255, but we keep
#: headroom for the " (12)" de-duplication suffix and the extension.
MAX_STEM_BYTES = 180
MAX_COMPONENT_BYTES = 240

FALLBACK_STEM = "Untitled"

#: Characters that look like separators but are illegal, mapped to readable text.
_REPLACEMENTS = {
    "/": "-",
    "\\": "-",
    ":": " -",
    "|": "-",
    "<": "(",
    ">": ")",
    '"': "'",
    "?": "",
    "*": "",
}


def _truncate_bytes(text: str, limit: int) -> str:
    """Trim ``text`` so its UTF-8 encoding fits ``limit`` bytes, never splitting
    a character and preferring to break on a word boundary."""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    clipped = encoded[:limit].decode("utf-8", errors="ignore")
    # Prefer cutting at the last space so we do not end mid-word.
    pivot = clipped.rfind(" ")
    if pivot >= limit // 2:
        clipped = clipped[:pivot]
    return clipped.rstrip(_EDGE_CHARS)


def sanitize_component(
    name: str,
    *,
    max_bytes: int = MAX_STEM_BYTES,
    fallback: str = FALLBACK_STEM,
) -> str:
    """Turn arbitrary text into a single safe path component (no extension).

    Handles illegal characters, control characters, Unicode normalisation,
    Windows reserved device names, trailing dots/spaces and over-long titles.
    """
    if not name:
        return fallback

    # NFC keeps composed accents stable across macOS (which prefers NFD) and
    # the other platforms, so the same title yields the same filename anywhere.
    text = unicodedata.normalize("NFC", str(name))
    text = _CONTROL_WHITESPACE_RE.sub(" ", text)
    text = _CONTROL_RE.sub("", text)

    for source, target in _REPLACEMENTS.items():
        text = text.replace(source, target)
    # Anything still illegal (defensive: keeps the two lists in sync).
    text = _ILLEGAL_RE.sub("", text)

    text = _WHITESPACE_RE.sub(" ", text).strip()
    text = text.strip(_EDGE_CHARS)

    # A title made entirely of punctuation leaves nothing meaningful behind.
    if not text or not any(c.isalnum() for c in text):
        return fallback

    text = _truncate_bytes(text, max_bytes)
    text = text.strip(_EDGE_CHARS)
    if not text:
        return fallback

    if text.split(".")[0].upper() in _RESERVED_NAMES:
        text = f"_{text}"

    return text


def sanitize_filename(name: str, extension: str = "", **kwargs) -> str:
    """Sanitise ``name`` and append a normalised ``extension``."""
    stem = sanitize_component(name, **kwargs)
    ext = normalize_extension(extension)
    if not ext:
        return stem
    # Guard against a pathological extension pushing the component over budget.
    stem = _truncate_bytes(stem, MAX_COMPONENT_BYTES - len(ext.encode("utf-8")) - 1)
    return f"{stem}{ext}"


def normalize_extension(extension: str) -> str:
    """Return ``.mp3`` for inputs like ``mp3``, ``.MP3`` or ``  .mp3 ``."""
    ext = (extension or "").strip().lower()
    if not ext:
        return ""
    ext = ext.lstrip(".")
    ext = re.sub(r"[^a-z0-9]", "", ext)
    return f".{ext}" if ext else ""


def unique_path(path: Path | str) -> Path:
    """Return a path that does not exist yet, using ``name (1).ext`` suffixes.

    Mediary never silently overwrites a file, so every write goes through here.
    """
    path = Path(path)
    if not path.exists():
        return path

    parent, stem, suffix = path.parent, path.stem, path.suffix
    # If the name already ends in " (n)", continue that sequence rather than
    # producing "clip (1) (1).mp4".
    match = re.match(r"^(?P<base>.*?) \((?P<index>\d+)\)$", stem)
    if match:
        stem = match.group("base")
        counter = int(match.group("index")) + 1
    else:
        counter = 1

    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1
        if counter > 9999:  # pathological directory; fall back to a nonce
            import uuid

            return parent / f"{stem} ({uuid.uuid4().hex[:8]}){suffix}"


#: Fields accepted by the user-configurable filename template.
TEMPLATE_FIELDS = (
    "title",
    "creator",
    "platform",
    "category",
    "quality",
    "ext",
    "date",
    "id",
)

_TOKEN_RE = re.compile(r"\{(\w+)\}")


def render_template(template: str, values: dict[str, object]) -> str:
    """Render a filename template such as ``{title}`` or ``{creator} - {title}``.

    Unknown tokens are dropped rather than raising, and empty values collapse
    so a template never leaves dangling separators like ``" - .mp3"``.
    """
    def substitute(match: re.Match[str]) -> str:
        key = match.group(1)
        value = values.get(key)
        if value is None:
            return ""
        return sanitize_component(str(value), fallback="")

    rendered = _TOKEN_RE.sub(substitute, template or "{title}")
    # Clean up punctuation orphaned by empty tokens, so a template like
    # "{creator} - {title} [{quality}]" never yields "Title []".
    rendered = re.sub(r"[\[\(\{<]\s*[\]\)\}>]", "", rendered)
    rendered = re.sub(r"\s*[-–_·|]\s*(?=[-–_·|]|$)", "", rendered)
    rendered = re.sub(r"^\s*[-–_·|]\s*", "", rendered)
    rendered = _WHITESPACE_RE.sub(" ", rendered).strip(" -_–·|")
    # A template is a *filename* template: literal separators in the template
    # itself must not silently create sub-directories.
    return sanitize_component(rendered, fallback=FALLBACK_STEM)
