#!/bin/bash

list_no_studio_vids.py | grep 'Scene #' | cut -d '-' -f2- | cut -d '(' -f1 | sed -e 's/^([ ]+)//' | sort | uniq -c | sort -n
