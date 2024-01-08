#!/bin/bash

list_studios.py | grep '^[ 0-9][ 0-9][ 0-9][ 0-9]: ' | sort -n | tail -15
