#!/bin/bash
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
. "${SCRIPT_DIR}/plexadm-env.sh"

if [ "$1" == "" ]; then
  TAIL_SIZE=15
else
  TAIL_SIZE="$1"
fi
# "Category" collections now span several taxonomy prefixes after rename_categories.sh - Hair
# collections are a separate axis and are deliberately excluded, same as before that migration.
for PREFIX in "01: Category: " "01: Activity: " "01: Attributes: " "01: Composition: " "01: Cumshot: " "01: Prop: " "01: Theme: "; do
  "$PLEXADM" list collections "$PREFIX"
done | sort -n | tail "-${TAIL_SIZE}"
