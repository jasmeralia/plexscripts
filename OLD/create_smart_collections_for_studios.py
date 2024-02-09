#!/usr/bin/env python3
#
# import modules
#
import configparser
import sys
import os
from datetime import datetime
from pprint import pprint
from plexapi.server import PlexServer
#
# Check CLI arguments
#
if len(sys.argv) == 2:
    searchPattern = sys.argv[1]
else:
    searchPattern = ''
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
plexHost = config['default']['plexHost']
plexPort = config['default']['plexPort']
plexSection = config['default']['plexSection']
plexToken = config['default']['plexToken']
plexSectionName = config['default']['plexSectionName']
baseurl = f"http://{plexHost}:{plexPort}"
#
# Connect to server
#
plex = PlexServer(baseurl, plexToken)
#
# Select section
#
plexSection = plex.library.section(plexSectionName)
studioEmptyCount = 0
studioCount = 0
studioSet = set()
collectionsAlreadyCreated = 0
collectionsNewlyCreated = 0
currentTime = datetime.now().strftime("%H:%M:%S")
startTime = datetime.now()
print(f"{bcolors.OKGREEN}[{currentTime}] Collecting list of studios...{bcolors.ENDC}")
for video in plexSection.all():
    # ensure the data is up to date
    video.reload()
    if video.studio is None or video.studio == '':
        studioEmptyCount += 1
    else:
        studioSet.add(video.studio)
studioCount = len(studioSet)
currentTime = datetime.now().strftime("%H:%M:%S")
elapsed = datetime.now() - startTime
print(f"{bcolors.OKGREEN}[{currentTime}] Studio scanning completed in {elapsed}.{bcolors.ENDC}")
print(f"[{currentTime}] Total studios: {studioCount}")
print(f"[{currentTime}] Total empty studios: {studioEmptyCount}")
print('')

collectionGlobalSet = set()
collectionCount = 0
startTime = datetime.now()
for collection in plexSection.collections():
    collectionGlobalSet.add(f"{collection.title}")
    collectionCount += 1
currentTime = datetime.now().strftime("%H:%M:%S")
elapsed = datetime.now() - startTime
print(f"{bcolors.OKGREEN}[{currentTime}] Collection scanning completed in {elapsed}.{bcolors.ENDC}")
print(f"[{currentTime}] Total collections: {collectionCount}")
print('')

for studioName in sorted(studioSet):
    studioFilters = {"studio": studioName}
    if studioName == 'Independent Content':
        studioTitle = f"02: {studioName}"
    else:
        studioTitle = f"02: Studio: {studioName}"
    # print(f"Checking if '{studioTitle}' collection already exists...")
    collectionFound = False
    for collection in collectionGlobalSet:
        # print(f"Comparing '{collection.title.lower()}' against '{studioTitle.lower()}'")
        if collection.lower() == studioTitle.lower():
            # print(f"{bcolors.OKCYAN}Collection match found!{bcolors.ENDC}")
            collectionFound = True
    if collectionFound:
        collectionsAlreadyCreated += 1
        # print(f"{bcolors.OKCYAN}Collection '{studioTitle}' already exists, skipping.{bcolors.ENDC}")
    else:
        currentTime = datetime.now().strftime("%H:%M:%S")
        print(f"{bcolors.WARNING}[{currentTime}] Creating smart collection '{studioTitle}'{bcolors.ENDC}")
        plexSection.createCollection(title=studioTitle, smart=True, sort="titleSort:asc", filters=studioFilters)
        currentTime = datetime.now().strftime("%H:%M:%S")
        print(f"{bcolors.OKGREEN}[{currentTime}] Created smart collection '{studioTitle}'{bcolors.ENDC}")
        collectionsNewlyCreated += 1

print('')
currentTime = datetime.now().strftime("%H:%M:%S")
print(f"{bcolors.OKCYAN}[{currentTime}] Existing smart collections: {collectionsAlreadyCreated}{bcolors.ENDC}")
print(f"{bcolors.OKGREEN}[{currentTime}] Newly created smart collections: {collectionsNewlyCreated}{bcolors.ENDC}")
print('')
