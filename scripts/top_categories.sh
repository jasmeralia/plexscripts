#!/bin/bash
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
. "${SCRIPT_DIR}/plexadm-env.sh"

if [ "$1" == "" ]; then
  TAIL_SIZE=15
else
  TAIL_SIZE="$1"
fi
"$PLEXADM" list collections "01: Category: " | sort -n | tail "-${TAIL_SIZE}"
