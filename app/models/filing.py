"""Types for smart filing: where a download should go.

Filing is not a guess about what something *is*, it is a reading of what the
user habitually does. The same creator's material almost always belongs in the
same place, and that evidence is already in the library.

Nothing here touches licensing. Inferring an organisational bucket from
someone's own filing habits and inferring whether media is legally reusable are
different claims, and Mediary only ever makes the first.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# --- How a category came to be set ---------------------------------------
#
# Recorded per item so the suggester can weight its evidence. Without this it
# would learn from its own suggestions and reinforce them indefinitely.

SOURCE_USER = "user"            # deliberately chosen by a person
SOURCE_RULE = "rule"            # matched a rule the user wrote
SOURCE_SUGGESTED = "suggested"  # suggested and left alone
SOURCE_DEFAULT = "default"      # nothing better was known
SOURCE_UNKNOWN = ""             # predates the feature; historically hand-picked

#: How much each source counts when learning. A deliberate choice is real
#: evidence; an unchallenged suggestion is weak, because silence is not assent.
SOURCE_WEIGHTS: dict = {
    SOURCE_USER: 1.0,
    SOURCE_RULE: 1.0,
    SOURCE_UNKNOWN: 1.0,
    SOURCE_SUGGESTED: 0.5,
    SOURCE_DEFAULT: 0.25,
}


def source_weight(source: str) -> float:
    return SOURCE_WEIGHTS.get(source or SOURCE_UNKNOWN, 1.0)


#: Provenances that mean the user actually decided, rather than accepting or
#: ignoring what Mediary picked. Items imported before filing existed count as
#: deliberate: they were filed by hand or by an explicit default.
DELIBERATE_SOURCES = frozenset({SOURCE_USER, SOURCE_RULE, SOURCE_UNKNOWN})


def is_deliberate(source: str) -> bool:
    """Whether this category was a real choice rather than an unchallenged guess."""
    return (source or SOURCE_UNKNOWN) in DELIBERATE_SOURCES


# --- Rules ----------------------------------------------------------------

FIELD_CREATOR = "creator"
FIELD_PLATFORM = "platform"
FIELD_TITLE = "title_contains"
FIELD_URL = "url_contains"

RULE_FIELDS: tuple = (FIELD_CREATOR, FIELD_PLATFORM, FIELD_TITLE, FIELD_URL)

FIELD_LABELS: dict = {
    FIELD_CREATOR: "Creator is",
    FIELD_PLATFORM: "Platform is",
    FIELD_TITLE: "Title contains",
    FIELD_URL: "URL contains",
}


@dataclass
class FilingRule:
    """A user-authored "always put this there" instruction."""

    id: int | None = None
    field: str = FIELD_CREATOR
    pattern: str = ""
    category: str = ""
    enabled: bool = True
    priority: int = 100
    times_applied: int = 0
    created_at: str = ""

    def matches(self, *, creator: str, platform: str, title: str, url: str) -> bool:
        """Whether this rule applies to an analysed item."""
        if not self.enabled or not self.pattern:
            return False

        pattern = self.pattern.strip().casefold()
        if self.field == FIELD_CREATOR:
            # Exact, case-insensitive: "Studio Kern" should not match
            # "Studio Kernel Audio".
            return (creator or "").strip().casefold() == pattern
        if self.field == FIELD_PLATFORM:
            return (platform or "").strip().casefold() == pattern
        if self.field == FIELD_TITLE:
            return pattern in (title or "").casefold()
        if self.field == FIELD_URL:
            return pattern in (url or "").casefold()
        return False

    def describe(self) -> str:
        return f"{FIELD_LABELS.get(self.field, self.field)} “{self.pattern}” → {self.category}"

    def to_row(self) -> dict:
        return {
            "field": self.field,
            "pattern": self.pattern,
            "category": self.category,
            "enabled": int(bool(self.enabled)),
            "priority": int(self.priority),
            "times_applied": int(self.times_applied),
            "created_at": self.created_at or datetime.now().isoformat(timespec="seconds"),
        }

    @classmethod
    def from_row(cls, row) -> FilingRule:
        data = dict(row)
        return cls(
            id=data.get("id"),
            field=data.get("field") or FIELD_CREATOR,
            pattern=data.get("pattern") or "",
            category=data.get("category") or "",
            enabled=bool(data.get("enabled", 1)),
            priority=int(data.get("priority") or 100),
            times_applied=int(data.get("times_applied") or 0),
            created_at=data.get("created_at") or "",
        )


# --- Suggestions ----------------------------------------------------------

ORIGIN_RULE = "rule"
ORIGIN_CREATOR = "creator"
ORIGIN_PLATFORM = "platform"
ORIGIN_TITLE = "title"
ORIGIN_HEURISTIC = "heuristic"
ORIGIN_DEFAULT = "default"


@dataclass
class Suggestion:
    """Where Mediary thinks something goes, and why it thinks so."""

    category: str
    confidence: float = 0.0
    reason: str = ""
    origin: str = ORIGIN_DEFAULT
    rule_id: int | None = None

    @property
    def is_confident(self) -> bool:
        """Whether this is worth showing the user at all.

        Below the threshold the honest thing is to stay quiet and use the
        default: a hedged suggestion costs more attention than it saves.
        """
        return self.origin != ORIGIN_DEFAULT and self.confidence >= MIN_CONFIDENCE

    @property
    def source(self) -> str:
        """The provenance to record if this suggestion is taken."""
        if self.origin == ORIGIN_RULE:
            return SOURCE_RULE
        return SOURCE_SUGGESTED if self.is_confident else SOURCE_DEFAULT


#: Below this, say nothing.
MIN_CONFIDENCE = 0.55

#: Evidence needed before history counts as a pattern. One previous download is
#: a coincidence; suggesting off it is how the feature loses trust on day two.
MIN_HISTORY_SAMPLES = 2

#: Built-in heuristics never outrank real history, so their score is capped.
MAX_HEURISTIC_CONFIDENCE = 0.70
