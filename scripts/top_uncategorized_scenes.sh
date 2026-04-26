#!/bin/bash
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
. "${SCRIPT_DIR}/plexadm-env.sh"

"$PLEXADM" list special uncategorized | grep 'Scene #' | cut -d '-' -f2- | cut -d '(' -f1 | sed -e 's/^([ ]+)//' | sort | uniq -c | sort -n
