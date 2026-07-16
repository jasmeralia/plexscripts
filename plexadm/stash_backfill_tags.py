from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from plexadm.cli import EXCLUDED_COMPOSITION_COLLECTIONS, EXCLUDED_HAIR_COLLECTIONS
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
    "Category: Solo",
    "Category: MF Only",
    "Category: MMF",
    "Category: Gangbang",
}
GROUP_MULTI_FEMALE_HEADCOUNT = {
    "Category: FFM",
    "Category: FFFM",
    "Category: Reverse Gangbang",
    "Category: FFF+",
}
GROUP_MULTI_FEMALE_ACTIVITY = {"Category: Lesbian"}
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
    """
    tag_name = str(tag["name"])
    if _tag_to_collection(tag_name) in existing_titles:
        return True
    is_local = not (tag.get("stash_ids") or [])
    if is_local or tag_name.startswith(("Category: ", "Hair: ")):
        return False
    return f"01: Category: {tag_name}" in existing_titles or f"01: Hair: {tag_name}" in existing_titles


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

_SKIP_MARKER_WORDS = {"4k", "8k", "1080p", "720p", "fps", "hdr", "vr", "available"}

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
}


def _suggested_action(tag_name: str, existing_titles: set[str]) -> str:
    """Heuristic-only suggestion for an unmapped tag: 'add', 'merge -> <collection>', or 'skip'.

    A starting point for human review, not a decision.

    Two merge signals, both requiring the target collection to actually exist already:
    1. A curated phrase from `_CATEGORY_MERGE_PHRASES` (sourced from
       scripts/set_tags_based_on_title.sh's own already-validated keyword associations)
       appearing anywhere in the tag name.
    2. A hair-color keyword AND the word "hair"/"haired" both appearing as whole, space/
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
    if words & _SKIP_MARKER_WORDS:
        return "skip"
    for phrase, target in _CATEGORY_MERGE_PHRASES.items():
        if phrase in lower_name and target in existing_titles:
            return f"merge -> {target}"
    if words & _HAIR_CONTEXT_WORDS:
        for word in words:
            hair_target = _HAIR_MERGE_KEYWORDS.get(word)
            if hair_target and hair_target in existing_titles:
                return f"merge -> {hair_target}"
    return "add"


_CUMSHOT_KEYWORDS = frozenset({"cum", "creampie", "bukkake", "facial", "swallow", "throatpie", "cumshot"})
_COMPOSITION_KEYWORDS = frozenset(
    {"solo", "gangbang", "orgy", "threesome", "foursome", "mmf", "ffm", "fffm", "fff", "daisy", "chain", "trio"}
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
        "licking",
        "eating",
        "penetration",
        "throating",
        "throated",
        "tribbing",
        "slapping",
        "sitting",
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

# Checked in this order - some words plausibly fit more than one bucket (e.g. "throatpie" is
# cum-related first, act-related second), so priority matters. "01: Hair:" is deliberately not
# a target here: a tag reaching this function had no merge match against any existing hair
# collection, and inventing a 12th hair-color collection from a keyword guess is a bigger claim
# than this heuristic should make - left as a plain "add" with no special prefix instead.
_NEW_PREFIX_KEYWORD_GROUPS: list[tuple[str, frozenset[str]]] = [
    ("01: Cumshot: ", _CUMSHOT_KEYWORDS),
    ("01: Composition: ", _COMPOSITION_KEYWORDS),
    ("01: Prop: ", _PROP_KEYWORDS),
    ("01: Activity: ", _ACTIVITY_KEYWORDS),
    ("01: Theme: ", _THEME_KEYWORDS),
]


def _suggest_new_collection_name(tag_name: str) -> str:
    """Suggest a "01: <Prefix>: <name>" collection name for a tag with no existing match.

    Heuristic keyword classification into the emerging Cumshot/Composition/Prop/Activity/Theme
    taxonomy, checked in that priority order. Falls back to "01: Category: <name>" - the
    existing, safe default - when no keyword matches, rather than guessing into a specific new
    bucket without a real signal. The tag's own name is used verbatim as the suggested
    collection's suffix.
    """
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
    "01: Category: Cum Swapping": "01: Cumshot: Cum Swapping",
    "01: Category: Cum on Body": "01: Cumshot: Cum on Body",
    "01: Category: Cum on Feet": "01: Cumshot: Cum on Feet",
    "01: Category: Cum on Stomach": "01: Cumshot: Cum on Stomach",
    "01: Category: Custom": "01: Theme: Custom",
    "01: Category: Daisy Chain": "01: Composition: Daisy Chain",
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
    "01: Category: Plaid Miniskirt": "01: Theme: Plaid Miniskirt",
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
    "01: Category: Teacher/Tutor": "01: Theme: Teacher/Tutor",
    "01: Category: Throatpie": "01: Cumshot: Throatpie",
    "01: Category: Tit Fucking": "01: Activity: Tit Fucking",
    "01: Category: Trans MTF": "01: Composition: Trans MTF",
    "01: Category: Tribbing": "01: Activity: Tribbing",
    "01: Category: Triple Anal": "01: Activity: Triple Anal",
    "01: Category: Vaginal Creampie": "01: Cumshot: Vaginal Creampie",
    "01: Category: Voyeurism": "01: Theme: Voyeurism",
    "01: Category: Water": "01: Activity: Water",
}

# Existing "01: Category:" collections deliberately left out of _EXISTING_CATEGORY_RENAMES -
# none of Cumshot/Composition/Prop/Activity/Theme fit cleanly, for the reason noted per entry.
_UNCLASSIFIED_CATEGORY_NOTES: dict[str, str] = {
    "01: Category: Asian": "ethnicity descriptor, not a fit for any current bucket",
    "01: Category: Beautiful Agony": "looks like it may actually be a studio/brand name, not a content category - worth checking before any rename",
    "01: Category: Ebony": "ethnicity descriptor, not a fit for any current bucket",
    "01: Category: Non-Sexual": "content-type flag (also appears in EXCLUDED_MONEYSHOT_COLLECTIONS for the same reason), not a content descriptor itself",
    "01: Category: Pierced Nipples": "body modification, not a fit for any current bucket - possibly wants its own future prefix alongside Hair, e.g. Piercing",
    "01: Category: Pierced Tongue": "body modification, same note as Pierced Nipples",
    "01: Category: Pierced Vagina": "body modification, same note as Pierced Nipples",
    "01: Category: Porcelain Skin": "skin complexion, similar situation to hair color but no existing bucket for it",
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
        "| Scenes | Tag | Source | Suggested Collection | Link |",
        "|---:|---|---|---|---|",
    ]
    lines.extend(
        f"| {tag.get('scene_count') or 0} | {_escape_markdown_table_cell(tag['name'])} | "
        f"{_escape_markdown_table_cell(_tag_source(tag, stash_box_names))} | "
        f"{_escape_markdown_table_cell(_suggest_new_collection_name(str(tag['name'])))} | "
        f"[view]({web_base}/tags/{tag['id']}) |"
        for tag in sorted(add_rows, key=lambda t: t.get("scene_count") or 0, reverse=True)
    )

    lines.extend(["", "## Merge", "", "| Scenes | Tag | Source | Merge Into | Link |", "|---:|---|---|---|---|"])
    lines.extend(
        f"| {tag.get('scene_count') or 0} | {_escape_markdown_table_cell(tag['name'])} | "
        f"{_escape_markdown_table_cell(_tag_source(tag, stash_box_names))} | "
        f"{_escape_markdown_table_cell(target)} | "
        f"[view]({web_base}/tags/{tag['id']}) |"
        for tag, target in sorted(merge_rows, key=lambda pair: pair[1])
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
