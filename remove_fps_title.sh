#!/bin/bash

if [ "$1" == "" ]; then
  echo "Usage: $0 <filename>"
  exit 1
fi

ORI_FNAME=$1
# shellcheck disable=SC2001
NEW_FNAME=$(echo "${ORI_FNAME}" | sed -e 's/_[236][450]fps//')

echo "Renaming '${ORI_FNAME}' to '${NEW_FNAME}'..."
mv "${ORI_FNAME}" "${NEW_FNAME}"
