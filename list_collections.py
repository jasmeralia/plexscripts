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
collectionCount = len(plexSection.collections())
collectionSmartCount = 0
collectionEmptyCount = 0
collectionSortChange = 0
for collection in plexSection.collections():
    if searchPattern == "" or searchPattern.lower() in collection.title.lower():
        # ensure the data is up to date if needed
        if collection.isPartialObject():
            collection.reload()
        print("%4d: %s" % (collection.childCount, collection.title))
        if collection.collectionSort != 1 and not collection.smart:
            currentTime = datetime.now().strftime("%H:%M:%S")
            print(f"{bcolors.WARNING}[{currentTime}] Updated collection sort method to alphabetical.{bcolors.ENDC}")
            collection.sortUpdate(sort="alpha")
            collectionSortChange += 1
        if collection.childCount == 0:
            collectionEmptyCount += 1
        if collection.smart:
            collectionSmartCount += 1
            # print(f"Smart collection filters: '{pprint(collection.content)}'")

currentTime = datetime.now().strftime("%H:%M:%S")
print('')
print(f"{bcolors.OKCYAN}[{currentTime}] Total number of collections: {collectionCount}{bcolors.ENDC}")
print(f"{bcolors.OKGREEN}[{currentTime}] Total number of smart collections: {collectionSmartCount}{bcolors.ENDC}")
print(f"{bcolors.WARNING}[{currentTime}] Total number of collections changed sorting on: {collectionSortChange}{bcolors.ENDC}")
print(f"{bcolors.FAIL}[{currentTime}] Total number of empty collections: {collectionEmptyCount}{bcolors.ENDC}")
