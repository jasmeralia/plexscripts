#!/bin/bash

list_uncategorized_vids.py | grep 'Scene #' | cut -d '-' -f2- | cut -d '(' -f1 | sed -e 's/^([ ]+)//' | sort | uniq -c | sort -n
