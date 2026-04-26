#!/bin/bash

if [ -n "${PLEXADM:-}" ]; then
  return 0
fi

PLEXADM_SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PLEXADM_LOCAL="${PLEXADM_SCRIPT_DIR}/../bin/plexadm"
PLEXADM_LOCAL_REFERENCE="${PLEXADM_SCRIPT_DIR}/../reference"

if [ -x "${PLEXADM_LOCAL}" ]; then
  PLEXADM="${PLEXADM_LOCAL}"
elif command -v plexadm >/dev/null 2>&1; then
  PLEXADM=$(command -v plexadm)
else
  echo "plexadm not found. Run from a checkout with bin/plexadm, run 'make install-system', or set PLEXADM=/path/to/plexadm." >&2
  return 127
fi

if [ -z "${PLEXADM_REFERENCE_DIR:-}" ] && [ -d "${PLEXADM_LOCAL_REFERENCE}" ]; then
  PLEXADM_REFERENCE_DIR="${PLEXADM_LOCAL_REFERENCE}"
fi

export PLEXADM
export PLEXADM_REFERENCE_DIR
