#!/bin/bash

python3 -u bulk_set_independent_for_writers.py writers_indie.txt

python3 -u bulk_add_writers_to_collection.py '01: Category: Solo' writers_solo.txt
python3 -u bulk_add_writers_to_collection.py '01: Category: Asian' writers_asian.txt
python3 -u bulk_add_writers_to_collection.py '01: Category: Pierced Nipples' writers_pierced_nipples.txt
python3 -u bulk_add_writers_to_collection.py '01: Category: Pierced Tongue' writers_pierced_tongue.txt
python3 -u bulk_add_writers_to_collection.py '01: Category: Porcelain Skin' writers_porcelain.txt
python3 -u bulk_add_writers_to_collection.py '01: Category: Trans MTF' writers_trans_mtf.txt

python3 -u bulk_add_writers_to_collection.py '01: Hair: Blonde' writers_blonde.txt
python3 -u bulk_add_writers_to_collection.py '01: Hair: Blue' writers_blue_hair.txt
python3 -u bulk_add_writers_to_collection.py '01: Hair: Brunette' writers_brunette.txt
python3 -u bulk_add_writers_to_collection.py '01: Hair: Red' writers_redhead.txt
