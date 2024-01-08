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
    print(f"Usage: {os.path.basename(__file__)} <source collection name> <target collection name>")
    sys.exit(1)
source_studio_name = sys.argv[1]
target_collection_name = sys.argv[2]
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
target_collection = plex_section.collection(target_collection_name)
if (str(target_collection.title).lower() == target_collection_name.lower()):
    print(f"{bcolors.OKGREEN}Target collection '{target_collection.title}' found.{bcolors.ENDC}")
    print("")
else:
    print(f"{bcolors.FAIL}Target collection '{target_collection_name}' not found!{bcolors.ENDC}")
    sys.exit(1)

matches_found = 0
collections_added = 0
for video in plex_section.all():
    #print(f"Checking video '{video.title}'...")
    # ensure data is up to date
    video.reload()
    if video.studio != None and video.studio.lower() == source_studio_name.lower():
        matches_found += 1
        found_collection = False
        if video.collections:
            for collection in video.collections:
                if str(collection) == target_collection.title:
                    found_collection = True
        if not found_collection:
            print(f"{bcolors.WARNING}'{video.title}' needs to be added to '{target_collection.title}'{bcolors.ENDC}")
            target_collection.addItems(video)
            collections_added += 1
            print(f"{bcolors.OKGREEN}'{video.title}' has been added to {target_collection.title}{bcolors.ENDC}")
            # print(f"{bcolors.OKGREEN}'{video.title}' has been added to {this_collection.title} (sleeping for {sleep_interval}s...){bcolors.ENDC}")
            # time.sleep(sleep_interval) # introduce a delay to avoid hammering the server
        else:
            print(f"{bcolors.OKCYAN}'{video.title}' is already part of '{target_collection.title}'{bcolors.ENDC}")
    # else:
    #     print(f"{bcolors.OKCYAN}{video.title} is a member of studio '{video.studio}', skipping.{bcolors.ENDC}")

if matches_found == 0:
    print("")
    print(f"{bcolors.FAIL}No items found for studio '{source_studio_name.title}'!{bcolors.ENDC}")
    print("")
else:
    print("")
    print(f"{bcolors.OKCYAN}{matches_found} matches found, {collections_added} collections added.{bcolors.ENDC}")
    print("")
