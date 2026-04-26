#!/bin/bash
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
. "${SCRIPT_DIR}/plexadm-env.sh"

set +x
TMPFILE=$(mktemp /tmp/listvids.XXXXXXXXXX) || exit 1
if [ "$1" == "" ]; then
  TAIL_SIZE="15"
else
  TAIL_SIZE="$1"
fi
"$PLEXADM" list special no-hair | grep 'Title:' | grep -v 'Unknown' | grep -v 'TBD' | sed -e 's/Title: //' | cut -d'-' -f1 | sed -e 's/, /\n/g' | sort | uniq -c | sort -n > "${TMPFILE}"
if [ "$TAIL_SIZE" == "0" ]; then
  cat "${TMPFILE}"
else
  tail "-${TAIL_SIZE}" "${TMPFILE}"
fi
/bin/rm -f "${TMPFILE}"
