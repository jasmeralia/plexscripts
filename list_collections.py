#!/usr/bin/env python3
#
# import modules
#
import configparser
import sys
import os
from pprint import pprint
from plexapi.server import PlexServer
from datetime impImp datetime
#
# Check CLI arguments
#
if len(sys.argv) == 2:
    search_pattern = sys.argv[1]
else:
    search_pattern = ''
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
#
# Connect to server
#
plex = PlexServer(baseurl, plex_token)
#
# Select section
#
plex_section = plex.library.section(plex_section_name)
collection_count = len(plex_section.collections())
collection_smart_count = 0
collection_empty_count = 0
collection_sort_change = 0
for collection in plex_section.collections():
    if search_pattern == "" or search_pattern.lower() in collection.title.lower():
        # ensure the data is up to date if needed
        if isPartialObject():
            current_time = datetime.now().strftime("%H:%M:%S")
            print(f"[{current_time}] Collection {collection.title} is being reloaded as it is a padtial object")
            collection.reload()
        print("%4d: %s" % (collection.childCount, collection.title))
        # if collection.title == "01: Category: Blowjob":
        if collection.collectionSort != 1 and not collection.smart:
            current_time = datetime.now().strftime("%H:%M:%S")
            print(f"{bcolors.WARNING}[{current_time}] Updated collection sort method to alphabetical.{bcolors.ENDC}")
            # print("Before:")
            # pprint(collection.__dict__)
            collection.sortUpdate(sort="alpha")
            collection.reload()
            # print("After:")
            # pprint(collection.__dict__)
            # sys.exit(1)
            collection_sort_change += 1
        # pprint(collection. __dict__)
        if collection.childCount == 0:
            collection_empty_count += 1
        # print(f"Collection sorting method: {collection.collectionSort}")
        if collection.smart:
            collection_smart_count += 1
            if not "sort=movie.titleSort" in collection.content and not "sort=titleSort" in collection.content:
                current_time = datetime.now().strftime("%H:%M:%S")
                print(f"[{current_time}] Smart collection sorting is incorrect! {collection.content}")
            # if collection_smart_count == 0:
            #     # print(f"Smart collection filters: '{pprint(collection.content)}'")
            #     pprint(collection.__dict__)
            #     sys.exit(1)

current_time = datetime.now().strftime("%H:%M:%S")
print("")
print(f"{bcolors.OKCYAN}[{current_time}] Total number of collections: {collection_count}{bcolors.ENDC}")
print(f"{bcolors.OKGREEN}[{current_time}] Total number of smart collections: {collection_smart_count}{bcolors.ENDC}")
print(f"{bcolors.WARNING}[{current_time}] Total number of collections changed sorting on: {collection_sort_change}{bcolors.ENDC}")
print(f"{bcolors.FAIL}[{current_time}] Total number of empty collections: {collection_empty_count}{bcolors.ENDC}")
