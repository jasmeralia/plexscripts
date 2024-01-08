#!/usr/bin/env python3
#
# import modules
#
import configparser
import sys
import os
from pprint import pprint
from plexapi.server import PlexServer
from datetime import datetime
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
studio_empty_count = 0
studio_count = 0
studio_set = set()
collections_already_created = 0
collections_newly_created = 0
current_time = datetime.now().strftime("%H:%M:%S")
start_time = datetime.now()
print(f"{bcolors.OKGREEN}[{current_time}] Collecting list of studios...{bcolors.ENDC}")
for video in plex_section.all():
    # ensure the data is up to date
    video.reload()
    if video.studio == None or video.studio == '':
        studio_empty_count += 1
    else:
        studio_set.add(video.studio)
studio_count = len(studio_set)
current_time = datetime.now().strftime("%H:%M:%S")
elapsed = datetime.now() - start_time
print(f"{bcolors.OKGREEN}[{current_time}] Studio scanning completed in {elapsed}.{bcolors.ENDC}")
print(f"[{current_time}] Total studios: {studio_count}")
print(f"[{current_time}] Total empty studios: {studio_empty_count}")
print("")

collection_global_set = set()
collection_count = 0
start_time = datetime.now()
for collection in plex_section.collections():
    collection_global_set.add(f"{collection.title}")
    collection_count += 1
current_time = datetime.now().strftime("%H:%M:%S")
elapsed = datetime.now() - start_time
print(f"{bcolors.OKGREEN}[{current_time}] Collection scanning completed in {elapsed}.{bcolors.ENDC}")
print(f"[{current_time}] Total collections: {collection_count}")
print("")

for studioName in sorted(studio_set):
    studioFilters = {"studio": studioName}
    if studioName == 'Independent Content':
        studioTitle = f"02: {studioName}"
    else:
        studioTitle = f"02: Studio: {studioName}"
    # print(f"Checking if '{studioTitle}' collection already exists...")
    collection_found = False
    for collection in collection_global_set:
        # print(f"Comparing '{collection.title.lower()}' against '{studioTitle.lower()}'")
        if collection.lower() == studioTitle.lower():
            # print(f"{bcolors.OKCYAN}Collection match found!{bcolors.ENDC}")
            collection_found = True
    if collection_found:
        collections_already_created += 1
        # print(f"{bcolors.OKCYAN}Collection '{studioTitle}' already exists, skipping.{bcolors.ENDC}")
    else:
        current_time = datetime.now().strftime("%H:%M:%S")
        print(f"{bcolors.WARNING}[{current_time}] Creating smart collection '{studioTitle}'{bcolors.ENDC}")
        plex_section.createCollection(title=studioTitle, smart=True, sort="titleSort:asc", filters=studioFilters)
        current_time = datetime.now().strftime("%H:%M:%S")
        print(f"{bcolors.OKGREEN}[{current_time}] Created smart collection '{studioTitle}'{bcolors.ENDC}")
        collections_newly_created += 1

print("")
current_time = datetime.now().strftime("%H:%M:%S")
print(f"{bcolors.OKCYAN}[{current_time}] Existing smart collections: {collections_already_created}{bcolors.ENDC}")
print(f"{bcolors.OKGREEN}[{current_time}] Newly created smart collections: {collections_newly_created}{bcolors.ENDC}")
print("")
