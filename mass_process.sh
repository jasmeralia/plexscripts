#!/bin/bash -x

# First, set all the writers from the titles
date; time python3 -u set_writers_and_create_collections.py

# Add certain writer-specific collections
date; time set_tags_based_on_writers.sh

# Set certain tags based on the title
date; time set_tags_based_on_title.sh

# Copy certain collections and studios to other collections
date; time copy_collections.sh

# Update the contents of the unrated collection
date; time python3 -u update_unrated_collection.py '001: Unrated'

# Add short videos to a special collection
date; time python3 -u add_short_duration_vids_to_collection.py '01: Category: Short Videos'

date
