#!/bin/bash
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
. "${SCRIPT_DIR}/plexadm-env.sh"

REFERENCE_DIR=${PLEXADM_REFERENCE_DIR:-/usr/local/share/plexadm/reference}

"$PLEXADM" studio bulk-independent "${REFERENCE_DIR}/writers_indie.txt"

"$PLEXADM" collection add-writers '01: Category: Solo' "${REFERENCE_DIR}/writers_solo.txt"
"$PLEXADM" collection add-writers '01: Category: Asian' "${REFERENCE_DIR}/writers_asian.txt"
"$PLEXADM" collection add-writers '01: Category: Pierced Nipples' "${REFERENCE_DIR}/writers_pierced_nipples.txt"
"$PLEXADM" collection add-writers '01: Category: Pierced Tongue' "${REFERENCE_DIR}/writers_pierced_tongue.txt"
"$PLEXADM" collection add-writers '01: Category: Porcelain Skin' "${REFERENCE_DIR}/writers_porcelain.txt"
"$PLEXADM" collection add-writers '01: Category: Trans MTF' "${REFERENCE_DIR}/writers_trans_mtf.txt"

"$PLEXADM" collection add-writers '01: Hair: Blonde' "${REFERENCE_DIR}/writers_blonde.txt"
"$PLEXADM" collection add-writers '01: Hair: Blue' "${REFERENCE_DIR}/writers_blue_hair.txt"
"$PLEXADM" collection add-writers '01: Hair: Brunette' "${REFERENCE_DIR}/writers_brunette.txt"
"$PLEXADM" collection add-writers '01: Hair: Red' "${REFERENCE_DIR}/writers_redhead.txt"
