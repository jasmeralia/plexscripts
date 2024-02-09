#!/bin/bash

set +x
TMPFILE=$(mktemp /tmp/listvids.XXXXXXXXXX) || exit 1
if [ "$1" == "" ]; then
  TAIL_SIZE="15"
else
  TAIL_SIZE="$1"
fi
list_no_hair_tag_videos.py | grep 'Title:' | grep -v 'Unknown' | grep -v 'TBD' | sed -e 's/Title: //' | cut -d'-' -f1 | sed -e 's/, /\n/g' | sort | uniq -c | sort -n > "${TMPFILE}"
if [ "$TAIL_SIZE" == "0" ]; then
  cat "${TMPFILE}"
else
  tail "-${TAIL_SIZE}" "${TMPFILE}"
fi
/bin/rm -f "${TMPFILE}"
