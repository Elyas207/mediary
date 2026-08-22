"""Mediary's media taxonomy: media kinds, categories and their folder layout.

A *category* is the user-facing bucket ("Sound Effects"); each category knows
which media kind it belongs to and where on disk its files live relative to the
library root. Custom categories are supported and fall back to sensible
defaults for both of those.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

# --- Media kinds ---------------------------------------------------------

KIND_VIDEO = "video"
KIND_AUDIO = "audio"
KIND_OTHER = "other"
MEDIA_KINDS = (KIND_VIDEO, KIND_AUDIO, KIND_OTHER)


@dataclass(frozen=True)
class Category:
    """A library category and the folder it maps to."""

    name: str
    kind: str
    folder: str            # POSIX-style path relative to the library root
    description: str = ""
    accent: str = "slate"  # semantic colour key resolved by the theme
    builtin: bool = True

    @property
    def slug(self) -> str:
        return self.name.lower().replace(" ", "-")

    def relative_parts(self) -> tuple[str, ...]:
        return tuple(part for part in PurePosixPath(self.folder).parts if part)


#: Ordered so the UI can render them without re-sorting.
BUILTIN_CATEGORIES: tuple[Category, ...] = (
    Category("Video", KIND_VIDEO, "Video", "General video downloads", "blue"),
    Category("Inspiration", KIND_VIDEO, "Inspiration", "Reference and mood clips", "violet"),
    Category("Music", KIND_AUDIO, "Audio/Music", "Tracks and songs", "magenta"),
    Category("Sound Effects", KIND_AUDIO, "Audio/Sound Effects", "One-shots and stingers", "amber"),
    Category("Voice", KIND_AUDIO, "Audio/Voice", "Dialogue, VO and narration", "teal"),
    Category("Ambience", KIND_AUDIO, "Audio/Ambience", "Beds, rooms and atmospheres", "green"),
    Category("Foley", KIND_AUDIO, "Audio/Foley", "Performed practical sounds", "orange"),
    Category("Other", KIND_OTHER, "Other", "Anything that fits nowhere else", "slate"),
)

BUILTIN_BY_NAME: dict[str, Category] = {c.name: c for c in BUILTIN_CATEGORIES}

DEFAULT_CATEGORY = "Video"

#: Categories offered by default for each media kind, in menu order.
CATEGORIES_BY_KIND: dict[str, tuple[str, ...]] = {
    KIND_VIDEO: ("Video", "Inspiration", "Other"),
    KIND_AUDIO: ("Music", "Sound Effects", "Voice", "Ambience", "Foley", "Other"),
    KIND_OTHER: ("Other",),
}

#: Suggested tags shown when tagging a sound effect. Purely a convenience -
#: the user can create any tag they like.
SOUND_EFFECT_TAGS: tuple[str, ...] = (
    "Whoosh", "Impact", "Hit", "Transition", "Explosion", "Footsteps",
    "Foley", "UI", "Mechanical", "Nature", "Crowd", "Ambience", "Other",
)

MUSIC_TAGS: tuple[str, ...] = (
    "Cinematic", "Ambient", "Electronic", "Hip Hop", "Corporate",
    "Dramatic", "Chill", "Upbeat", "Acoustic", "Orchestral",
)

INSPIRATION_TAGS: tuple[str, ...] = (
    "Editing", "Cinematography", "Motion", "Transition", "Colour",
    "Typography", "Sound Design", "Concept",
)


def suggested_tags(category: str) -> tuple[str, ...]:
    if category == "Sound Effects":
        return SOUND_EFFECT_TAGS
    if category == "Music":
        return MUSIC_TAGS
    if category == "Inspiration":
        return INSPIRATION_TAGS
    if category in ("Foley", "Ambience"):
        return SOUND_EFFECT_TAGS
    return ()


def make_custom_category(name: str, kind: str = KIND_OTHER) -> Category:
    """Build a :class:`Category` for a user-defined name.

    Custom categories live in a top-level folder named after them, except audio
    ones which nest under ``Audio/`` to match the built-in layout.
    """
    clean = " ".join(str(name).split()).strip() or "Custom"
    kind = kind if kind in MEDIA_KINDS else KIND_OTHER
    folder = f"Audio/{clean}" if kind == KIND_AUDIO else clean
    return Category(clean, kind, folder, "Custom category", "slate", builtin=False)


def resolve_category(name: str, custom: dict | None = None) -> Category:
    """Look up a category by name, falling back to a custom or generic one."""
    if name in BUILTIN_BY_NAME:
        return BUILTIN_BY_NAME[name]
    if custom and name in custom:
        entry = custom[name]
        if isinstance(entry, Category):
            return entry
        if isinstance(entry, dict):
            return make_custom_category(name, entry.get("kind", KIND_OTHER))
    return make_custom_category(name)


def kind_for_category(name: str) -> str:
    return resolve_category(name).kind


def categories_for_kind(kind: str, custom_names: list | None = None) -> list:
    """Category names appropriate for a media kind, custom ones appended."""
    names = list(CATEGORIES_BY_KIND.get(kind, CATEGORIES_BY_KIND[KIND_OTHER]))
    for extra in custom_names or []:
        if extra not in names and extra not in BUILTIN_BY_NAME:
            names.insert(len(names) - 1, extra)
    return names


def default_folder_tree() -> tuple[str, ...]:
    """Folders created under the library root on first run."""
    return tuple(dict.fromkeys(c.folder for c in BUILTIN_CATEGORIES))
