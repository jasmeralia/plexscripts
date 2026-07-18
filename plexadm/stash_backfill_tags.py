from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from plexadm.cli import EXCLUDED_COMPOSITION_COLLECTIONS, EXCLUDED_HAIR_COLLECTIONS, dry_run_note
from plexadm.config import load_config
from plexadm.console import info, ok, warn
from plexadm.plex import PlexContext, add_items, reload_if_partial, remove_items
from plexadm.stash import StashClient
from plexadm.stash_reconcile import _collection_to_tag

log = logging.getLogger(__name__)

COMPOSITION_COLLECTIONS = frozenset(EXCLUDED_COMPOSITION_COLLECTIONS) | {"01: Category: Lesbian"}
HAIR_COLLECTIONS = frozenset(EXCLUDED_HAIR_COLLECTIONS)
HAIR_TAGS = frozenset(tag for collection in HAIR_COLLECTIONS if (tag := _collection_to_tag(collection)) is not None)

GROUP_SINGLE_FEMALE = {
    "Composition: Solo",
    "Composition: MF Only",
    "Composition: MMF",
    "Composition: Gangbang",
}
GROUP_MULTI_FEMALE_HEADCOUNT = {
    "Composition: FFM",
    "Composition: FFFM",
    "Composition: Reverse Gangbang",
    "Composition: FFF+",
}
GROUP_MULTI_FEMALE_ACTIVITY = {"Composition: Lesbian"}
COMPOSITION_TAGS = frozenset(GROUP_SINGLE_FEMALE | GROUP_MULTI_FEMALE_HEADCOUNT | GROUP_MULTI_FEMALE_ACTIVITY)


@dataclass
class SceneDecision:
    rating_key: str
    title: str
    file_paths: list[str]
    adds: list[str] = field(default_factory=list)
    remove_candidates: list[str] = field(default_factory=list)
    ambiguous_reason: str | None = None


def _tag_to_collection(tag_name: str) -> str:
    return f"01: {tag_name}"


def classify_scene(stash_tags: set[str], plex_tags: set[str]) -> SceneDecision | None:
    s = stash_tags & COMPOSITION_TAGS
    p = plex_tags & COMPOSITION_TAGS
    if not s:
        return None

    single = s & GROUP_SINGLE_FEMALE
    headcount = s & GROUP_MULTI_FEMALE_HEADCOUNT
    lesbian = s & GROUP_MULTI_FEMALE_ACTIVITY

    conflicts = []
    if len(single) > 1:
        conflicts.append(f"multiple single-female tags: {sorted(single)}")
    if len(headcount) > 1:
        conflicts.append(f"multiple multi-female headcount tags: {sorted(headcount)}")
    if single and (headcount or lesbian):
        conflicts.append(f"cross-axis: {sorted(single)} + {sorted(headcount | lesbian)}")

    if conflicts:
        return SceneDecision(rating_key="", title="", file_paths=[], ambiguous_reason="; ".join(conflicts))

    adds = sorted(s - p)

    if single:
        contradicting = GROUP_MULTI_FEMALE_HEADCOUNT | GROUP_MULTI_FEMALE_ACTIVITY | (GROUP_SINGLE_FEMALE - single)
    else:
        contradicting = set(GROUP_SINGLE_FEMALE)
        if headcount:
            contradicting |= GROUP_MULTI_FEMALE_HEADCOUNT - headcount

    remove_candidates = sorted(p & contradicting)
    if not adds and not remove_candidates:
        return None

    return SceneDecision(rating_key="", title="", file_paths=[], adds=adds, remove_candidates=remove_candidates)


def _stash_tags_in_scope(scene: dict[str, Any], scope: frozenset[str]) -> set[str]:
    return {str(tag["name"]) for tag in scene.get("tags") or [] if tag.get("name") and str(tag["name"]) in scope}


def _plex_tags_in_scope(video: Any, scope: frozenset[str]) -> set[str]:
    tags = {_collection_to_tag(str(collection)) for collection in getattr(video, "collections", None) or []}
    return {tag for tag in tags if tag in scope}


def _write_review(path: str | Path, entries: list[dict[str, Any]]) -> None:
    review_path = Path(path)
    review_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = [{"generated_at": generated_at, **entry} for entry in entries]
    with review_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")


def _escape_markdown_table_cell(value: object) -> str:
    return str(value).replace("|", "\\|")


def _tag_source(tag: dict[str, Any], stash_box_names: dict[str, str]) -> str:
    """Return where a tag came from: 'local' (no external link) or the stash-box name(s) it's linked to.

    A tag with no stash_ids is purely local to this Stash instance - that includes tags
    synced in from Plex via `plexadm stash sync-tags`, since Stash has no way to record
    that provenance beyond "not linked to an external stash-box". Falls back to the raw
    endpoint URL if a stash_id references a box that isn't in the currently configured list
    (e.g. a box that was since removed from Settings).
    """
    stash_ids = tag.get("stash_ids") or []
    if not stash_ids:
        return "local"
    sources = {
        stash_box_names.get(sid.get("endpoint", ""), sid.get("endpoint") or "unknown stash-box") for sid in stash_ids
    }
    return ", ".join(sorted(sources))


def _resolve_existing(name: str, existing_titles: set[str]) -> str | None:
    """Return `name` if it's currently a real Plex collection, or its renamed form if THAT is
    real instead (`rename_categories()` may have already renamed it) - or None if neither is.

    Every merge-phrase target in this module (_CATEGORY_MERGE_PHRASES etc.) is written using
    the pre-rename "01: Category: X" convention. Without this, the moment
    `rename_categories()` actually renames a collection, every merge phrase targeting its old
    name would silently stop firing, since that name no longer exists - this keeps them all
    working correctly whether or not the rename has actually happened yet, without needing
    every target string in this file updated in lockstep with each live rename. Case-sensitive,
    matching this module's existing merge-phrase convention (unlike the case-insensitive
    _has_existing_plex_match, which does its own equivalent lookup - see there for why).
    """
    if name in existing_titles:
        return name
    renamed = _EXISTING_CATEGORY_RENAMES.get(name)
    if renamed and renamed in existing_titles:
        return renamed
    return None


def _has_existing_plex_match(tag: dict[str, Any], existing_titles: set[str]) -> bool:
    """Check whether a Stash tag already corresponds to some existing Plex collection.

    The direct "01: <name>" derivation only produces a real title for tags already
    following the Category:/Hair: naming convention - that's the only prefix this
    tool's own backfill logic ever writes. A non-local, unprefixed tag (almost always
    a StashDB act/attribute tag, e.g. "Fingering") can still correspond to an existing
    "01: Category: Fingering" collection filed under a *different*, already-mapped
    Stash tag ("Category: Fingering") - reporting that as a gap would be misleading,
    since nothing is actually missing from Plex, it's just Stash carrying two tags
    for related concepts. Local tags are excluded from this broader check: they were
    either hand-created or synced in from Plex under whatever prefix family that
    collection actually used (often not "01:" at all, e.g. "00A: FAVORITES") - this
    check doesn't attempt to cover that separate, wider prefix-family mismatch.

    Comparison is case-insensitive: the real collection list is inconsistently cased
    ("01: Category: Cum On Ass" vs "01: Category: Cum on Body"), and a real Stash tag
    ("Cum on Hands") was found on a live run that only differed from its matching
    collection ("01: Category: Cum On Hands") by case - a case-sensitive comparison
    wrongly reported that as a gap.

    Also checks each "01: Category: X" candidate's renamed form (see _resolve_existing) -
    otherwise, the moment `rename_categories()` renames a collection, every Stash tag that
    used to match it directly would wrongly start reporting as an unmapped gap.
    """
    tag_name = str(tag["name"])
    existing_titles_lower = {title.lower() for title in existing_titles}
    renames_lower = {old.lower(): new.lower() for old, new in _EXISTING_CATEGORY_RENAMES.items()}

    def _matches(candidate_lower: str) -> bool:
        if candidate_lower in existing_titles_lower:
            return True
        renamed = renames_lower.get(candidate_lower)
        return renamed is not None and renamed in existing_titles_lower

    if _matches(_tag_to_collection(tag_name).lower()):
        return True
    is_local = not (tag.get("stash_ids") or [])
    if is_local or tag_name.startswith(("Category: ", "Hair: ")):
        return False
    return _matches(f"01: category: {tag_name}".lower()) or _matches(f"01: hair: {tag_name}".lower())


_HAIR_MERGE_KEYWORDS: dict[str, str] = {
    "black": "01: Hair: Black",
    "blonde": "01: Hair: Blonde",
    "blond": "01: Hair: Blonde",
    "blue": "01: Hair: Blue",
    "brunette": "01: Hair: Brunette",
    "brown": "01: Hair: Brunette",
    "green": "01: Hair: Green",
    "pink": "01: Hair: Pink",
    "purple": "01: Hair: Purple",
    "red": "01: Hair: Red",
    "silver": "01: Hair: Silver",
    "white": "01: Hair: White",
}

# "winner" (not "winning" - a different word/token) catches all the "Award Winner (AVN Award
# YYYY)" variants regardless of year in one go, without catching "Award Winning" (which wasn't
# asked to be excluded). Confirmed by direct user review of the live report.
_SKIP_MARKER_WORDS = {"4k", "8k", "1080p", "720p", "fps", "hdr", "vr", "available", "winner"}

# Generic body-type descriptors - not technical metadata like _SKIP_MARKER_WORDS, but equally
# not worth a dedicated collection: the current taxonomy has no body-build or hair-length axis,
# and these words show up fused into otherwise-unrelated tag names ("Medium Ass", "Athletic
# Woman", "Average Height Man", "Medium Hair"). Confirmed by direct user review of the live
# report, not guessed.
_SKIP_GENERIC_BODY_WORDS = {"athletic", "slim", "average", "medium"}

# Eye color - same "not a tracked attribute axis" spirit as the body words above, kept separate
# since it's specifically about eyes, not build. Word-based (not a curated per-color list like
# hair) since "eyes" doesn't otherwise appear in any current tag name outside the color variants
# ("Eye Contact", "Eye Makeup", "Eyebrow Piercing" are all different singular/compound words),
# so this is safe today and doesn't need updating for future colors. Confirmed by direct user
# review of the live report.
_SKIP_EYE_COLOR_WORDS = {"eyes"}

# Age references - the user doesn't want these tracked at all. Word-based since these terms
# (unlike generic "middle"/"young" alone, which could plausibly appear elsewhere) are safely
# specific to age brackets in the current tag set. Confirmed by direct user review.
_SKIP_AGE_WORDS = {"teen", "milf", "dilf", "young", "younger", "older", "experienced", "aged"}

# Whole-tag-name (not substring) skips: too broad to be a useful collection ("Cumshot",
# "Threesome" - the specific variants like "Massive Cumshot" or "Threesome (BBG)" are still
# useful and must NOT be caught by this), pure ethnicity/nationality descriptors the user
# doesn't want tracked, or metadata about the tagging process itself rather than the content
# ("Missing Performer (Male)", "Exclusive"). Confirmed by direct user review of the live report.
_SKIP_EXACT_TAG_NAMES = {
    "hardcore",
    "cumshot",
    "threesome",
    "professional production",
    "indoors",
    "european",
    "white woman",
    "bed",
    "russian",
    "gonzo",
    "missing performer (male)",
    "exclusive",
    "straight",
    # Furniture - the user doesn't care about tracking it as a collection. Exact-name only:
    # "Countertop" describes a specific setting, not bare furniture, and wasn't part of what was
    # confirmed. "Massage Table" is handled as a merge into Massage instead - see below.
    "bedroom",
    "chair",
    "couch",
    "table",
    "blanket",
    "ottoman",
    "desk",
    "lounger",
    # Ethnicity/nationality descriptors beyond the two the user actually tracks (Asian, Ebony -
    # see the "black"/"asian woman" merges below). "White Woman" already covered above;
    # "White Man" is the same case. Confirmed by direct user review of the live report.
    "white man",
    "latina woman",
    "latino man",
    "mixed race woman",
    "mixed race man",
    "middle eastern woman",
    "latin",
    "american",
    "american porn",
    "ukrainian",
    "czech",
    "spanish",
    "french",
    "hungarian",
    "british",
    "dutch",
    "romanian",
    "israeli",
    "brazilian",
    "canadian",
    "estonian",
    "finnish",
    "polish",
    "portuguese",
    "venezuelan",
    "italian",
    "german",
    # Confirmed by direct user review of the live report: not content the user is ever looking
    # to watch/browse by.
    "prolapse",
    "armpit fetish",
    "ass to mouth",
    # Every scene in this library is already explicit - tracking "nude" as a collection is
    # redundant. "Nude Stockings" (a stocking color/style) is a different, unrelated tag and
    # is unaffected since this is an exact whole-name match, not a substring.
    "nude",
    # Bare number+"+" age brackets - the "+" isn't alphanumeric so these don't tokenize into a
    # word _SKIP_AGE_WORDS could catch; exact-matched here instead.
    "18+",
    "20+",
    "30+",
    # "Drop licking, grinding, touching, and kissing variants" - foot/toe-related ones route to
    # Foot Fetish instead (see the merge phrases below); everything else is dropped outright.
    "licking",
    "ball licking",
    "breast licking",
    "grinding",
    "touching",
    "breast touching",
    "nipple touching",
    "kissing",
}

_HAIR_CONTEXT_WORDS = {"hair", "haired"}

# A curated subset of scripts/set_tags_based_on_title.sh's title -> collection keyword
# associations (already validated by hand against real content, just for title matching
# rather than Stash tag names). Only phrases specific/unambiguous enough to trust as a
# substring match against a short, curated Stash tag name are included here - excluded:
# bare 2-3 letter tokens ("BJ", "DP", "gg"), words already covered more precisely elsewhere
# ("throat"/"finger" alone risk over-matching more specific variants like "Anal Fingering",
# the same failure mode the hair-color heuristic had before requiring "hair" co-occurrence),
# and words the script itself maps to more than one target ("strap" -> both Sex Toys and
# Strap On, "fuck machine" -> both Fuck Machine and Sex Toys - ambiguous, left out).
_CATEGORY_MERGE_PHRASES: dict[str, str] = {
    "blackmail": "01: Category: Blackmail",
    "cheating": "01: Category: Cheating",
    "double anal": "01: Category: Double Anal",
    "double penetration": "01: Category: Double Penetration",
    "girlfriend experience": "01: Category: GFE",
    "goth": "01: Category: Goth",
    "hitachi": "01: Category: Sex Toys",
    "interview": "01: Category: Interview",
    "latex": "01: Category: Latex",
    "live stream": "01: Category: Live Stream",
    "livestream": "01: Category: Live Stream",
    "throatpie": "01: Category: Throatpie",
    "vibrator": "01: Category: Sex Toys",
    # Confirmed by the script's own explicit title-matching rule ("Red head"/"Redhead" ->
    # Hair: Red) rather than guessed - this is exactly the fused-compound case the whole-word
    # hair heuristic below deliberately does not catch on its own.
    "redhead": "01: Hair: Red",
    "red head": "01: Hair: Red",
    # Confirmed by direct user review of the live report, not sourced from the script.
    "pussy licking": "01: Category: Pussy Eating",
    "cum on pussy": "01: Category: Cum On Vagina",
    # BBG = Boy-Boy-Girl, the same composition already tracked as MMF.
    "threesome (bbg)": "01: Category: MMF",
    # GTT = Girl-Trans-Trans, the same composition already tracked as TTF.
    "threesome (gtt)": "01: Category: TTF",
    "twosome (trans-female)": "01: Category: TF Only",
    # Found via a systematic pass cross-referencing every real "01: Category:" collection
    # against the live Add-section list for differently-worded StashDB synonyms of the same
    # concept - not sourced from the script, confirmed by direct user review.
    "mouth creampie": "01: Category: Cum In Mouth",
    "throat creampie": "01: Category: Throatpie",
    "cum on asshole": "01: Category: Cum On Ass",
    "peeing": "01: Category: Pee",
    "no sex": "01: Category: Non-Sexual",
    "jerk off instruction": "01: Category: JOI",
    "behind the scenes": "01: Category: BTS",
    "nipple piercing": "01: Category: Pierced Nipples",
    "tongue piercing": "01: Category: Pierced Tongue",
    "pussy piercing": "01: Category: Pierced Vagina",
    # The user only cares about the coarse Fauxcest flag, not which specific step-relation is
    # involved - collapsing all of StashDB's finer-grained relation tags into it is intentional.
    "family roleplay": "01: Category: Fauxcest",
    "step dad": "01: Category: Fauxcest",
    "step daughter": "01: Category: Fauxcest",
    "step sister": "01: Category: Fauxcest",
    "step mother": "01: Category: Fauxcest",
    "step brother": "01: Category: Fauxcest",
    "step cousin": "01: Category: Fauxcest",
    "step siblings": "01: Category: Fauxcest",
    # "Teacher/Tutor" (see _EXISTING_CATEGORY_RENAMES) is meant to become "Teacher/Student" to
    # capture both nuances - these already belong there under the current name.
    "teacher": "01: Category: Teacher/Tutor",
    "teaching": "01: Category: Teacher/Tutor",
    "tutor": "01: Category: Teacher/Tutor",
    # Headcount above a threesome (excepting FFFM, which keeps its own category) collapses to
    # Orgy/Gangbang/Reverse Gangbang by gender ratio - the user's own classification rule.
    # Order matters: the specific parenthetical variants must be checked before any future bare
    # "foursome"/"sixsome" entry would be added, since phrase matching is substring-based and
    # first-match-wins - deliberately no bare "foursome"/"fivesome"/"sixsome" entry exists here,
    # so there's no such collision today, but keep new entries specific for the same reason.
    "foursome (bggg)": "01: Category: Reverse Gangbang",  # 1 male, 3 female
    "foursome (bbbg)": "01: Category: Gangbang",  # 3 male, 1 female
    "foursome (bbgg)": "01: Category: Orgy",  # balanced mixed group
    "fivesome (bbbgg)": "01: Category: Orgy",
    "sixsome (bbbbgg)": "01: Category: Orgy",
    "asian woman": "01: Category: Asian",
    "black woman": "01: Category: Ebony",
    # Position/qualifier-prefixed or -suffixed variants of an already-tracked act collapse into
    # it - the position/qualifier itself isn't a distinct tracked axis. Confirmed by direct user
    # review ("many of these are just '<adjective> <existing tag>'"): Blowjob, Rimming, Massage,
    # and 69 clusters below. Substring matching deliberately covers the "- POV" siblings of each
    # for free (e.g. "anal missionary" also matches "Anal Missionary - POV").
    "standing blowjob": "01: Category: Blowjob",
    "sloppy blowjob": "01: Category: Blowjob",
    "missionary blowjob": "01: Category: Blowjob",
    "cowgirl blowjob": "01: Category: Blowjob",
    "chipmunk blowjob": "01: Category: Blowjob",
    "head pushing blowjob": "01: Category: Blowjob",
    "hands-free blowjob": "01: Category: Blowjob",
    "inverted blowjob": "01: Category: Blowjob",
    "triple blowjob": "01: Category: Blowjob",
    "dildo blowjob": "01: Category: Blowjob",
    "side fuck blowjob": "01: Category: Blowjob",
    "spooning blowjob": "01: Category: Blowjob",
    "blowjob only": "01: Category: Blowjob",
    "blowjob - pov": "01: Category: Blowjob",
    "blowjob nose pinch": "01: Category: Blowjob",
    "ball sucking during blowjob": "01: Category: Blowjob",
    "dick licking": "01: Category: Blowjob",
    "rimming her": "01: Category: Rimming",
    "rimming him": "01: Category: Rimming",
    "rimming during sex": "01: Category: Rimming",
    "massage table": "01: Category: Massage",
    "massage parlor": "01: Category: Massage",
    "69 breast licking": "01: Category: 69",
    "standing 69": "01: Category: 69",
    "lesbian action": "01: Category: Lesbian",
    "lesbian character": "01: Category: Lesbian",
    "ass smacking": "01: Category: Spanking",
    "double blowjob": "01: Category: Double Blowjob",
    "double facial": "01: Category: Facial",
    "double vaginal penetration": "01: Category: Double Vaginal",
    "all anal": "01: Category: Anal",
    # "Anal X" where X isn't itself independently tracked - single-target merge into Anal.
    # "Anal Fingering"/"Anal Toys"/"Anal Fisting"/etc. are deliberately excluded here since they
    # already get a good, specific Activity/Prop suggestion instead - not part of what was
    # confirmed, and merging them here would only lose that specificity.
    "anal missionary": "01: Category: Anal",
    "anal gape": "01: Category: Anal",
    "anal reverse cowgirl": "01: Category: Anal",
    "anal doggy style": "01: Category: Anal",
    "anal cowgirl": "01: Category: Anal",
    "anal spooning": "01: Category: Anal",
    "anal side fuck": "01: Category: Anal",
    "anal bulldog": "01: Category: Anal",
    "anal full nelson": "01: Category: Anal",
    "anal orgasm": "01: Category: Anal",
    "anal lazy reverse cowgirl": "01: Category: Anal",
    "anal squatting reverse cowgirl": "01: Category: Anal",
    "anal loophole": "01: Category: Anal",
    "anal piledriver": "01: Category: Anal",
    "anal spit roast": "01: Category: Anal",
    "anal winking": "01: Category: Anal",
    "anal hooks": "01: Category: Anal",
    "anal stretching": "01: Category: Anal",
    # Foot/toe-related "licking" variant, carved out of the general licking drop below.
    "foot licking": "01: Category: Foot Fetish",
    # "Grinding on face is redundant with face sitting" - the user's own description.
    "grinding on face": "01: Category: Face Sitting",
    # "Pussy Spanking already exists" - corrects the earlier "Ass Smacking only" merge, which
    # missed that its Pussy-specific sibling has its own real collection to merge into instead
    # of falling back to the generic "smacking" Activity keyword.
    "pussy smacking": "01: Category: Pussy Spanking",
    # "Anal fingering during sex feels totally redundant with anal fingering" - "Anal Fingering"
    # itself isn't a real collection (it's only a suggested Activity name, not merged elsewhere
    # per its own good specificity) - forward-declared the same way as the Masturbation-related
    # entries above, so this activates once "01: Activity: Anal Fingering" is created.
    "anal fingering during sex": "01: Activity: Anal Fingering",
    # "Vaginal insertion is redundant with vaginal penetration" - same forward-declaration
    # pattern; neither is a real collection yet.
    "vaginal insertion": "01: Activity: Vaginal Penetration",
    # "Collapse Titjob with Tit Fucking" - a real, already-existing collection.
    "titjob": "01: Category: Tit Fucking",
}

# A tag that legitimately overlaps two existing collections at once (e.g. "Open Mouth Facial"
# is both a cum-in-mouth and a facial variant) rather than one - confirmed by direct user
# review of the live report. Requires every listed target to already exist, same as the
# single-target phrases above.
_MULTI_TARGET_MERGE_PHRASES: dict[str, list[str]] = {
    # Confirmed by direct user correction: FF Only is a subset of Female Only, not a separate
    # bucket - anything tagged FF Only also belongs in Female Only. Combined, not collapsed:
    # the dedicated "01: Composition: FF Only" suggested name (_SUGGESTED_NAME_OVERRIDES) is
    # unchanged, this just adds Female Only as a second required target.
    "twosome (lesbian)": ["01: Composition: FF Only", "01: Composition: Female Only"],
    # Confirmed by direct user correction (revising the earlier single-target Female Only call):
    # 3+ all-female headcounts route to all three of FFF+ (headcount), Female Only (umbrella),
    # and Orgy (group-sex descriptor) - "twosome" is deliberately excluded since 2 people isn't
    # an orgy.
    "foursome (lesbian)": ["01: Category: FFF+", "01: Composition: Female Only", "01: Category: Orgy"],
    "sixsome (lesbian)": ["01: Category: FFF+", "01: Composition: Female Only", "01: Category: Orgy"],
    "orgy (lesbian)": ["01: Category: FFF+", "01: Composition: Female Only", "01: Category: Orgy"],
    # Confirmed by direct user correction: this is two acts happening together, not just the
    # generic "pussy licking" -> Pussy Eating merge.
    "pussy licking doggy style": ["01: Category: Pussy Eating", "01: Activity: Doggy Style"],
    # Confirmed by direct user correction: these are activities (not the generic Prop "toy"
    # keyword bucket) - "Toy Masturbation" routes straight into the existing Masturbation
    # activity (no separate "Toy Masturbation" collection), "Toy Penetration" gets its own
    # activity. Both also need Sex Toys - see _SUGGESTED_NAME_OVERRIDES for the matching "add"
    # display-name overrides while these targets are still pending.
    "toy masturbation": ["01: Activity: Masturbation", "01: Prop: Sex Toys"],
    "toy penetration": ["01: Activity: Toy Penetration", "01: Prop: Sex Toys"],
    "open mouth facial": ["01: Category: Cum In Mouth", "01: Category: Facial"],
    # "Blowbang would be Gangbang+Blowjob and likely Orgy" - the user's own description.
    "blowbang": ["01: Category: Gangbang", "01: Category: Blowjob", "01: Category: Orgy"],
    "rimming (lesbian)": ["01: Category: Lesbian", "01: Category: Rimming"],
    "rimming during blowjob": ["01: Category: Rimming", "01: Category: Blowjob"],
    "anal prone bone": ["01: Category: Anal", "01: Category: Prone Bone"],
    # These two targets don't exist yet ("Masturbation" is itself only a suggested new
    # collection today - see the bare "Masturbation" Add row) - won't fire as a merge until it's
    # created, since both targets are required to exist. Forward-declared anyway so it activates
    # automatically on a future run rather than needing to be re-added later.
    "anal masturbation": ["01: Category: Anal", "01: Activity: Masturbation"],
    "self pussy fingering": ["01: Activity: Masturbation", "01: Category: Fingering"],
    # "Almost every POV should be split" (the his/hers gender-direction ones are the exception -
    # see _SUGGESTED_NAME_OVERRIDES). "01: Theme: POV" doesn't exist yet, so none of these fire
    # today - each forward-declares the split so it activates once POV is created. Order here
    # matters: the more specific "anal X - pov" entries must be listed (and therefore matched)
    # before their bare "X - pov" siblings, since phrase matching is substring-based and
    # first-match-wins within this dict - "cowgirl - pov" is itself a substring of "anal cowgirl
    # - pov" and of "reverse cowgirl - pov", so those must come first too.
    "anal cowgirl - pov": ["01: Category: Anal", "01: Theme: POV"],
    "anal doggy style - pov": ["01: Category: Anal", "01: Theme: POV"],
    "anal missionary - pov": ["01: Category: Anal", "01: Theme: POV"],
    "blowjob - pov": ["01: Category: Blowjob", "01: Theme: POV"],
    "reverse cowgirl - pov": ["01: Activity: Reverse Cowgirl", "01: Theme: POV"],
    "cowgirl - pov": ["01: Activity: Cowgirl", "01: Theme: POV"],
    "missionary - pov": ["01: Activity: Missionary", "01: Theme: POV"],
    "facial - pov": ["01: Category: Facial", "01: Theme: POV"],
    "handjob - pov": ["01: Category: Handjob", "01: Theme: POV"],
    "footjob - pov": ["01: Category: Footjob", "01: Theme: POV"],
    # Titjob collapses into the existing Tit Fucking collection (see _CATEGORY_MERGE_PHRASES) -
    # a real, already-existing target, so this one only depends on POV to activate.
    "titjob - pov": ["01: Category: Tit Fucking", "01: Theme: POV"],
    "doggy style - pov": ["01: Activity: Doggy Style", "01: Theme: POV"],
}

# Exact whole-tag-name (not substring) merges: "black" alone is too short/common a substring to
# match safely against tag names like "Black Hair (Female)" or "Black Stockings" - those are
# about hair color and clothing, not ethnicity, and must keep going through their own separate
# checks. Confirmed by direct user review: Ebony and Asian are the only two ethnicities tracked.
_EXACT_MATCH_MERGE_PHRASES: dict[str, str] = {
    "black": "01: Category: Ebony",
    # Bare "Foursome" (no gender-ratio qualifier) - exact match, not substring, so it doesn't
    # swallow the specific "Foursome (BBGG)"/"(BGGG)"/"(BBBG)"/"(Lesbian)" variants, which route
    # elsewhere. Confirmed by direct user request.
    "foursome": "01: Category: Orgy",
}

# Exact-tag-name overrides for the suggested "add" collection name, used when the generic
# keyword classifier would either pick the wrong bucket/wording or - for a bare "fuck" keyword -
# would be too broad to add safely (it would sweep in "Hard Fuck"/"Deep Fuck", which weren't
# confirmed). Checked first in _suggest_new_collection_name, before any keyword group.
_SUGGESTED_NAME_OVERRIDES: dict[str, str] = {
    # New Composition collections (not yet real Plex collections) for specific known StashDB
    # tags that would otherwise hit the generic "orgy"/"foursome" Composition keywords and
    # suggest "01: Composition: Foursome (Lesbian)" verbatim - technically not wrong, but the
    # user asked for these routed to new dedicated FF Only/Female Only collections instead.
    # "Leave Lesbian alone" - not expanding that collection's existing dual meaning.
    "twosome (lesbian)": "01: Composition: FF Only",
    "foursome (lesbian)": "01: Composition: Female Only",
    "sixsome (lesbian)": "01: Composition: Female Only",
    "orgy (lesbian)": "01: Composition: Female Only",
    # Confirmed by direct user correction: these are activities, not the generic Prop "toy"
    # keyword bucket - see _MULTI_TARGET_MERGE_PHRASES for the matching merge targets.
    "toy masturbation": "01: Activity: Masturbation",
    "toy penetration by partner": "01: Activity: Toy Penetration",
    # Respelled per direct user request ("facefuck (no space)").
    "face fuck": "01: Activity: Facefuck",
    "side fuck": "01: Activity: Side Fuck",
    # "Almost every POV should be split... the only exception would be POV: His vs POV: Hers" -
    # these three don't pair with a specific act, so they get their own dedicated collection
    # instead of a multi-target split. "POV: Mixed" is this tool's own extrapolation of the same
    # naming pattern for the one gender-direction tag that isn't strictly his/hers - flag if
    # that's not what was intended.
    "male - pov": "01: Theme: POV: His",
    "female - pov": "01: Theme: POV: Hers",
    "mixed - pov": "01: Theme: POV: Mixed",
}

# Confirmed by direct user request: "anal anything also needs the anal activity tag" - every
# tag with "anal" as a whole word also belongs in the base Anal collection, on top of whatever
# specific classification already applies (combined, not collapsed - same pattern as the FF
# Only/Female Only merge below). "Most of the props also need to be flagged with sex toys, too
# ... dildos, sybian, anything flagged as toys should [be] - clothing and generic objects
# don't": word-based rather than an exhaustive per-tag list so it also catches future StashDB
# toy tags automatically; clothing/generic-object tags naturally never contain these words.
_ANAL_TAGALONG_TARGET = "01: Category: Anal"
_TOY_TAGALONG_TARGET = "01: Prop: Sex Toys"
_TOY_TAGALONG_WORDS = frozenset({"dildo", "toy", "toys", "sybian"})


def _tagalong_targets(tag_name: str) -> list[str]:
    """Extra collection(s) a tag should *also* land in, beyond its normal classification."""
    words = set(re.findall(r"[a-z0-9]+", tag_name.lower()))
    extra: list[str] = []
    if "anal" in words:
        extra.append(_ANAL_TAGALONG_TARGET)
    if words & _TOY_TAGALONG_WORDS:
        extra.append(_TOY_TAGALONG_TARGET)
    return extra


def _with_tagalong(tag_name: str, targets: list[str]) -> list[str]:
    combined = list(targets)
    for extra in _tagalong_targets(tag_name):
        if extra not in combined:
            combined.append(extra)
    return combined


def _suggested_action(tag_name: str, existing_titles: set[str]) -> str:
    """Heuristic-only suggestion for an unmapped tag: 'add', 'merge -> <collection>', or 'skip'.

    A starting point for human review, not a decision.

    Skip signals, checked first: an exact (whole tag name, not substring) match against
    `_SKIP_EXACT_TAG_NAMES`, or a whole word from `_SKIP_MARKER_WORDS`/`_SKIP_GENERIC_BODY_WORDS`.
    Exact-name matching for the former is deliberate - "Cumshot" alone is too broad to be a
    useful collection, but "Massive Cumshot" and "Threesome (BBG)" are specific enough to keep,
    so a substring match would wrongly swallow those too.

    Merge signals, all requiring every target collection to actually exist already:
    1. `_MULTI_TARGET_MERGE_PHRASES` for a tag that legitimately spans more than one existing
       collection at once (e.g. "Open Mouth Facial" -> both Cum In Mouth and Facial).
    2. A curated phrase from `_CATEGORY_MERGE_PHRASES` (sourced from
       scripts/set_tags_based_on_title.sh's own already-validated keyword associations, plus
       entries confirmed by direct user review of the live report) appearing anywhere in the
       tag name.
    3. A hair-color keyword AND the word "hair"/"haired" both appearing as whole, space/
       punctuation-delimited words - not just the color word alone. Color words alone are
       not a reliable signal: verified against this tool's real, live-data test run that a
       color-word-only match produces mostly false positives ("White Woman", "Blue Eyes",
       "Brown Eyes", "Pink Labia", "Red Lipstick", ... - none of those are about hair), while
       every tag that also contains "hair" was a correct match ("Brown Hair (Male)", "Blond
       Hair (Male)", "Platinum Blond Hair", ...). Requiring both words present (not
       necessarily adjacent, since these tag names are short enough that co-occurrence alone
       is already precise) eliminated every false positive in that run while keeping every
       true positive. Composition-side merges are deliberately not attempted for the whole-
       word path - those terms (MMF, FFM, FFFM, ...) are short/abbreviation-heavy enough that
       keyword matching would be too noisy to trust even as a suggestion; a human scanning
       the raw list is more reliable there.
    """
    lower_name = tag_name.lower()
    words = set(re.findall(r"[a-z0-9]+", lower_name))
    if lower_name in _SKIP_EXACT_TAG_NAMES or words & (
        _SKIP_MARKER_WORDS | _SKIP_GENERIC_BODY_WORDS | _SKIP_EYE_COLOR_WORDS | _SKIP_AGE_WORDS
    ):
        return "skip"
    exact_target = _EXACT_MATCH_MERGE_PHRASES.get(lower_name)
    if exact_target:
        full_targets = _with_tagalong(tag_name, [exact_target])
        resolved_targets = [_resolve_existing(target, existing_titles) for target in full_targets]
        if all(resolved_targets):
            return f"merge -> {' + '.join(resolved_targets)}"  # type: ignore[arg-type]
    for phrase, targets in _MULTI_TARGET_MERGE_PHRASES.items():
        if phrase in lower_name:
            full_targets = _with_tagalong(tag_name, targets)
            resolved_targets = [_resolve_existing(target, existing_titles) for target in full_targets]
            if all(resolved_targets):
                return f"merge -> {' + '.join(resolved_targets)}"  # type: ignore[arg-type]
    for phrase, target in _CATEGORY_MERGE_PHRASES.items():
        if phrase in lower_name:
            full_targets = _with_tagalong(tag_name, [target])
            resolved_targets = [_resolve_existing(t, existing_titles) for t in full_targets]
            if all(resolved_targets):
                return f"merge -> {' + '.join(resolved_targets)}"  # type: ignore[arg-type]
    if words & _HAIR_CONTEXT_WORDS:
        for word in words:
            hair_target = _HAIR_MERGE_KEYWORDS.get(word)
            if hair_target and hair_target in existing_titles:
                return f"merge -> {hair_target}"
    # No explicit merge rule matched - a tag-along-eligible tag (anal/toy) still needs tracking:
    # treat its own generic suggested name as an implicit single-target rule so it stays "add"
    # until real, then correctly upgrades to a full multi-target merge, same as every other
    # forward-declared rule above.
    tagalong = _tagalong_targets(tag_name)
    if tagalong:
        full_targets = _with_tagalong(tag_name, [_suggest_new_collection_name(tag_name)])
        resolved_targets = [_resolve_existing(t, existing_titles) for t in full_targets]
        if all(resolved_targets):
            return f"merge -> {' + '.join(resolved_targets)}"  # type: ignore[arg-type]
    return "add"


def _potential_merge_targets(tag_name: str) -> list[str] | None:
    """Return the merge target(s) a currently-"add" tag would get once every referenced
    collection exists, ignoring the existence gate `_suggested_action` applies.

    Mirrors `_suggested_action`'s matching order (skip check, then exact/multi/single-target
    phrases, then the tag-along-only fallback) minus the `in existing_titles` checks, so it also
    surfaces forward-declared rules that haven't activated yet. Used to build the report's
    "Pending Collections" section - "do track the suggested adds now even if not present", per
    direct user request. Deliberately doesn't include the hair-color path: that one is about
    existing hair collections specifically and this tool never proposes creating a new one (see
    `_suggest_new_collection_name`).
    """
    lower_name = tag_name.lower()
    words = set(re.findall(r"[a-z0-9]+", lower_name))
    if lower_name in _SKIP_EXACT_TAG_NAMES or words & (
        _SKIP_MARKER_WORDS | _SKIP_GENERIC_BODY_WORDS | _SKIP_EYE_COLOR_WORDS | _SKIP_AGE_WORDS
    ):
        return None
    exact_target = _EXACT_MATCH_MERGE_PHRASES.get(lower_name)
    if exact_target:
        return _with_tagalong(tag_name, [exact_target])
    for phrase, targets in _MULTI_TARGET_MERGE_PHRASES.items():
        if phrase in lower_name:
            return _with_tagalong(tag_name, targets)
    for phrase, target in _CATEGORY_MERGE_PHRASES.items():
        if phrase in lower_name:
            return _with_tagalong(tag_name, [target])
    tagalong = _tagalong_targets(tag_name)
    if tagalong:
        return _with_tagalong(tag_name, [_suggest_new_collection_name(tag_name)])
    return None


_CUMSHOT_KEYWORDS = frozenset({"cum", "creampie", "bukkake", "facial", "swallow", "throatpie", "cumshot"})
_COMPOSITION_KEYWORDS = frozenset(
    {"solo", "gangbang", "orgy", "threesome", "foursome", "mmf", "ffm", "fffm", "fff", "trio"}
)
_PROP_KEYWORDS = frozenset(
    {
        "toy",
        "toys",
        "vibrator",
        "dildo",
        "plug",
        "machine",
        "clamp",
        "clamps",
        "blindfold",
        "rope",
        "restraint",
        "restraints",
        "wax",
        "glory",
        "hole",
        # Confirmed by direct user review of the live report: physical objects/gear and worn
        # fetish attire, matching the existing "01: Category: Latex" -> "01: Prop: Latex"
        # precedent. Deliberately excludes furniture/setting words ("bed", "chair", "couch",
        # "table") and broad genre words ("bondage") - those read more like a location or theme
        # than a discrete prop and weren't part of what was confirmed.
        "lingerie",
        "stockings",
        "stocking",
        "bodystocking",
        "heels",
        "heel",
        "heeled",
        "handcuffs",
        "handcuff",
        "leash",
        "mirror",
        "wand",
        "wands",
        "whip",
        "cane",
        "canes",
        "flogger",
        "mask",
        "sybian",
        "gag",
        "gags",
        # Confirmed by direct user correction (Plaid Miniskirt is a Prop, not a Theme) - worn
        # clothing item, same reasoning as the fetish attire above.
        "skirt",
        "miniskirt",
    }
)
_ACTIVITY_KEYWORDS = frozenset(
    {
        "anal",
        "blowjob",
        "deepthroat",
        "fingering",
        "fisting",
        "handjob",
        "footjob",
        "rimming",
        "spanking",
        "squirting",
        "squirt",
        "massage",
        "choking",
        "eating",
        "penetration",
        "throating",
        "throated",
        "tribbing",
        "slapping",
        "sitting",
        # Confirmed by direct user review of the live report: verb/gerund-shaped act tags that
        # were falling to the "01: Category:" fallback and belong here instead (e.g. "Kissing").
        # "licking"/"grinding"/"touching"/"kissing" were removed from this set in a later round -
        # see _SKIP_EXACT_TAG_NAMES, those are dropped outright now instead (except foot/toe-
        # related and "Grinding on Face", which merge into Foot Fetish/Face Sitting).
        "riding",
        "sucking",
        "gagging",
        "rubbing",
        "spitting",
        "fondling",
        "humping",
        "smacking",
        "grabbing",
        "squeezing",
        "pinching",
        "pulling",
        "insertion",
        "worship",
        "tickling",
        "flashing",
        "twerking",
        "gripping",
        # Confirmed by direct user correction: Daisy Chain is an activity, not a composition
        # (moved out of _COMPOSITION_KEYWORDS).
        "daisy",
        "chain",
        # Confirmed by direct user correction: named positions are activities after all,
        # reversing the earlier "named positions stay Category" call. "Face Fuck" and "Side
        # Fuck" are handled via _SUGGESTED_NAME_OVERRIDES instead of a bare "fuck" keyword here
        # - "fuck" alone would sweep in "Hard Fuck"/"Deep Fuck", which weren't part of this.
        "cowgirl",
        "missionary",
        "doggy",
        # "titjob" deliberately not a keyword here - it collapses into the existing Tit
        # Fucking collection instead, via _CATEGORY_MERGE_PHRASES.
        # Confirmed by direct user correction: bare "Masturbation" was falling to the "01:
        # Category:" fallback (no keyword matched it) rather than a deliberate classification -
        # it's an activity, and _CATEGORY_MERGE_PHRASES' "anal masturbation"/"self pussy
        # fingering" targets were updated to match.
        "masturbation",
    }
)
_THEME_KEYWORDS = frozenset(
    {
        "gfe",
        "cheating",
        "interview",
        "teacher",
        "blackmail",
        "goth",
        "cosplay",
        "hentai",
        "fetish",
        "stream",
        "roleplay",
        "outdoor",
        "outdoors",
        "public",
        "voyeur",
        "voyeurism",
        "cuckold",
        "cuckolding",
        "custom",
        "classic",
    }
)

# Performer/content attributes (ethnicity, piercings, skin tone, body art) - a descriptive
# property of the content rather than an act, object, or theme. Confirmed by direct user
# request ("piercings, asian/ebony, porcelain skin, etc."). "asian"/"ebony" aren't included here
# since those are handled by the dedicated merge phrases above (targeting the two real
# collections directly) - every other ethnicity/nationality word is skipped outright instead of
# reaching this classifier at all.
_ATTRIBUTES_KEYWORDS = frozenset(
    {
        "piercing",
        "piercings",
        "skin",
        "tattoo",
        "tattoos",
        "tattooed",
        # Confirmed by direct user request: "Hairless Pussy is an attribute, as are natural
        # tits, big tits, hairy pussy, big dick, long hair."
        "hair",
        "hairless",
        "hairy",
        "tits",
        "dick",
    }
)

# Checked in this order - some words plausibly fit more than one bucket (e.g. "throatpie" is
# cum-related first, act-related second), so priority matters. Attributes is checked last since
# it's the most general/descriptive bucket. "01: Hair:" is deliberately not a target here: a tag
# reaching this function had no merge match against any existing hair collection, and inventing
# a 12th hair-color collection from a keyword guess is a bigger claim than this heuristic should
# make - left as a plain "add" with no special prefix instead.
_NEW_PREFIX_KEYWORD_GROUPS: list[tuple[str, frozenset[str]]] = [
    ("01: Cumshot: ", _CUMSHOT_KEYWORDS),
    ("01: Composition: ", _COMPOSITION_KEYWORDS),
    ("01: Prop: ", _PROP_KEYWORDS),
    ("01: Activity: ", _ACTIVITY_KEYWORDS),
    ("01: Theme: ", _THEME_KEYWORDS),
    ("01: Attributes: ", _ATTRIBUTES_KEYWORDS),
]


_BREASTS_WORD_PATTERN = re.compile(r"\bbreasts\b", re.IGNORECASE)
_BREAST_WORD_PATTERN = re.compile(r"\bbreast\b", re.IGNORECASE)


def _normalize_wording(tag_name: str) -> str:
    """Use "tits" consistently rather than mixing it with "breast(s)" in suggested names.

    Confirmed by direct user request ("mixing the two looks awkward") - "tits" is the more
    prevalent wording in this taxonomy already (Tit Fucking, Big Tits, ...). Only affects the
    suggested display name, not classification - no keyword currently depends on "breast".
    """
    tag_name = _BREASTS_WORD_PATTERN.sub("Tits", tag_name)
    return _BREAST_WORD_PATTERN.sub("Tit", tag_name)


def _suggest_new_collection_name(tag_name: str) -> str:
    """Suggest a "01: <Prefix>: <name>" collection name for a tag with no existing match.

    Heuristic keyword classification into the emerging Cumshot/Composition/Prop/Activity/Theme/
    Attributes taxonomy, checked in that priority order. Falls back to "01: Category: <name>" -
    the existing, safe default - when no keyword matches, rather than guessing into a specific
    new bucket without a real signal. The tag's own name (after `_normalize_wording`) is used
    verbatim as the suggested collection's suffix.

    `_SUGGESTED_NAME_OVERRIDES` is checked first: without it, a tag like "Foursome (Lesbian)"
    would hit the generic "orgy"/"foursome" Composition keywords below and suggest "01:
    Composition: Foursome (Lesbian)" verbatim - technically not wrong, but the user asked for
    these routed elsewhere (new dedicated collections, a respelling, or a different bucket).
    """
    tag_name = _normalize_wording(tag_name)
    override = _SUGGESTED_NAME_OVERRIDES.get(tag_name.lower())
    if override:
        return override
    words = set(re.findall(r"[a-z0-9]+", tag_name.lower()))
    for prefix, keywords in _NEW_PREFIX_KEYWORD_GROUPS:
        if words & keywords:
            return f"{prefix}{tag_name}"
    return f"01: Category: {tag_name}"


# Hand-classified, not keyword-guessed: the real "01: Category:" list is a small, fixed,
# fully-known set (106 collections as of 2026-07-16), so every entry got individual judgment
# rather than running it through the same heuristic used for the open-ended Stash tag list.
# Genuinely ambiguous calls (documented inline) and collections that don't cleanly fit any of
# Cumshot/Composition/Prop/Activity/Theme at all (ethnicity, body modification, skin
# complexion, video format, and one likely-mislabeled studio name) are deliberately left out of
# this table entirely rather than forced into a bucket - see the report's own notes section for
# that residual list. "Lesbian" is included despite its known dual composition/activity meaning
# (see plans discussion) - this table doesn't attempt to resolve that split, only the rename.
_EXISTING_CATEGORY_RENAMES: dict[str, str] = {
    "01: Category: 69": "01: Activity: 69",
    "01: Category: Anal": "01: Activity: Anal",
    "01: Category: Anal Creampie": "01: Cumshot: Anal Creampie",
    "01: Category: BTS": "01: Theme: BTS",
    "01: Category: Blackmail": "01: Theme: Blackmail",
    "01: Category: Blindfold": "01: Prop: Blindfold",
    "01: Category: Blowjob": "01: Activity: Blowjob",
    "01: Category: Bukkake": "01: Cumshot: Bukkake",
    "01: Category: Butt Plug": "01: Prop: Butt Plug",
    "01: Category: Cheating": "01: Theme: Cheating",
    "01: Category: Choking": "01: Activity: Choking",
    "01: Category: Classic": "01: Theme: Classic",
    "01: Category: Completely Throated": "01: Activity: Completely Throated",
    "01: Category: Cosplay": "01: Theme: Cosplay",
    "01: Category: Cuckolding": "01: Theme: Cuckolding",
    "01: Category: Cum In Mouth": "01: Cumshot: Cum In Mouth",
    "01: Category: Cum On Ass": "01: Cumshot: Cum On Ass",
    "01: Category: Cum On Hands": "01: Cumshot: Cum On Hands",
    "01: Category: Cum On Self": "01: Cumshot: Cum On Self",
    "01: Category: Cum On Tits": "01: Cumshot: Cum On Tits",
    "01: Category: Cum On Vagina": "01: Cumshot: Cum On Vagina",
    "01: Category: Cum Play": "01: Cumshot: Cum Play",
    # Confirmed by direct user correction: Cum Swapping is an activity, not a cumshot.
    "01: Category: Cum Swapping": "01: Activity: Cum Swapping",
    # "Current" preserves the real (inconsistently-cased) Plex title; "Suggested" fixes the
    # casing to match the majority "Cum On X" convention used everywhere else in this cluster -
    # confirmed by direct user request for case consistency across the Cumshot group.
    "01: Category: Cum on Body": "01: Cumshot: Cum On Body",
    "01: Category: Cum on Feet": "01: Cumshot: Cum On Feet",
    "01: Category: Cum on Stomach": "01: Cumshot: Cum On Stomach",
    "01: Category: Custom": "01: Theme: Custom",
    # Confirmed by direct user correction: Daisy Chain is an activity, not a composition.
    "01: Category: Daisy Chain": "01: Activity: Daisy Chain",
    "01: Category: Deepthroat": "01: Activity: Deepthroat",
    # Double Anal/Blowjob/Penetration/Vaginal describe an act performed on/by a specific
    # partner count, closer to Composition than plain Activity - but none of these are in the
    # existing EXCLUDED_COMPOSITION_COLLECTIONS grouping the codebase already uses elsewhere,
    # so Activity was chosen to match that existing precedent rather than override it. Worth a
    # second look during the actual migration.
    "01: Category: Double Anal": "01: Activity: Double Anal",
    "01: Category: Double Blowjob": "01: Activity: Double Blowjob",
    "01: Category: Double Penetration": "01: Activity: Double Penetration",
    "01: Category: Double Vaginal": "01: Activity: Double Vaginal",
    "01: Category: Extreme Throating": "01: Activity: Extreme Throating",
    "01: Category: FFF+": "01: Composition: FFF+",
    "01: Category: FFFM": "01: Composition: FFFM",
    "01: Category: FFM": "01: Composition: FFM",
    "01: Category: FFT": "01: Composition: FFT",
    "01: Category: Face Sitting": "01: Activity: Face Sitting",
    "01: Category: Face Slapping": "01: Activity: Face Slapping",
    "01: Category: Facial": "01: Cumshot: Facial",
    "01: Category: Fauxcest": "01: Theme: Fauxcest",
    "01: Category: Fetish": "01: Theme: Fetish",
    "01: Category: Fingering": "01: Activity: Fingering",
    "01: Category: Fisting": "01: Activity: Fisting",
    "01: Category: Foot Fetish": "01: Theme: Foot Fetish",
    "01: Category: Footjob": "01: Activity: Footjob",
    "01: Category: Fuck Machine": "01: Prop: Fuck Machine",
    "01: Category: GFE": "01: Theme: GFE",
    "01: Category: Gangbang": "01: Composition: Gangbang",
    "01: Category: Glory Hole": "01: Prop: Glory Hole",
    "01: Category: Goth": "01: Theme: Goth",
    "01: Category: Handjob": "01: Activity: Handjob",
    "01: Category: Hentai": "01: Theme: Hentai",
    # Prop (the wax itself) rather than Activity (the act of applying it) - a judgment call,
    # same reasoning applies to Oil below.
    "01: Category: Hot Wax": "01: Prop: Hot Wax",
    "01: Category: Interview": "01: Theme: Interview",
    "01: Category: JOI": "01: Theme: JOI",
    "01: Category: Latex": "01: Prop: Latex",
    "01: Category: Lesbian": "01: Composition: Lesbian",
    "01: Category: Live Stream": "01: Theme: Live Stream",
    "01: Category: Live Stream Clip": "01: Theme: Live Stream Clip",
    "01: Category: MF Only": "01: Composition: MF Only",
    "01: Category: MMF": "01: Composition: MMF",
    "01: Category: Massage": "01: Activity: Massage",
    "01: Category: Nipple Clamps": "01: Prop: Nipple Clamps",
    "01: Category: Nipple Play": "01: Activity: Nipple Play",
    "01: Category: Oil": "01: Prop: Oil",
    "01: Category: Orgy": "01: Composition: Orgy",
    "01: Category: Outdoors": "01: Theme: Outdoors",
    "01: Category: Painal": "01: Activity: Painal",
    "01: Category: Panty Stuffing": "01: Prop: Panty Stuffing",
    "01: Category: Pee": "01: Activity: Pee",
    # Confirmed by direct user correction: this is a worn item, i.e. a Prop, not a Theme.
    "01: Category: Plaid Miniskirt": "01: Prop: Plaid Miniskirt",
    "01: Category: Prone Bone": "01: Activity: Prone Bone",
    "01: Category: Pussy Eating": "01: Activity: Pussy Eating",
    "01: Category: Pussy Spanking": "01: Activity: Pussy Spanking",
    "01: Category: Reverse Gangbang": "01: Composition: Reverse Gangbang",
    "01: Category: Rimming": "01: Activity: Rimming",
    "01: Category: Sex Toys": "01: Prop: Sex Toys",
    "01: Category: Social Event": "01: Theme: Social Event",
    "01: Category: Solo": "01: Composition: Solo",
    "01: Category: Spanking": "01: Activity: Spanking",
    "01: Category: Squirting": "01: Activity: Squirting",
    "01: Category: Strap On": "01: Prop: Strap On",
    "01: Category: Striptease": "01: Activity: Striptease",
    "01: Category: TF Only": "01: Composition: TF Only",
    "01: Category: TTF": "01: Composition: TTF",
    # Renamed (not just re-prefixed) per direct user request, to capture both nuances.
    "01: Category: Teacher/Tutor": "01: Theme: Teacher/Student",
    "01: Category: Throatpie": "01: Cumshot: Throatpie",
    "01: Category: Tit Fucking": "01: Activity: Tit Fucking",
    "01: Category: Tribbing": "01: Activity: Tribbing",
    "01: Category: Triple Anal": "01: Activity: Triple Anal",
    "01: Category: Vaginal Creampie": "01: Cumshot: Vaginal Creampie",
    "01: Category: Voyeurism": "01: Theme: Voyeurism",
    # Confirmed by direct user correction: Water is a Prop, not an Activity.
    "01: Category: Water": "01: Prop: Water",
    # New "01: Attributes:" bucket for performer/content attributes that don't fit any
    # act/object/theme bucket - confirmed by direct user request ("piercings, asian/ebony,
    # porcelain skin, etc.").
    "01: Category: Asian": "01: Attributes: Asian",
    "01: Category: Ebony": "01: Attributes: Ebony",
    "01: Category: Porcelain Skin": "01: Attributes: Porcelain Skin",
    "01: Category: Pierced Nipples": "01: Attributes: Pierced Nipples",
    "01: Category: Pierced Tongue": "01: Attributes: Pierced Tongue",
    "01: Category: Pierced Vagina": "01: Attributes: Pierced Vagina",
    # Confirmed by direct user correction: Trans MTF is a performer attribute, not a
    # composition axis - no longer in EXCLUDED_COMPOSITION_COLLECTIONS, so this rename runs
    # through the normal (non-composition) path.
    "01: Category: Trans MTF": "01: Attributes: Trans MTF",
}

# The subset of _EXISTING_CATEGORY_RENAMES that classify_scene() actually reads (the
# GROUP_SINGLE_FEMALE/GROUP_MULTI_FEMALE_HEADCOUNT/GROUP_MULTI_FEMALE_ACTIVITY tags making up
# COMPOSITION_TAGS) - derived rather than hand-duplicated so it can never drift from the Plex
# side. Composition collections outside COMPOSITION_TAGS (FFT, Orgy) aren't read by
# classify_scene() at all, so they don't need a Stash tag rename and are correctly excluded here
# - only Plex-side renaming (via rename-categories --include-composition) applies to them.
#
# Filters on the *new* (post-rename) tag being in COMPOSITION_TAGS, not the old one -
# GROUP_SINGLE_FEMALE/etc. hold the new "Composition: X" names (classify_scene() only ever needs
# to recognize live data), so filtering on the old name would find nothing.
_COMPOSITION_TAG_RENAMES: dict[str, str] = {
    tag: new_tag
    for old_collection, new_collection in _EXISTING_CATEGORY_RENAMES.items()
    if (tag := _collection_to_tag(old_collection)) is not None
    and (new_tag := _collection_to_tag(new_collection)) in COMPOSITION_TAGS
}

# Existing "01: Category:" collections deliberately left out of _EXISTING_CATEGORY_RENAMES -
# none of Cumshot/Composition/Prop/Activity/Theme/Attributes fit cleanly, for the reason noted
# per entry.
_UNCLASSIFIED_CATEGORY_NOTES: dict[str, str] = {
    "01: Category: Beautiful Agony": "looks like it may actually be a studio/brand name, not a content category - worth checking before any rename",
    "01: Category: Non-Sexual": "content-type flag (also appears in EXCLUDED_MONEYSHOT_COLLECTIONS for the same reason), not a content descriptor itself",
    "01: Category: Short Videos": "video format/length, not a content descriptor",
    "01: Category: Vertical Video": "video format/orientation, not a content descriptor",
}


def _write_unmapped_tags_report(
    path: str | Path,
    unmapped: list[dict[str, Any]],
    web_base: str,
    stash_box_names: dict[str, str],
    existing_titles: set[str],
    *,
    total_tag_count: int,
    local_tag_count: int,
) -> None:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    add_rows: list[dict[str, Any]] = []
    merge_rows: list[tuple[dict[str, Any], str]] = []
    skip_rows: list[dict[str, Any]] = []
    for tag in unmapped:
        action = _suggested_action(str(tag["name"]), existing_titles)
        if action == "skip":
            skip_rows.append(tag)
        elif action.startswith("merge -> "):
            merge_rows.append((tag, action[len("merge -> ") :]))
        else:
            add_rows.append(tag)

    lines = [
        "# Stash Tags With No Matching Plex Collection",
        "",
        f"Generated: {generated_at}",
        "",
        f"Found {len(unmapped)} unmapped tags out of {total_tag_count} total Stash tags "
        f"({local_tag_count} local tags excluded - see AGENTS.md/README for why).",
        f"{len(add_rows)} suggested add, {len(merge_rows)} suggested merge, {len(skip_rows)} suggested skip.",
        "",
        "All of the below is a heuristic starting point for review, not a decision. `merge` "
        "always reflects an actual existing Plex collection as the target. `Suggested "
        "Collection` for `Add` rows is a keyword-based guess at the emerging taxonomy "
        "(Cumshot/Composition/Prop/Activity/Theme) and falls back to the existing `Category:` "
        "form when no keyword matched - verify before creating anything.",
        "",
        "## Add",
        "",
        "Grouped by the suggested taxonomy prefix below - `Category` is the catch-all for "
        "tags that didn't match any of the other keyword groups.",
    ]
    add_by_prefix: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for tag in add_rows:
        suggested = _suggest_new_collection_name(str(tag["name"]))
        prefix_label = suggested.split(": ", 2)[1]
        add_by_prefix[prefix_label].append(tag)
    for prefix_label in sorted(add_by_prefix):
        lines.extend(
            [
                "",
                f"### {prefix_label}",
                "",
                "| Scenes | Tag | Source | Suggested Collection | Link |",
                "|---:|---|---|---|---|",
            ]
        )
        lines.extend(
            f"| {tag.get('scene_count') or 0} | {_escape_markdown_table_cell(tag['name'])} | "
            f"{_escape_markdown_table_cell(_tag_source(tag, stash_box_names))} | "
            f"{_escape_markdown_table_cell(_suggest_new_collection_name(str(tag['name'])))} | "
            f"[view]({web_base}/tags/{tag['id']}) |"
            for tag in sorted(add_by_prefix[prefix_label], key=lambda t: t.get("scene_count") or 0, reverse=True)
        )

    lines.extend(["", "## Merge", "", "| Scenes | Tag | Source | Merge Into | Link |", "|---:|---|---|---|---|"])
    lines.extend(
        f"| {tag.get('scene_count') or 0} | {_escape_markdown_table_cell(tag['name'])} | "
        f"{_escape_markdown_table_cell(_tag_source(tag, stash_box_names))} | "
        f"{_escape_markdown_table_cell(target)} | "
        f"[view]({web_base}/tags/{tag['id']}) |"
        for tag, target in sorted(merge_rows, key=lambda pair: pair[1])
    )

    # Covers both add-bucket tags waiting entirely on a pending collection, and merge-bucket
    # tags that already merged somewhere but would upgrade to a fuller multi-target merge once
    # a pending collection exists (e.g. "Anal Cowgirl - POV" merges into bare Anal today, but
    # _potential_merge_targets still surfaces its full [Anal, POV] rule, so it's tracked here
    # too instead of silently missing from this section).
    # A target counts as pending only if it doesn't resolve under either its old or renamed
    # name (see _resolve_existing) - otherwise a merge-phrase target written against a
    # collection's pre-rename name would wrongly show as "pending" forever after
    # rename_categories() actually renames it, even though it's fully real again.
    pending_targets: dict[str, list[str]] = defaultdict(list)
    for tag in add_rows:
        targets = _potential_merge_targets(str(tag["name"]))
        if not targets:
            continue
        for target in targets:
            if _resolve_existing(target, existing_titles) is None:
                pending_targets[target].append(str(tag["name"]))
    for tag, current_target in merge_rows:
        targets = _potential_merge_targets(str(tag["name"]))
        if not targets:
            continue
        for target in targets:
            if _resolve_existing(target, existing_titles) is None:
                pending_targets[target].append(f"{tag['name']} (currently -> {current_target})")

    if pending_targets:
        # Sorted by impact (most tags unlocked first) rather than alphabetically, so it's clear
        # which pending collection to create first if prioritizing.
        ordered_targets = sorted(pending_targets, key=lambda target: (-len(pending_targets[target]), target))
        lines.extend(
            [
                "",
                "## Pending Collections",
                "",
                "Tags below already have a merge rule pointed at a collection that doesn't exist "
                "in Plex yet - once created, they'll show up under `## Merge` on the next run "
                '(fully, for rows marked "currently -> X", which already merge into X today but '
                "would upgrade to the fuller multi-target merge). Sorted by how many tags each "
                "one unlocks, most first. Creation order doesn't otherwise matter between "
                "different rows: each rule only depends on its own listed target(s) existing, "
                "there's no dependency chain between them.",
                "",
                "| Suggested Collection | Tags Unlocked | Tags waiting on it |",
                "|---|---:|---|",
            ]
        )
        lines.extend(
            f"| {_escape_markdown_table_cell(target)} | {len(pending_targets[target])} | "
            f"{_escape_markdown_table_cell(', '.join(sorted(pending_targets[target])))} |"
            for target in ordered_targets
        )

    lines.extend(["", "## Skip", "", "| Scenes | Tag | Source | Link |", "|---:|---|---|---|"])
    lines.extend(
        f"| {tag.get('scene_count') or 0} | {_escape_markdown_table_cell(tag['name'])} | "
        f"{_escape_markdown_table_cell(_tag_source(tag, stash_box_names))} | "
        f"[view]({web_base}/tags/{tag['id']}) |"
        for tag in sorted(skip_rows, key=lambda t: t.get("scene_count") or 0, reverse=True)
    )

    existing_renames = sorted(
        ((old, new) for old, new in _EXISTING_CATEGORY_RENAMES.items() if old in existing_titles),
        key=lambda pair: pair[1],
    )
    lines.extend(
        [
            "",
            '## Existing "01: Category:" Rename Suggestions',
            "",
            "Hand-classified, not keyword-guessed - the full 01: Category: list is small and "
            "fixed enough to review individually. Sorted by suggested name so collections "
            "headed for the same new prefix are grouped together. This is a starting point "
            "for the taxonomy rework, not something this tool applies automatically.",
            "",
            "| Current | Suggested |",
            "|---|---|",
        ]
    )
    lines.extend(
        f"| {_escape_markdown_table_cell(old)} | {_escape_markdown_table_cell(new)} |" for old, new in existing_renames
    )

    unclassified = sorted(title for title in _UNCLASSIFIED_CATEGORY_NOTES if title in existing_titles)
    if unclassified:
        lines.extend(
            [
                "",
                "### Not classified",
                "",
                "No clean fit in Cumshot/Composition/Prop/Activity/Theme:",
                "",
                "| Collection | Note |",
                "|---|---|",
            ]
        )
        lines.extend(
            f"| {_escape_markdown_table_cell(title)} | {_escape_markdown_table_cell(_UNCLASSIFIED_CATEGORY_NOTES[title])} |"
            for title in unclassified
        )

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_backfill_report(
    path: str | Path,
    *,
    dry_run: bool,
    processed: int,
    matched_count: int,
    composition_additions: dict[str, list[Any]],
    hair_additions: dict[str, list[Any]],
    composition_added_count: int,
    hair_added_count: int,
    ambiguous_entries: list[tuple[str, str]],
    review_path: str | Path,
    review_entry_count: int,
) -> None:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    mode = "DRY RUN (no Plex changes made)" if dry_run else "APPLIED"
    lines = [
        "# Stash -> Plex Backfill Report",
        "",
        f"Generated: {generated_at}",
        f"Mode: {mode}",
        "",
        "## Summary",
        "",
        f"- Plex videos scanned: {processed}",
        f"- Matched to Stash: {matched_count}",
        f"- Composition memberships added: {composition_added_count}",
        f"- Hair memberships added: {hair_added_count}",
        f"- Ambiguous matches staged for review: {len(ambiguous_entries)}",
        f"- Review entries written: {review_entry_count} -> {review_path}",
    ]

    if composition_additions:
        lines.extend(
            [
                "",
                "## Composition additions by collection",
                "",
                "| Collection | Videos added |",
                "|---|---:|",
            ]
        )
        lines.extend(
            f"| {_escape_markdown_table_cell(_tag_to_collection(tag))} | {len(videos)} |"
            for tag, videos in sorted(composition_additions.items())
        )

    if hair_additions:
        lines.extend(
            [
                "",
                "## Hair additions by collection",
                "",
                "| Collection | Videos added |",
                "|---|---:|",
            ]
        )
        lines.extend(
            f"| {_escape_markdown_table_cell(_tag_to_collection(tag))} | {len(videos)} |"
            for tag, videos in sorted(hair_additions.items())
        )

    lines.extend(["", "## Ambiguous scenes (staged for review, not applied)", ""])
    if ambiguous_entries:
        lines.extend(["| Title | Reason |", "|---|---|"])
        lines.extend(
            f"| {_escape_markdown_table_cell(title)} | {_escape_markdown_table_cell(reason)} |"
            for title, reason in ambiguous_entries
        )
    else:
        lines.append("_No ambiguous scenes this run._")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_review(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, list) or not all(isinstance(entry, dict) for entry in payload):
        raise ValueError("Review file must contain a JSON array of objects")
    return payload


def _decision_entries(
    decision: SceneDecision,
    stash_tags: set[str],
    plex_tags: set[str],
) -> list[dict[str, Any]]:
    common = {
        "rating_key": decision.rating_key,
        "title": decision.title,
        "file_paths": decision.file_paths,
        "stash_tags": sorted(stash_tags),
        "plex_tags": sorted(_tag_to_collection(tag) for tag in plex_tags),
        "status": "proposed",
    }
    if decision.ambiguous_reason:
        return [
            {
                **common,
                "action": "ambiguous",
                "ambiguous_reason": decision.ambiguous_reason,
            }
        ]

    return [
        {
            **common,
            "action": "remove_candidate",
            "collection_to_remove": _tag_to_collection(tag),
            "reason": f"Stash composition tags {sorted(stash_tags)} contradict Plex tag {tag!r}",
        }
        for tag in decision.remove_candidates
    ]


def backfill_tags(args: Any) -> int:
    log_level = getattr(args, "log_level", "WARNING").upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.WARNING), format="%(levelname)s: %(message)s")

    cfg = load_config(args.config)
    endpoint = getattr(args, "stash_endpoint", None) or cfg.stash_endpoint
    if not endpoint:
        raise ValueError(
            "No Stash endpoint configured. Add stashEndpoint to your config file or pass --stash-endpoint."
        )

    print(info("Connecting to Stash and building scene index..."))
    stash_index = StashClient(endpoint).all_scenes()
    print(info(f"Stash: {len({scene['id'] for scene in stash_index.values()})} scenes across {len(stash_index)} paths"))

    plex_ctx = PlexContext(cfg)
    limit: int | None = getattr(args, "limit", None)
    path_filter: str | None = getattr(args, "path", None)
    additions: dict[str, list[Any]] = defaultdict(list)
    hair_additions: dict[str, list[Any]] = defaultdict(list)
    review_entries: list[dict[str, Any]] = []
    ambiguous_entries: list[tuple[str, str]] = []
    processed = 0
    matched_count = 0
    ambiguous_count = 0

    print(info("Scanning Plex library..."))
    for video in plex_ctx.all_videos():
        if limit is not None and processed >= limit:
            break

        reload_if_partial(video)
        locations = list(getattr(video, "locations", None) or [])
        if not locations:
            continue
        if path_filter and not any(location.startswith(path_filter) for location in locations):
            continue

        processed += 1
        matched: dict[str, dict[str, Any]] = {}
        for location in locations:
            scene = stash_index.get(location)
            if scene:
                matched[str(scene["id"])] = scene
        if not matched:
            log.debug("UNMATCHED Plex item: %s", video.title)
            continue

        matched_count += 1
        stash_hair_tags = set().union(*(_stash_tags_in_scope(scene, HAIR_TAGS) for scene in matched.values()))
        plex_hair_tags = _plex_tags_in_scope(video, HAIR_TAGS)
        for tag in sorted(stash_hair_tags - plex_hair_tags):
            hair_additions[tag].append(video)

        stash_tags = set().union(*(_stash_tags_in_scope(scene, COMPOSITION_TAGS) for scene in matched.values()))
        plex_tags = _plex_tags_in_scope(video, COMPOSITION_TAGS)
        decision = classify_scene(stash_tags, plex_tags)
        if decision is None:
            continue

        decision.rating_key = str(video.ratingKey)
        decision.title = str(video.title)
        decision.file_paths = locations

        if decision.ambiguous_reason:
            ambiguous_count += 1
            ambiguous_entries.append((decision.title, decision.ambiguous_reason))
        else:
            for tag in decision.adds:
                additions[tag].append(video)
        review_entries.extend(_decision_entries(decision, stash_tags, plex_tags))

    review_path = Path(getattr(args, "review_output", "reference/stash_backfill_review.json"))
    _write_review(review_path, review_entries)

    composition_added_count = 0
    for tag, videos in sorted(additions.items()):
        collection = plex_ctx.collection(_tag_to_collection(tag))
        composition_added_count += add_items(collection, videos, dry_run=args.dry_run)

    hair_added_count = 0
    for tag, videos in sorted(hair_additions.items()):
        collection = plex_ctx.collection(_tag_to_collection(tag))
        hair_added_count += add_items(collection, videos, dry_run=args.dry_run)

    report_path = Path(getattr(args, "report_output", "reference/stash_backfill_report.md"))
    _write_backfill_report(
        report_path,
        dry_run=args.dry_run,
        processed=processed,
        matched_count=matched_count,
        composition_additions=additions,
        hair_additions=hair_additions,
        composition_added_count=composition_added_count,
        hair_added_count=hair_added_count,
        ambiguous_entries=ambiguous_entries,
        review_path=review_path,
        review_entry_count=len(review_entries),
    )

    print(ok(f"Plex videos scanned: {processed}"))
    print(info(f"Matched to Stash: {matched_count}"))
    print(info(f"Composition memberships added: {composition_added_count}"))
    print(info(f"Hair memberships added: {hair_added_count}"))
    print(info(f"Ambiguous matches staged: {ambiguous_count}"))
    print(info(f"Review entries written: {len(review_entries)} → {review_path}"))
    print(info(f"Report written to {report_path}"))
    if args.dry_run:
        print(warn("Dry run - no Plex changes made."))
    return 0


def unmapped_tags(args: Any) -> int:
    log_level = getattr(args, "log_level", "WARNING").upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.WARNING), format="%(levelname)s: %(message)s")

    cfg = load_config(args.config)
    endpoint = getattr(args, "stash_endpoint", None) or cfg.stash_endpoint
    if not endpoint:
        raise ValueError(
            "No Stash endpoint configured. Add stashEndpoint to your config file or pass --stash-endpoint."
        )
    web_base = endpoint.rstrip("/")
    if web_base.endswith("/graphql"):
        web_base = web_base[: -len("/graphql")]

    print(info("Fetching Stash tags..."))
    stash = StashClient(endpoint)
    tags = stash.all_tags()
    stash_box_names = {box["endpoint"]: str(box["name"]) for box in stash.configured_stash_boxes()}

    print(info("Fetching Plex collections..."))
    plex_ctx = PlexContext(cfg)
    existing_titles = {str(collection.title) for collection in plex_ctx.section.collections()}

    candidates = [tag for tag in tags if not _has_existing_plex_match(tag, existing_titles)]
    local_tag_count = sum(1 for tag in candidates if not (tag.get("stash_ids") or []))
    unmapped = [tag for tag in candidates if tag.get("stash_ids") or []]
    unmapped.sort(key=lambda tag: tag.get("scene_count") or 0, reverse=True)

    report_path = Path(getattr(args, "output", "reference/stash_unmapped_tags.md"))
    _write_unmapped_tags_report(
        report_path,
        unmapped,
        web_base,
        stash_box_names,
        existing_titles,
        total_tag_count=len(tags),
        local_tag_count=local_tag_count,
    )

    print(ok(f"Unmapped tags: {len(unmapped)} of {len(tags)} total ({local_tag_count} local excluded)"))
    print(info(f"Report written to {report_path}"))
    return 0


def rename_tags(args: Any) -> int:
    """Rename the Stash tags that back COMPOSITION_TAGS to their new taxonomy names.

    This is the Stash-side counterpart to `plexadm collection rename-categories
    --include-composition`: classify_scene() matches Stash tag names and Plex-collection-derived
    tag names by exact string, so both sides must carry the new name before that flag is safe to
    use. Renaming here does not by itself change matching behavior - GROUP_SINGLE_FEMALE /
    GROUP_MULTI_FEMALE_HEADCOUNT / GROUP_MULTI_FEMALE_ACTIVITY (and therefore COMPOSITION_TAGS)
    must be updated to the new names in the same change that this command is actually run for
    real, or backfill-tags will stop finding any composition tags at all in the interim.
    """
    log_level = getattr(args, "log_level", "WARNING").upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.WARNING), format="%(levelname)s: %(message)s")

    cfg = load_config(args.config)
    endpoint = getattr(args, "stash_endpoint", None) or cfg.stash_endpoint
    if not endpoint:
        raise ValueError(
            "No Stash endpoint configured. Add stashEndpoint to your config file or pass --stash-endpoint."
        )

    stash = StashClient(endpoint)
    existing = {str(tag["name"]): str(tag["id"]) for tag in stash.all_tags()}

    renamed = 0
    skipped_collisions = 0
    for old_name, new_name in sorted(_COMPOSITION_TAG_RENAMES.items()):
        if old_name == new_name or old_name not in existing:
            continue
        if new_name in existing:
            print(warn(f"Skipping '{old_name}' -> '{new_name}': a tag named '{new_name}' already exists."))
            skipped_collisions += 1
            continue
        print(warn(f"'{old_name}' needs to be renamed to '{new_name}'"))
        if not args.dry_run:
            stash.rename_tag(existing[old_name], new_name)
        renamed += 1
    print(info(f"{renamed} tags renamed.{dry_run_note(args)}"))
    if skipped_collisions:
        print(warn(f"{skipped_collisions} renames skipped due to a name collision - resolve manually in Stash."))
    return 0


def apply_review(args: Any) -> int:
    log_level = getattr(args, "log_level", "WARNING").upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.WARNING), format="%(levelname)s: %(message)s")

    entries = _load_review(args.review_file)
    include_ambiguous = getattr(args, "include_ambiguous", False)
    selected = [
        entry
        for entry in entries
        if entry.get("action") == "remove_candidate" or (include_ambiguous and entry.get("action") == "ambiguous")
    ]

    missing_collection = [entry for entry in selected if not entry.get("collection_to_remove")]
    if missing_collection:
        print(warn(f"Skipping {len(missing_collection)} entries without collection_to_remove."))
    selected = [entry for entry in selected if entry.get("collection_to_remove")]

    invalid_collections = sorted(
        {
            str(entry["collection_to_remove"])
            for entry in selected
            if entry["collection_to_remove"] not in COMPOSITION_COLLECTIONS
        }
    )
    if invalid_collections:
        raise ValueError(f"Review file contains out-of-scope collections: {invalid_collections}")

    cfg = load_config(args.config)
    plex_ctx = PlexContext(cfg)
    videos_by_key = {str(video.ratingKey): video for video in plex_ctx.all_videos()}
    removals: dict[str, list[Any]] = defaultdict(list)
    missing_keys: list[str] = []
    seen: set[tuple[str, str]] = set()

    for entry in selected:
        rating_key = str(entry.get("rating_key", ""))
        collection_title = str(entry["collection_to_remove"])
        key = (collection_title, rating_key)
        if key in seen:
            continue
        seen.add(key)
        video = videos_by_key.get(rating_key)
        if video is None:
            missing_keys.append(rating_key)
            continue
        reload_if_partial(video)
        removals[collection_title].append(video)

    removed_count = 0
    for collection_title, videos in sorted(removals.items()):
        collection = plex_ctx.collection(collection_title)
        removed_count += remove_items(collection, videos, dry_run=args.dry_run)

    if missing_keys:
        print(warn(f"Skipped missing Plex rating keys: {sorted(set(missing_keys))}"))
    print(ok(f"Review entries selected: {len(selected)}"))
    print(info(f"Composition memberships removed: {removed_count}"))
    if args.dry_run:
        print(warn("Dry run - no Plex changes made."))
    return 0
