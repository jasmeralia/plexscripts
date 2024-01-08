#!/usr/bin/env python3
#
# import modules
#
import configparser
import sys
import os
import time
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
if collection_name == '01: Category: Solo':
    solo_content = True
else:
    solo_content = False

print(f"Pattern: '{pattern}'")
#print(f"Collection: {collection_name}")
#
# Color support
#
class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
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
sleep_interval = 10
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
    print(f"{bcolors.OKGREEN}Collection '{this_collection.title}' found.{bcolors.ENDC}")
    print("")
else:
    print(f"{bcolors.FAIL}Collection '{collection_name}' not found!{bcolors.ENDC}")
    sys.exit(1)
 
matches_found = 0
collections_added = 0
for video in plex_section.all():
    #print(f"Checking video '{video.title}' for pattern '{pattern}'...")
    skip_scene_content = False
    if (indie_content or solo_content) and " (Scene #" in video.title and pattern.lower() in video.title.lower():
        skip_scene_content = True
        print(f"{bcolors.OKCYAN}Skipping scene content match '{video.title}'{bcolors.ENDC}")
    if not skip_scene_content and pattern.lower() in video.title.lower():
        # ensure data is up to date
        video.reload()
        matches_found += 1
        found_collection = False
        skip_solo_content = False
        if video.collections:
            for collection in video.collections:
                if str(collection).lower() == collection_name.lower():
                    found_collection = True
                elif solo_content and str(collection) == '01: Category: Non-Sexual'.lower():
                    skip_solo_content = True
        if skip_solo_content:
            print(f"{bcolors.WARNING}Skipping non-sexual solo content '{video.title}'{bcolors.ENDC}")
        elif not found_collection:
            print(f"{bcolors.WARNING}'{video.title}' needs to be added to '{this_collection.title}'{bcolors.ENDC}")
            this_collection.addItems(video)
            collections_added += 1
            print(f"{bcolors.OKGREEN}'{video.title}' has been added to {this_collection.title}{bcolors.ENDC}")
            # print(f"{bcolors.OKGREEN}'{video.title}' has been added to {this_collection.title} (sleeping for {sleep_interval}s...){bcolors.ENDC}")
            # time.sleep(sleep_interval) # introduce a delay to avoid hammering the server
        else:
            print(f"{bcolors.OKCYAN}'{video.title}' is already part of '{this_collection.title}'{bcolors.ENDC}")
if matches_found == 0:
    print("")
    print(f"{bcolors.FAIL}No matches found for pattern '{pattern}'!{bcolors.ENDC}")
    print("")
else:
    print("")
    print(f"{bcolors.OKCYAN}{matches_found} matches found, {collections_added} collections added.{bcolors.ENDC}")
    print("")
