#!/bin/bash -x

# First, set all the writers from the titles
date; time python3 -u set_writers_and_create_collections.py

# Add certain writer-specific collections
date; time set_asians.sh
date; time set_indies.sh
date; time set_pierced.sh
date; time set_porcelain.sh

# Add known hair color collections
date; time set_hair.sh

# Copy certain collections and studios to other collections
date; time copy_collections.sh

# Set certain tags based on the title
date; time set_tags_based_on_title.sh

# Update the contents of the unrated collection
date; time python3 -u update_unrated_collection.py '001: Unrated'

date
