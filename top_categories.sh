#!/bin/bash

if [ "$1" -eq ""]; then
  TAIL_SIZEE=15
fi
list_collections.py "01: Category: " | sort -n | tail "-${TAIL_SIZE}"
