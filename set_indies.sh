#!/bin/bash -x

time python3 -u bulk_set_independent_for_writers.py indie_writers.txt | tee indies.log
# time python3 -u bulk_add_writers_to_collection.py '01: Category: Solo' solo_writers.txt | tee solos.log
