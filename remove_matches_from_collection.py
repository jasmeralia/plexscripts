#!/usr/bin/env python3
#
# import modules
#
import sys
import os
import configparser
from pprint import pprint
from plexapi.server import PlexServer
#
# Sanity check CLI arguments and assign them to readable variable names
#
if len(sys.argv) != 3:
    print(f"Usage: {os.path.basename(__file__)} <collection name> <pattern match>")
    sys.exit(1)
pattern = sys.argv[2]
collection_name = sys.argv[1]
if collection_name == "02: Independent Content":
    indie_content = True
else:
    indie_content = False
print(f"Pattern: '{pattern}'")
#print(f"Collection: {collection_name}")
#
# set default variables
#
config = configparser.ConfigParser()
config.read(os.getenv('HOME')+'/.plexconfig.ini')
plex_host = config['default']['plex_host']
plex_port = config['default']['plex_port']
plex_section = config['default']['plex_section']
plex_token = config['default']['plex_token']
plex_section_name = config['default']['plex_section_name']
baseurl = f"http://{plex_host}:{plex_port}"
#
# Connect to server
#
plex = PlexServer(baseurl, plex_token)
#
# Select section
#
plex_section = plex.library.section(plex_section_name)
this_collection = plex_section.collection(collection_name)
if (str(this_collection.title).lower() == collection_name.lower()):
    print(f"Collection '{this_collection.title}' found.")
else:
    print(f"Collection '{collection_name}' not found.")
    sys.exit(1)
 
matches_found = False
for video in plex_section.all():
    #print(f"Checking video '{video.title}' for pattern '{pattern}'...")
    skip_non_indie = False
    if indie_content and " (Scene #" in video.title and pattern.lower() in video.title.lower():
        skip_non_indie = True
        print(f"Skipping non-indie content match '{video.title}'")
    if not skip_non_indie and pattern.lower() in video.title.lower():
        matches_found = True
        found_collection = False
        if video.collections:
            for collection in video.collections:
                if str(collection).lower() == collection_name.lower():
                    found_collection = True
        if found_collection:
            print(f"'{video.title}' needs to be removed from '{this_collection.title}'")
            this_collection.removeItems(video)
            print(f"'{video.title}' has been removed from {this_collection.title}")
if not matches_found:
    print(f"No matches found for pattern '{pattern}'")
