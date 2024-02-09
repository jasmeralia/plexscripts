#!/bin/bash

if [ "$1" -eq "" ]; then
  TAIL_SIZE=15
fi
list_collections.py "01: Category: " | sort -n | tail "-${TAIL_SIZE}"
