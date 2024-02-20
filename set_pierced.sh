#!/bin/bash -x

time python3 -u bulk_add_writers_to_collection.py '01: Category: Pierced Nipples' pierced_nipples_writers.txt | tee piercings.log
time python3 -u bulk_add_writers_to_collection.py '01: Category: Pierced Tongue' pierced_tongue_writers.txt | tee -a piercings.log
