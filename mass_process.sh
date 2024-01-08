#!/bin/bash -x

# First, set all the writers from the titles
date; time set_writers_from_titles.py

# Add certain writer-specific collections
date; time set_asians.sh
date; time set_redheads.sh
date; time set_indies.sh

# Create new smart collections for all new writers
date; time create_smart_collections_for_writers.py

# Create new smart collections for all new studios
date; time create_smart_collections_for_studios.py
date
