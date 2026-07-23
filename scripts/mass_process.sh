#!/bin/bash -x
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
. "${SCRIPT_DIR}/plexadm-env.sh"
START_DATE=$(date)

# First, set all the writers from the titles
date; time "$PLEXADM" writers set-and-sync

# Add certain writer-specific collections
date; time "${SCRIPT_DIR}/set_tags_based_on_writers.sh"

# Set certain tags based on the title
date; time "${SCRIPT_DIR}/set_tags_based_on_title.sh"

# Copy certain collections and studios to other collections
date; time "${SCRIPT_DIR}/copy_collections.sh"

# Add short videos to a special collection
date; time "$PLEXADM" collection add-duration '01: Category: Short Videos'

# Add videos with 4+ performers to orgy
date; time "$PLEXADM" collection add-orgy '01: Composition: Orgy'

# Add vertically-oriented videos to a special collection
date; time "$PLEXADM" collection add-vertical '01: Category: Vertical Video'

# Update the contents of the unrated collection
date; time "${SCRIPT_DIR}/set_unrated.sh"

# Update the contents of the PPV collection
date; time "${SCRIPT_DIR}/set_ppv.sh"

date; time "$PLEXADM" collection sync-no-studio "00A: NO STUDIO"

# Flag likely-mistagged '01: Composition: Lesbian' members for review
date; time "$PLEXADM" collection sync-lesbian-single-writer

# Flag sexual, non-female-only videos with no Cumshot-collection membership for review
date; time "$PLEXADM" collection sync-cumshot-absent

# Flag long indie videos with no Live Stream tag for review - often a livestream recording
# that's missing the tag
date; time "$PLEXADM" collection add-duration "00D: Review: Potential Live Streams" \
  --min-duration-ms 5400000 \
  --filters '{"studio": "Independent Content", "collection!": "01: Theme: Live Stream"}'

END_DATE=$(date)
echo "Start date: ${START_DATE}"
echo "  End date: ${END_DATE}"
