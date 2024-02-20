#!/bin/bash

if [ "$1" == "" ]; then
  review_no_studio_vids.py | grep Scene | cut -d',' -f1 | cut -d'-' -f1 | sed -e 's/Title: //' | sort | uniq -c | sort -n
else
  review_no_studio_vids.py | grep Scene | cut -d',' -f1 | cut -d'-' -f1 | sed -e 's/Title: //' | sort | uniq -c | sort -n | tail "-$1"
fi
