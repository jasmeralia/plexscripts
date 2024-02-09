#!/bin/bash

if [ "$1" == "" ]; then
  list_collection_vids.py '001: Unrated' | cut -d',' -f1 | cut -d'-' -f1 | sed -e 's/Title: //' | sort | uniq -c | sort -n
else
  list_collection_vids.py '001: Unrated' | cut -d',' -f1 | cut -d'-' -f1 | sed -e 's/Title: //' | sort | uniq -c | sort -n | tail "-$1"
fi
