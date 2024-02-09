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
sourceStudioName = sys.argv[1]
targetCollectionName = sys.argv[2]
#print(f"Collection: {collectionName}")
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
sleepInterval = 10
#
# Connect to server
#
plex = PlexServer(baseurl, plexToken)
#
# Select section
#
plexSection = plex.library.section(plexSectionName)
targetCollection = plexSection.collection(targetCollectionName)
if str(targetCollection.title).lower() == targetCollectionName.lower():
    print(f"{bcolors.OKGREEN}Target collection '{targetCollection.title}' found.{bcolors.ENDC}")
    print('')
else:
    print(f"{bcolors.FAIL}Target collection '{targetCollectionName}' not found!{bcolors.ENDC}")
    sys.exit(1)

searchFilters = {
    'and': [
        {'studio': sourceStudioName},
        {'collection!': targetCollection.title}
    ]
}
results = plexSection.search(filters=searchFilters, sort="titleSort")
print(f"Copying from {sourceStudioName} to {targetCollectionName} via filter {searchFilters}")
matchesFound = len(results)
matchCount = 0
collectionsAdded = 0
for video in results:
    #print(f"Checking video '{video.title}'...")
    # ensure data is up to date
    if video.isPartialObject():
        video.reload()

    foundCollection = False
    matchCount += 1
    progressStr = f"[{matchCount}/{matchesFound}] "
    if video.collections:
        for collection in video.collections:
            if str(collection) == targetCollection.title:
                foundCollection = True
    if not foundCollection:
        print(f"{bcolors.WARNING}{progressStr}'{video.title}' needs to be added to '{targetCollection.title}'{bcolors.ENDC}")
        targetCollection.addItems(video)
        collectionsAdded += 1
        print(f"{bcolors.OKGREEN}{progressStr}'{video.title}' has been added to {targetCollection.title}{bcolors.ENDC}")
    else:
        print(f"{bcolors.OKCYAN}{progressStr}'{video.title}' is already part of '{targetCollection.title}'{bcolors.ENDC}")

if matchesFound == 0:
    print('')
    print(f"{bcolors.FAIL}No items found for studio '{sourceStudioName}' that are not already in '{targetCollection.title}'!{bcolors.ENDC}")
    print('')
else:
    print('')
    print(f"{bcolors.OKCYAN}{matchesFound} matches found, {collectionsAdded} collections added.{bcolors.ENDC}")
    print('')
