#!/bin/bash
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
. "${SCRIPT_DIR}/plexadm-env.sh"

if [ "$1" == "" ]; then
  "$PLEXADM" list videos --collection '00C: Unrated' | grep 'Scene #' | cut -d '-' -f2- | cut -d '(' -f1 | sed -e 's/^([ ]+)//' | sort | uniq -c | sort -n
else
  "$PLEXADM" list videos --collection '00C: Unrated' | grep 'Scene #' | cut -d '-' -f2- | cut -d '(' -f1 | sed -e 's/^([ ]+)//' | sort | uniq -c | sort -n | tail "-$1"
fi
