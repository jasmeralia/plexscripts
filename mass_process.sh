#!/bin/bash -x

# First, set all the writers from the titles
date; time python3 -u set_writers_from_titles.py

# Add certain writer-specific collections
date; set_asians.sh
date; set_indies.sh
date; set_porcelain.sh

# Add known hair color collections
date; set_hair.sh

# Copy certain collections and studios to other collections
date; copy_collections.sh

# Set certain tags based on the title
date; time set_tags_based_on_title.sh

# Create new smart collections for all new writers and studios
date; time python3 -u create_smart_collections_unified.py

# Update the contents of the unrated collection
date; time python3 -u update_unrated_collection.py '001: Unrated'

date
