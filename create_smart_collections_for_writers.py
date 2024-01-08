#!/usr/bin/env python3
#-*- coding: utf-8 -*-
#
# import modules
#
import configparser
import sys
import os
import time
from pprint import pprint
from plexapi.server import PlexServer
from datetime import datetime
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
current_time = datetime.now().strftime("%H:%M:%S")
start_time = datetime.now()
print(f"{bcolors.OKGREEN}[{current_time}] Collecting list of writers...{bcolors.ENDC}")
writer_global_set = set()
title_count = 0
collections_already_created = 0
collections_newly_created = 0
bad_writer_names = 0
for video in plex_section.all():
    # ensure data is up to date
    video.reload()
    title_count += 1
    for writer in video.writers:
        writer_global_set.add(f"{writer}".strip())

writer_global_count = len(writer_global_set)
current_time = datetime.now().strftime("%H:%M:%S")
elapsed = datetime.now() - start_time
print(f"{bcolors.OKGREEN}[{current_time}] Writer scanning completed in {elapsed}.{bcolors.ENDC}")
print(f"[{current_time}] Total titles: {title_count}")
print(f"[{current_time}] Total individual writers: {writer_global_count}")
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

# pprint(sorted(writer_global_set))
# sys.exit(1)
for writerName in sorted(writer_global_set):
    writerFilters = {"writer": writerName}
    writerTitle = f"03: Star: {writerName}"
    # print(f"Checking if '{writerTitle}' collection already exists...")
    collection_found = False
    for collection in collection_global_set:
        # print(f"Comparing '{collection.title.lower()}' against '{writerTitle.lower()}'")
        if collection.lower() == writerTitle.lower():
            # print(f"{bcolors.OKCYAN}Collection match found!{bcolors.ENDC}")
            collection_found = True
    if collection_found:
        collections_already_created += 1
        # print(f"{bcolors.OKCYAN}Collection {writerTitle} already exists, skipping.{bcolors.ENDC}")
    else:
        current_time = datetime.now().strftime("%H:%M:%S")
        print(f"{bcolors.WARNING}[{current_time}] Creating smart collection '{writerTitle}'{bcolors.ENDC}")
        plex_section.createCollection(title=writerTitle, smart=True, sort="titleSort:asc", filters=writerFilters)
        current_time = datetime.now().strftime("%H:%M:%S")
        print(f"{bcolors.OKGREEN}[{current_time}] Created smart collection '{writerTitle}'{bcolors.ENDC}")
        collections_newly_created += 1

print("")
current_time = datetime.now().strftime("%H:%M:%S")
print(f"{bcolors.OKCYAN}[{current_time}] Existing smart collections: {collections_already_created}{bcolors.ENDC}")
print(f"{bcolors.OKGREEN}[{current_time}] Newly created smart collections: {collections_newly_created}{bcolors.ENDC}")
print("")
