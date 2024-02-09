#!/bin/bash

if [ "$1" == "" ]; then
  list_no_studio_vids.py | grep 'Scene #' | cut -d '-' -f2- | cut -d '(' -f1 | sed -e 's/^([ ]+)//' | sort | uniq -c | sort -n
else
  list_no_studio_vids.py | grep 'Scene #' | cut -d '-' -f2- | cut -d '(' -f1 | sed -e 's/^([ ]+)//' | sort | uniq -c | sort -n | tail "-$1"
fi
