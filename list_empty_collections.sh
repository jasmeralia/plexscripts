#!/bin/bash

list_collections.py | grep '^   0: ' | grep -v '00: Review'
