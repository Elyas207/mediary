"""Working out where a download belongs.

A cascade, strongest evidence first. Each tier only speaks when everything above
it has nothing confident to say, and every answer carries the sentence that
justifies it - a suggestion the user cannot audit is one they cannot trust.

    1. Rules the user wrote          deterministic, always win
    2. What they did with this       creator, then platform, then title words
       creator/platform before
    3. Built-in heuristics           so day one is not silent
    4. The configured default        no claim, no explanation

Scope, deliberately: this decides an *organisational bucket* from the user's own
filing habits. It never touches licensing, which Mediary promises never to
infer. Nothing in this module reads or writes a licence field.
"""

from __future__ import annotations

import re

from app.models.category import (
    KIND_AUDIO,
    KIND_VIDEO,
    categories_for_kind,
)
from app.models.download import MediaInfo
from app.models.filing import (
    MAX_HEURISTIC_CONFIDENCE,
    MIN_HISTORY_SAMPLES,
    ORIGIN_CREATOR,
    ORIGIN_DEFAULT,
    ORIGIN_HEURISTIC,
    ORIGIN_PLATFORM,
    ORIGIN_RULE,
    ORIGIN_TITLE,
    FilingRule,
    Suggestion,
)
from app.utils.logging import get_logger

log = get_logger("filing")

# --- Cold-start knowledge -------------------------------------------------
#
# Enough to be useful on an empty library, never enough to override what the
# user has actually done. Vocabulary is seeded from the tag lists that already
# exist in models/category.py.

KEYWORDS: dict = {
    "Sound Effects": (
        "whoosh", "swoosh", "impact", "hit", "riser", "stinger", "transition",
        "boom", "braam", "glitch", "swipe", "clang", "explosion", "shatter",
        "sfx", "one shot", "oneshot", "sweep", "drone hit", "sub drop",
    ),
    "Foley": ("foley", "footstep", "footsteps", "cloth", "rustle", "handling"),
    "Ambience": (
        "ambience", "ambient bed", "room tone", "roomtone", "atmos",
        "atmosphere", "background noise", "soundscape", "field recording",
    ),
    "Voice": (
        "voiceover", "voice over", "narration", "narrator", "dialogue",
        "monologue", "spoken word", "audiobook", "podcast",
    ),
    "Music": (
        "music", "track", "song", "instrumental", "beat", "theme", "score",
        "soundtrack", "album", "remix", "lofi", "lo-fi",
    ),
    "Inspiration": (
        "reel", "edit", "showreel", "reference", "moodboard", "inspo",
        "inspiration", "cinematography", "colour grade", "color grade",
        "transitions edit", "montage", "b-roll", "broll",
    ),
}

#: Platforms whose content is overwhelmingly one thing.
PLATFORM_HINTS: dict = {
    "Instagram": "Inspiration",
    "TikTok": "Inspiration",
}

#: Audio shorter than this is almost never a piece of music.
SHORT_AUDIO_SECONDS = 45
#: Audio longer than this is almost never a one-shot effect.
LONG_AUDIO_SECONDS = 120

#: The title model needs a real corpus before its word associations mean much.
MIN_CORPUS_FOR_TITLES = 20


class FilingService:
    """Suggests a category, and turns a correction into a rule."""

    def __init__(self, library, settings=None) -> None:
        self._library = library
        self._settings = settings
        self._token_cache: dict = {}

    # ------------------------------------------------------------------
    # Suggesting
    # ------------------------------------------------------------------

    def suggest(
        self,
        info: MediaInfo,
        media_kind: str,
        *,
        default_category: str = "",
    ) -> Suggestion:
        """Where this item most likely belongs, and why."""
        candidates = self._candidates(media_kind)
        fallback = self._fallback(
            default_category, candidates, default=self._default_category()
        )

        try:
            for probe in (
                self._from_rules,
                self._from_creator,
                self._from_platform_history,
                self._from_title,
                self._from_heuristics,
            ):
                suggestion = probe(info, media_kind, candidates)
                if suggestion is not None and suggestion.is_confident:
                    return suggestion
        except Exception:  # noqa: BLE001 - a suggestion is never worth a crash
            log.exception("Filing suggestion failed; falling back to the default")

        return Suggestion(category=fallback, confidence=0.0, origin=ORIGIN_DEFAULT)

    def _default_category(self) -> str:
        if self._settings is not None:
            return getattr(self._settings, "default_category", "") or "Other"
        return "Other"

    @staticmethod
    def _fallback(preferred: str, candidates: list, default: str = "") -> str:
        """The default, unless this media kind has no such folder.

        A default of "Video" is meaningless for an audio download, and filing
        a WAV under Video would put it somewhere the user cannot find it.
        """
        wanted = preferred or default
        for name in candidates:
            if name.casefold() == wanted.casefold():
                return name
        return candidates[0] if candidates else (wanted or "Other")

    @staticmethod
    def _candidates(media_kind: str) -> list:
        """Only categories that make sense for this media kind.

        Without this a long podcast could be filed as Inspiration, which is a
        video bucket - the suggestion would be structurally impossible.
        """
        return list(categories_for_kind(media_kind or KIND_VIDEO))

    # -- Tier 1: rules ---------------------------------------------------

    def _from_rules(self, info: MediaInfo, media_kind: str, candidates: list):
        allowed = {name.casefold() for name in candidates}
        for rule in self._library.all_rules(enabled_only=True):
            if rule.category.casefold() not in allowed:
                # The rule was written about a different kind of media. Sending
                # a podcast to Inspiration because a video rule matched the same
                # creator is not what the user asked for.
                continue
            if rule.matches(
                creator=info.creator,
                platform=info.platform,
                title=info.title,
                url=info.url,
            ):
                return Suggestion(
                    category=rule.category,
                    confidence=1.0,
                    reason=f"Your rule: {rule.describe()}",
                    origin=ORIGIN_RULE,
                    rule_id=rule.id,
                )
        return None

    # -- Tier 2: history --------------------------------------------------

    def _from_creator(self, info: MediaInfo, media_kind: str, candidates: list):
        if not info.creator:
            return None

        # Same creator on the same platform is the strongest signal there is;
        # the same name elsewhere is good but not quite as certain.
        for platform, phrasing in ((info.platform, True), ("", False)):
            history = self._library.category_history(
                creator=info.creator, platform=platform, media_kind=media_kind
            )
            best = self._winner(history, candidates)
            if best is None:
                continue
            category, confidence, top_count, total = best
            where = f"from {info.creator}"
            if phrasing and info.platform:
                where = f"from {info.creator} on {info.platform}"
            return Suggestion(
                category=category,
                confidence=confidence,
                reason=f"{top_count} of {total} {where} went to {category}",
                origin=ORIGIN_CREATOR,
            )
        return None

    def _from_platform_history(self, info: MediaInfo, media_kind: str, candidates: list):
        if not info.platform:
            return None
        history = self._library.category_history(
            platform=info.platform, media_kind=media_kind
        )
        best = self._winner(history, candidates)
        if best is None:
            return None
        category, confidence, top_count, total = best
        # Platform alone is a weaker claim than a named creator.
        return Suggestion(
            category=category,
            confidence=confidence * 0.85,
            reason=f"{top_count} of {total} from {info.platform} went to {category}",
            origin=ORIGIN_PLATFORM,
        )

    @classmethod
    def _winner(cls, history: list, candidates: list):
        """Pick a category from weighted history, if the evidence supports one.

        Deliberate choices are consulted first. An item Mediary suggested and
        the user simply never corrected is not evidence that the suggestion was
        right, so it can support a decision but never make one on its own -
        without that, the suggester slowly ratifies its own guesses.
        """
        allowed = {name.casefold() for name in candidates}
        usable = [entry for entry in history if entry[0].casefold() in allowed]
        if not usable:
            return None

        deliberate = [entry for entry in usable if entry[3] > 0]
        if deliberate:
            decided = cls._decide(deliberate, index=3)
            if decided is not None:
                return decided
        return cls._decide(usable, index=2)

    @staticmethod
    def _decide(entries: list, *, index: int):
        """Weigh one pool of history. ``index`` selects which count to gate on."""
        total_raw = sum(entry[index] for entry in entries)
        if total_raw < MIN_HISTORY_SAMPLES:
            return None

        ranked = sorted(entries, key=lambda entry: entry[1], reverse=True)
        category, weight = ranked[0][0], ranked[0][1]
        total_weight = sum(entry[1] for entry in ranked)
        if total_weight <= 0:
            return None

        share = weight / total_weight
        if share < 0.6:
            return None

        confidence = (weight + 1.0) / (total_weight + len(ranked) + 1.0)
        # Report the same pool the decision was made from, so "3 of 4" always
        # refers to the items that actually decided it.
        return category, min(0.97, max(confidence, share * 0.9)), ranked[0][index], total_raw

    def _from_title(self, info: MediaInfo, media_kind: str, candidates: list):
        """Naive-Bayes-ish over title words the user has filed before."""
        tokens, totals, corpus = self._token_model(media_kind)
        if corpus < MIN_CORPUS_FOR_TITLES:
            return None

        from app.services.library_service import _tokenise

        words = _tokenise(info.title)
        if not words:
            return None

        allowed = [name for name in candidates if name in totals]
        if len(allowed) < 2:
            return None

        scores: dict = {}
        evidence: dict = {}
        for category in allowed:
            score = 0.0
            for word in words:
                bucket = tokens.get(word)
                if not bucket:
                    continue
                seen = bucket.get(category, 0.0)
                score += (seen + 0.5) / (totals[category] + 1.0)
                if seen and bucket.get(category, 0.0) == max(bucket.values()):
                    evidence.setdefault(category, set()).add(word)
            scores[category] = score

        ranked = sorted(scores.items(), key=lambda entry: entry[1], reverse=True)
        if len(ranked) < 2 or ranked[0][1] <= 0:
            return None

        top, runner_up = ranked[0], ranked[1]
        total = top[1] + runner_up[1]
        if total <= 0:
            return None
        confidence = top[1] / total
        if confidence < 0.65:
            return None

        words_used = sorted(evidence.get(top[0], []))[:2]
        if not words_used:
            return None
        quoted = " and ".join(f"“{word}”" for word in words_used)
        return Suggestion(
            category=top[0],
            confidence=min(0.85, confidence),
            reason=f"Titles with {quoted} usually go to {top[0]}",
            origin=ORIGIN_TITLE,
        )

    def _token_model(self, media_kind: str) -> tuple:
        cached = self._token_cache.get(media_kind)
        if cached is None:
            cached = self._library.title_token_counts(media_kind)
            self._token_cache[media_kind] = cached
        return cached

    def set_settings(self, settings) -> None:
        """Re-point at the live settings object after a reload."""
        self._settings = settings
        self.invalidate()

    def invalidate(self) -> None:
        """Drop the cached title model - call when the library changes."""
        self._token_cache.clear()

    # -- Tier 3: built-in heuristics --------------------------------------

    def _from_heuristics(self, info: MediaInfo, media_kind: str, candidates: list):
        scores: dict = {}
        reasons: dict = {}

        def add(category: str, amount: float, reason: str) -> None:
            if category not in candidates:
                return
            if amount > scores.get(category, 0.0):
                reasons[category] = reason
            scores[category] = scores.get(category, 0.0) + amount

        # Any one signal has to clear MIN_CONFIDENCE on its own, or the whole
        # cold-start tier is decorative: it would compute an answer and then
        # discard it for being too timid. Corroborating signals stack from
        # there, up to the heuristic ceiling.
        #
        # A word in the title is someone naming the thing. Length, platform and
        # orientation are inferences about it, so they score just below - a
        # 30-second file called "footsteps" is Foley, not a sound effect,
        # because one of those signals is a description and the other is a
        # guess about the description.
        keyword = 0.60
        structural = 0.56
        corroborating = 0.08

        haystack = f"{info.title} {info.description[:400]}".casefold()
        for category, words in KEYWORDS.items():
            for word in words:
                if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", haystack):
                    add(category, keyword, f"“{word}” in the title suggests {category}")
                    break

        if media_kind == KIND_AUDIO and info.duration:
            if info.duration <= SHORT_AUDIO_SECONDS:
                add(
                    "Sound Effects",
                    structural if "Sound Effects" not in scores else corroborating,
                    f"Short audio ({int(info.duration)}s) is usually a sound effect",
                )
            elif info.duration >= LONG_AUDIO_SECONDS:
                add(
                    "Music",
                    structural if "Music" not in scores else corroborating,
                    "Audio this long is usually music",
                )

        if media_kind == KIND_VIDEO:
            hinted = PLATFORM_HINTS.get(info.platform)
            if hinted:
                add(
                    hinted,
                    structural if hinted not in scores else corroborating,
                    f"{info.platform} clips usually go to {hinted}",
                )
            if self._is_portrait(info):
                add(
                    "Inspiration",
                    structural if "Inspiration" not in scores else corroborating,
                    "Vertical video is usually a reel",
                )

        if not scores:
            return None

        ranked = sorted(scores.items(), key=lambda entry: entry[1], reverse=True)
        category, score = ranked[0]
        if len(ranked) > 1 and ranked[1][1] >= score:
            # "Music impact track" reads equally as Music and Sound Effects.
            # Picking one by dictionary order and then explaining it would be
            # inventing a reason, so say nothing instead.
            return None

        return Suggestion(
            category=category,
            confidence=min(MAX_HEURISTIC_CONFIDENCE, score),
            reason=reasons.get(category, f"Looks like {category}"),
            origin=ORIGIN_HEURISTIC,
        )

    @staticmethod
    def _is_portrait(info: MediaInfo) -> bool:
        for fmt in info.formats:
            if fmt.has_video and fmt.width and fmt.height:
                return fmt.height > fmt.width
        return False

    # ------------------------------------------------------------------
    # Learning from a correction
    # ------------------------------------------------------------------

    def rule_offer(self, info: MediaInfo, category: str):
        """The rule worth offering after a manual correction, or ``None``.

        Prefers the creator, because that is what people actually mean when
        they say "always put these here". Falls back to the platform.
        """
        from app.models.filing import FIELD_CREATOR, FIELD_PLATFORM

        if info.creator:
            return FilingRule(field=FIELD_CREATOR, pattern=info.creator, category=category)
        if info.platform:
            return FilingRule(field=FIELD_PLATFORM, pattern=info.platform, category=category)
        return None

    def save_rule(self, rule: FilingRule) -> int:
        rule_id = self._library.save_rule(rule)
        self.invalidate()
        return rule_id

    def note_applied(self, suggestion: Suggestion) -> None:
        """Record that a rule actually fired, for the rules screen."""
        if suggestion.origin == ORIGIN_RULE and suggestion.rule_id:
            self._library.note_rule_applied(suggestion.rule_id)
