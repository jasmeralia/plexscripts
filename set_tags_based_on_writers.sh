#!/bin/bash

python3 -u bulk_set_independent_for_writers.py indie_writers.txt
python3 -u bulk_add_writers_to_collection.py '01: Category: Asian' asian_writers.txt
python3 -u bulk_add_writers_to_collection.py '01: Category: Blonde Hair' blonde_writers.txt
python3 -u bulk_add_writers_to_collection.py '01: Category: Blue Hair' blue_hair_writers.txt
python3 -u bulk_add_writers_to_collection.py '01: Category: Brunette Hair' brunette_writers.txt
# python3 -u bulk_add_writers_to_collection.py '01: Category: Solo' solo_writers.txt
python3 -u bulk_add_writers_to_collection.py '01: Category: Pierced Nipples' pierced_nipples_writers.txt
python3 -u bulk_add_writers_to_collection.py '01: Category: Pierced Tongue' pierced_tongue_writers.txt
python3 -u bulk_add_writers_to_collection.py '01: Category: Porcelain Skin' porcelain_writers.txt
python3 -u bulk_add_writers_to_collection.py '01: Category: Red Hair' redhead_writers.txt
