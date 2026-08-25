"""Smart filing: rules, learned history, cold-start heuristics and provenance.

The stakes here are trust. A wrong suggestion the user has to undo every time
is worse than no suggestion at all, so these tests care as much about when
Mediary stays quiet as about when it speaks up.
"""

from __future__ import annotations

import pytest

from app.models.download import FormatOption, MediaInfo
from app.models.filing import (
    FIELD_CREATOR,
    FIELD_PLATFORM,
    FIELD_TITLE,
    ORIGIN_DEFAULT,
    ORIGIN_RULE,
    SOURCE_DEFAULT,
    SOURCE_SUGGESTED,
    SOURCE_USER,
    FilingRule,
    source_weight,
)
from app.services.filing_service import FilingService


@pytest.fixture
def filing(library, settings):
    return FilingService(library, settings)


def video(**kwargs) -> MediaInfo:
    """A video item, with a real format so ``has_video`` is true."""
    data = {
        "url": "https://example.com/watch?v=1",
        "title": "Untitled",
        "formats": [
            FormatOption(
                format_id="1", ext="mp4", width=1920, height=1080,
                vcodec="h264", acodec="aac",
            )
        ],
    }
    data.update(kwargs)
    return MediaInfo(**data)


def audio(**kwargs) -> MediaInfo:
    data = {
        "url": "https://example.com/track/1",
        "title": "Untitled",
        "formats": [FormatOption(format_id="1", ext="mp3", acodec="mp3", abr=320)],
    }
    data.update(kwargs)
    return MediaInfo(**data)


class TestRules:
    """A rule is the user speaking directly, so it outranks everything."""

    def test_a_creator_rule_decides_the_category(self, filing, library):
        library.save_rule(
            FilingRule(field=FIELD_CREATOR, pattern="Studio Kern", category="Ambience")
        )
        suggestion = filing.suggest(audio(creator="Studio Kern"), "audio")
        assert suggestion.category == "Ambience"
        assert suggestion.origin == ORIGIN_RULE
        assert suggestion.confidence == 1.0

    def test_a_creator_rule_matches_whole_names_only(self, filing, library):
        """"Studio Kern" must not swallow "Studio Kernel Audio"."""
        library.save_rule(
            FilingRule(field=FIELD_CREATOR, pattern="Studio Kern", category="Ambience")
        )
        suggestion = filing.suggest(audio(creator="Studio Kernel Audio"), "audio")
        assert suggestion.category != "Ambience"

    def test_case_does_not_matter(self, filing, library):
        library.save_rule(
            FilingRule(field=FIELD_CREATOR, pattern="studio kern", category="Foley")
        )
        assert filing.suggest(audio(creator="STUDIO KERN"), "audio").category == "Foley"

    def test_a_title_rule_matches_a_substring(self, filing, library):
        library.save_rule(
            FilingRule(field=FIELD_TITLE, pattern="behind the scenes", category="Inspiration")
        )
        info = video(title="Alpine shoot - Behind The Scenes")
        assert filing.suggest(info, "video").category == "Inspiration"

    def test_a_disabled_rule_is_ignored(self, filing, library):
        rule_id = library.save_rule(
            FilingRule(field=FIELD_CREATOR, pattern="Studio Kern", category="Ambience")
        )
        library.set_rule_enabled(rule_id, False)
        filing.invalidate()
        assert filing.suggest(audio(creator="Studio Kern"), "audio").origin != ORIGIN_RULE

    def test_reteaching_the_same_match_updates_it(self, filing, library):
        """Two rules matching the same thing and disagreeing is not a state
        the user can reason about, so the newer intent replaces the older."""
        library.save_rule(
            FilingRule(field=FIELD_CREATOR, pattern="Studio Kern", category="Ambience")
        )
        library.save_rule(
            FilingRule(field=FIELD_CREATOR, pattern="Studio Kern", category="Foley")
        )
        rules = [r for r in library.all_rules() if r.pattern == "Studio Kern"]
        assert len(rules) == 1
        assert rules[0].category == "Foley"

    def test_a_rule_cannot_file_audio_somewhere_only_video_goes(self, filing, library):
        library.save_rule(
            FilingRule(field=FIELD_CREATOR, pattern="Studio Kern", category="Inspiration")
        )
        suggestion = filing.suggest(audio(creator="Studio Kern"), "audio")
        assert suggestion.category != "Inspiration"

    def test_a_rule_beats_a_strong_history(self, filing, library, make_item):
        for _ in range(8):
            library.add(
                make_item(creator="Studio Kern", category="Music",
                          media_kind="audio", category_source=SOURCE_USER)
            )
        library.save_rule(
            FilingRule(field=FIELD_CREATOR, pattern="Studio Kern", category="Foley")
        )
        filing.invalidate()
        suggestion = filing.suggest(audio(creator="Studio Kern"), "audio")
        assert suggestion.category == "Foley"
        assert suggestion.origin == ORIGIN_RULE


class TestLearnedHistory:
    """What the user has actually done outranks what Mediary guesses."""

    def test_a_consistent_creator_is_learned(self, filing, library, make_item):
        for _ in range(4):
            library.add(
                make_item(creator="Field Recordings Co", category="Ambience",
                          media_kind="audio", category_source=SOURCE_USER)
            )
        suggestion = filing.suggest(audio(creator="Field Recordings Co"), "audio")
        assert suggestion.category == "Ambience"
        assert suggestion.is_confident

    def test_one_example_is_not_a_pattern(self, filing, library, make_item):
        """A single download proves nothing, and guessing from it teaches the
        model its own guess."""
        library.add(
            make_item(creator="Field Recordings Co", category="Ambience",
                      media_kind="audio", category_source=SOURCE_USER)
        )
        suggestion = filing.suggest(audio(creator="Field Recordings Co"), "audio")
        assert suggestion.origin != "creator"

    def test_an_inconsistent_creator_teaches_nothing(self, filing, library, make_item):
        for category in ("Music", "Ambience", "Foley", "Voice"):
            library.add(
                make_item(creator="Mixed Bag", category=category,
                          media_kind="audio", category_source=SOURCE_USER)
            )
        suggestion = filing.suggest(audio(creator="Mixed Bag"), "audio")
        assert suggestion.origin != "creator"

    def test_history_beats_a_heuristic(self, filing, library, make_item):
        """"Whoosh" reads as a sound effect, but this user files them as Foley."""
        for _ in range(4):
            library.add(
                make_item(creator="Studio Kern", category="Foley",
                          media_kind="audio", category_source=SOURCE_USER)
            )
        suggestion = filing.suggest(
            audio(creator="Studio Kern", title="Metal whoosh 04"), "audio"
        )
        assert suggestion.category == "Foley"

    def test_deliberate_choices_outweigh_unchallenged_suggestions(
        self, filing, library, make_item
    ):
        """Otherwise Mediary would confirm its own guesses forever - two
        corrections must beat three suggestions the user simply never fixed."""
        for _ in range(3):
            library.add(
                make_item(creator="Loop House", category="Voice",
                          media_kind="audio", category_source=SOURCE_SUGGESTED)
            )
        for _ in range(2):
            library.add(
                make_item(creator="Loop House", category="Music",
                          media_kind="audio", category_source=SOURCE_USER)
            )
        suggestion = filing.suggest(audio(creator="Loop House"), "audio")
        assert suggestion.category == "Music"

    def test_a_user_choice_weighs_more_than_a_suggestion(self):
        assert source_weight(SOURCE_USER) > source_weight(SOURCE_SUGGESTED)
        assert source_weight(SOURCE_SUGGESTED) > source_weight(SOURCE_DEFAULT)


class TestColdStart:
    """With an empty library there is no history, so the words have to carry it."""

    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("Deep bass whoosh transition", "Sound Effects"),
            ("Gravel footsteps walking loop", "Foley"),
            ("Empty room tone, 3 minutes", "Ambience"),
            ("Male narration read, warm", "Voice"),
        ],
    )
    def test_audio_titles_suggest_a_category(self, filing, title, expected):
        suggestion = filing.suggest(audio(title=title, duration=30.0), "audio")
        assert suggestion.category == expected
        assert suggestion.is_confident

    def test_a_short_clip_reads_as_a_sound_effect(self, filing):
        suggestion = filing.suggest(audio(title="Untitled export", duration=3.0), "audio")
        assert suggestion.category == "Sound Effects"

    def test_a_long_clip_reads_as_music(self, filing):
        suggestion = filing.suggest(audio(title="Untitled export", duration=240.0), "audio")
        assert suggestion.category == "Music"

    def test_a_vertical_video_reads_as_inspiration(self, filing):
        info = video(
            title="Untitled",
            formats=[
                FormatOption(format_id="1", ext="mp4", width=1080, height=1920,
                             vcodec="h264", acodec="aac")
            ],
        )
        assert filing.suggest(info, "video").category == "Inspiration"

    def test_a_plain_video_gets_no_opinion(self, filing):
        """Nothing in the item points anywhere, so Mediary should not pretend."""
        suggestion = filing.suggest(video(title="Untitled"), "video")
        assert suggestion.origin == ORIGIN_DEFAULT
        assert not suggestion.is_confident

    def test_a_guess_never_sounds_certain(self, filing):
        suggestion = filing.suggest(audio(title="Whoosh impact hit sweep"), "audio")
        assert suggestion.confidence <= 0.70

    def test_the_default_is_used_when_nothing_is_known(self, filing):
        suggestion = filing.suggest(video(title="Untitled"), "video", default_category="Other")
        assert suggestion.category == "Other"


class TestSuggestionShape:
    """What the card needs in order to explain itself."""

    def test_every_confident_suggestion_gives_a_reason(self, filing, library):
        library.save_rule(
            FilingRule(field=FIELD_PLATFORM, pattern="Instagram", category="Inspiration")
        )
        suggestion = filing.suggest(video(platform="Instagram"), "video")
        assert suggestion.reason
        assert "Inspiration" in suggestion.reason

    def test_a_default_carries_no_provenance(self, filing):
        suggestion = filing.suggest(video(title="Untitled"), "video")
        assert suggestion.source == SOURCE_DEFAULT

    def test_a_suggestion_is_recorded_as_suggested(self, filing):
        suggestion = filing.suggest(audio(title="Whoosh transition"), "audio")
        assert suggestion.source == SOURCE_SUGGESTED


class TestRuleOffers:
    """Turning a correction into a rule."""

    def test_a_correction_offers_a_creator_rule(self, filing):
        offer = filing.rule_offer(video(creator="Studio Kern", platform="YouTube"), "Other")
        assert offer.field == FIELD_CREATOR
        assert offer.pattern == "Studio Kern"
        assert offer.category == "Other"

    def test_without_a_creator_it_falls_back_to_the_platform(self, filing):
        offer = filing.rule_offer(video(creator="", platform="Vimeo"), "Inspiration")
        assert offer.field == FIELD_PLATFORM
        assert offer.pattern == "Vimeo"

    def test_an_anonymous_item_offers_nothing(self, filing):
        assert filing.rule_offer(video(creator="", platform=""), "Other") is None

    def test_saving_an_offer_makes_it_stick(self, filing, library):
        offer = filing.rule_offer(audio(creator="Studio Kern"), "Foley")
        filing.save_rule(offer)
        assert filing.suggest(audio(creator="Studio Kern"), "audio").category == "Foley"

    def test_use_is_only_counted_when_asked(self, filing, library):
        rule_id = library.save_rule(
            FilingRule(field=FIELD_CREATOR, pattern="Studio Kern", category="Foley")
        )
        suggestion = filing.suggest(audio(creator="Studio Kern"), "audio")
        assert library.all_rules()[0].times_applied == 0
        filing.note_applied(suggestion)
        assert library.all_rules()[0].times_applied == 1
        assert library.all_rules()[0].id == rule_id


class TestSafety:
    """Filing is a convenience. It must never be able to break a download."""

    def test_a_broken_library_falls_back_to_the_default(self, settings):
        class Exploding:
            def __getattr__(self, name):
                def boom(*args, **kwargs):
                    raise RuntimeError("database is gone")

                return boom

        service = FilingService(Exploding(), settings)
        suggestion = service.suggest(video(title="Whatever"), "video", default_category="Video")
        assert suggestion.category == "Video"
        assert suggestion.origin == ORIGIN_DEFAULT

    def test_an_empty_item_is_handled(self, filing):
        suggestion = filing.suggest(MediaInfo(), "video", default_category="Video")
        assert suggestion.category == "Video"

    def test_an_unknown_kind_still_returns_something(self, filing):
        suggestion = filing.suggest(video(title="Untitled"), "", default_category="Other")
        assert suggestion.category


class TestAmbiguity:
    """When two readings are equally good, saying nothing is the honest answer."""

    def test_a_tied_guess_is_not_reported(self, filing):
        """"Music" and "impact" pull equally hard in opposite directions."""
        suggestion = filing.suggest(audio(title="Music impact track"), "audio")
        assert suggestion.origin == ORIGIN_DEFAULT

    def test_a_clear_winner_still_wins(self, filing):
        suggestion = filing.suggest(audio(title="Music impact track", duration=300.0), "audio")
        assert suggestion.category == "Music"
        assert suggestion.is_confident

    def test_a_named_thing_beats_an_inference_about_it(self, filing):
        """A 30-second file called "footsteps" is Foley. The length says
        "sound effect", but the title says what it actually is."""
        suggestion = filing.suggest(
            audio(title="Gravel footsteps walking loop", duration=30.0), "audio"
        )
        assert suggestion.category == "Foley"

    def test_an_inference_still_speaks_when_nothing_else_does(self, filing):
        suggestion = filing.suggest(audio(title="Export 004", duration=3.0), "audio")
        assert suggestion.category == "Sound Effects"
        assert suggestion.is_confident


class TestTheFallback:
    """Even the no-opinion answer has to name a folder that exists."""

    def test_a_video_default_is_not_used_for_audio(self, filing, settings):
        """The configured default is "Video". A WAV cannot live there."""
        suggestion = filing.suggest(audio(title="Export 004"), "audio")
        assert suggestion.category != "Video"
        assert suggestion.category in (
            "Music", "Sound Effects", "Voice", "Ambience", "Foley", "Other",
        )

    def test_a_usable_default_is_respected(self, filing):
        suggestion = filing.suggest(video(title="Untitled"), "video", default_category="Other")
        assert suggestion.category == "Other"
