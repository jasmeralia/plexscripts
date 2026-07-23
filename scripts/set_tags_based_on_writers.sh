#!/bin/bash
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
. "${SCRIPT_DIR}/plexadm-env.sh"

REFERENCE_DIR=${PLEXADM_REFERENCE_DIR:-/usr/local/share/plexadm/reference}

"$PLEXADM" studio bulk-independent "${REFERENCE_DIR}/writers_indie.txt"

"$PLEXADM" collection add-writers --single-writer-only '01: Composition: Solo' "${REFERENCE_DIR}/writers_solo.txt"
"$PLEXADM" collection add-writers '01: Attributes: Asian' "${REFERENCE_DIR}/writers_asian.txt"
"$PLEXADM" collection add-writers '01: Attributes: Pierced Nipples' "${REFERENCE_DIR}/writers_pierced_nipples.txt"
"$PLEXADM" collection add-writers '01: Attributes: Pierced Vagina' "${REFERENCE_DIR}/writers_pierced_vagina.txt"
"$PLEXADM" collection add-writers '01: Attributes: Pierced Tongue' "${REFERENCE_DIR}/writers_pierced_tongue.txt"
"$PLEXADM" collection add-writers '01: Attributes: Porcelain Skin' "${REFERENCE_DIR}/writers_porcelain.txt"
"$PLEXADM" collection add-writers '01: Attributes: Trans MTF' "${REFERENCE_DIR}/writers_trans_mtf.txt"

"$PLEXADM" collection add-writers '01: Hair: Blonde' "${REFERENCE_DIR}/writers_blonde.txt"
"$PLEXADM" collection add-writers '01: Hair: Blue' "${REFERENCE_DIR}/writers_blue_hair.txt"
"$PLEXADM" collection add-writers '01: Hair: Brunette' "${REFERENCE_DIR}/writers_brunette.txt"
"$PLEXADM" collection add-writers '01: Hair: Red' "${REFERENCE_DIR}/writers_redhead.txt"

"$PLEXADM" collection add-writers '01: Activity: Completely Throated' "${REFERENCE_DIR}/writers_completely_throated.txt"
"$PLEXADM" collection add-writer '01: Activity: Extreme Throating' "Tiptobase69"
