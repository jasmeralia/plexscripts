#!/bin/bash
# ONE-TIME TAXONOMY MIGRATION - not part of mass_process.sh.
#
# Renames existing '01: Category:' collections into the Activity/Composition/Cumshot/Prop/
# Theme/Attributes taxonomy (see plexadm.stash_backfill_tags._EXISTING_CATEGORY_RENAMES).
# Composition collections (Solo, MMF, FFM, Lesbian, Orgy, ...) are skipped by default since
# Stash tags aren't renamed to match yet - see `plexadm collection rename-categories --help`.
#
# Every other script that references a renamed collection by its old name
# (set_tags_based_on_title.sh, copy_collections.sh, set_tags_based_on_writers.sh,
# mass_process.sh) has already been updated to the new names in the same change that added
# this script - run this BEFORE the next mass_process.sh run, or those will fail to find their
# target collections.
#
# Defaults to --dry-run. Pass --apply to actually rename.
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
. "${SCRIPT_DIR}/plexadm-env.sh"

REFERENCE_DIR=${PLEXADM_REFERENCE_DIR:-/usr/local/share/plexadm/reference}

if [ "$1" == "--apply" ]; then
  time "$PLEXADM" collection rename-categories | tee "${REFERENCE_DIR}/rename_categories.log"
else
  echo "Dry run (pass --apply to actually rename). Preview:"
  time "$PLEXADM" collection rename-categories --dry-run | tee "${REFERENCE_DIR}/rename_categories.log"
fi
