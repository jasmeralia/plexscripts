#!/bin/bash

REMOTE_HOST="truenas"
UPLOAD_PATH="/mnt/myzmirror/plexdata/NSFW Scenes"

for filename in *.mp4
do
#   echo "Filename = ${filename}"
  star_name=$(echo "${filename}" | awk -F\- '{print $1}' | awk -F\, '{print $1}' | sed -e 's/ $//' | sed -e 's/.mp4$//')
  remote_dir_path="${UPLOAD_PATH}/${star_name}"
  remote_file_path="${remote_dir_path}/${filename}"
  scp_path="${REMOTE_HOST}:'${remote_file_path}.tmp'"
  # echo "Creating ${remote_path} ..."
  # shellcheck disable=SC2029
  ssh "${REMOTE_HOST}" mkdir "'${remote_dir_path}'" 2>&1 | grep -v 'File exists'
  echo "Uploading to ${scp_path} ..."
  if scp "${filename}" "${scp_path}"; then
    if ssh "${REMOTE_HOST}" mv "'${remote_file_path}.tmp'" "'${remote_file_path}'"; then
      echo "${filename} uploaded and renamed successfully, deleting..."
      /bin/rm "${filename}"
    else
      echo "Unable to rename from '${remote_file_path}.tmp' to '${remote_file_path}'!"
    fi
  else
    echo "Error uploading to ${scp_path}!"
  fi
done
