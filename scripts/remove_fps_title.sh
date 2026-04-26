#!/bin/bash
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
. "${SCRIPT_DIR}/plexadm-env.sh"

if [ "$1" == "" ]; then
  echo "Usage: $0 <filename>"
  exit 1
fi

"$PLEXADM" tools remove-fps-title "$1"
