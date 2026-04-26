#!/bin/bash
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
. "${SCRIPT_DIR}/plexadm-env.sh"

"$PLEXADM" list studios | grep '^[ 0-9][ 0-9][ 0-9][ 0-9]: ' | sort -n | tail -15
