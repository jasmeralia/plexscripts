#!/bin/bash

if [ "$1" == "" ]; then
  list_no_studio_vids.py | cut -d',' -f1 | cut -d'-' -f1 | sed -e 's/Title: //' | sort | uniq -c | sort -n
else
  list_no_studio_vids.py | cut -d',' -f1 | cut -d'-' -f1 | sed -e 's/Title: //' | sort | uniq -c | sort -n | tail "-$1"
fi
