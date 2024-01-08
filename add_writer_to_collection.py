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
    print(f"Usage: {os.path.basename(__file__)} <collection nane> <pattern match>")
    sys.exit(1)
collection_name = sys.argv[1]
pattern = sys.argv[2]
print(f"Pattern   : '{pattern}'")
# print(f"Collection: {collection_name}")
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

matches_found_count = 0
collections_added_count = 0
collections_already_set_count = 0
for video in plex_section.all():
    # not all pattern matches will actually match the writer, but this eliminates the overhead of doing reload() on every single video...
    if pattern.lower() in video.title.lower():
        # ensure data is up to date
        video.reload()
        for writer in video.writers:
            # print(f"Comparing '{str(writer)}' against '{pattern}' on '{video.title}'")
            if str(writer).lower() == pattern.lower():
                # print(f"Match found for '{pattern}' in '{video.title}'")
                matches_found_count += 1
                found_collection = False
                if video.collections:
                    for collection in video.collections:
                        if str(collection).lower() == collection_name.lower():
                            found_collection = True
                if not found_collection:
                    print(f"{bcolors.WARNING}'{video.title}' needs to be added to '{this_collection.title}'{bcolors.ENDC}")
                    this_collection.addItems(video)
                    collections_added_count += 1
                    print(f"{bcolors.OKGREEN}'{video.title}' has been added to {this_collection.title}{bcolors.ENDC}")
                    # print(f"{bcolors.OKGREEN}'{video.title}' has been added to {this_collection.title} (sleeping for {sleep_interval}s...){bcolors.ENDC}")
                    # time.sleep(sleep_interval) # introduce a delay to avoid hammering the server
                else:
                    print(f"{bcolors.OKCYAN}'{video.title}' is already part of '{this_collection.title}'{bcolors.ENDC}")
                    collections_already_set_count += 1

if matches_found_count == 0:
    print("")
    print(f"{bcolors.FAIL}No writer matches found for pattern '{pattern}'!{bcolors.ENDC}")
    print("")
else:
    print("")
    print(f"{bcolors.HEADER}{matches_found_count} writer matches found.{bcolors.ENDC}")
    print(f"{bcolors.OKGREEN}{collections_already_set_count} collections already set.{bcolors.ENDC}")
    print(f"{bcolors.OKCYAN}{collections_added_count} collections added.{bcolors.ENDC}")
    print("")
