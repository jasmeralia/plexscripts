#!/bin/bash
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
. "${SCRIPT_DIR}/plexadm-env.sh"

if [ "$1" == "" ]; then
  "$PLEXADM" list videos --no-studio | cut -d',' -f1 | cut -d'-' -f1 | sed -e 's/Title: //' | sort | uniq -c | sort -n
else
  "$PLEXADM" list videos --no-studio | cut -d',' -f1 | cut -d'-' -f1 | sed -e 's/Title: //' | sort | uniq -c | sort -n | tail "-$1"
fi
