#!/bin/bash

if [ "$1" == "" ]; then
  list_collection_vids.py '001: Unrated' | grep 'Scene #' | cut -d '-' -f2- | cut -d '(' -f1 | sed -e 's/^([ ]+)//' | sort | uniq -c | sort -n
else
  list_collection_vids.py '001: Unrated' | grep 'Scene #' | cut -d '-' -f2- | cut -d '(' -f1 | sed -e 's/^([ ]+)//' | sort | uniq -c | sort -n | tail "-$1"
fi
