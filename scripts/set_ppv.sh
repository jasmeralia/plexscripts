#!/bin/bash
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
. "${SCRIPT_DIR}/plexadm-env.sh"

REFERENCE_DIR=${PLEXADM_REFERENCE_DIR:-/usr/local/share/plexadm/reference}

time "$PLEXADM" collection sync-ppv '01: Category: PPV' | tee "${REFERENCE_DIR}/ppv.log"
