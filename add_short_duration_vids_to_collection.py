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
# Sanity check CLI arguments and assign them to readable variable names
#
if len(sys.argv) != 2:
    print(f"Usage: {os.path.basename(__file__)} <collection name>")
    sys.exit(1)
collectionName = sys.argv[1]
print(f"Collection: {collectionName}")
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
thisCollection = plexSection.collection(collectionName)
collectionsAdded = 0
matchesFound = 0
if str(thisCollection.title).lower() == collectionName.lower():
    results = plexSection.search(filters={"duration<<": 90000}, sort="titleSort")
    for video in results:
        foundCollection = False
        matchesFound += 1
        if video.collections:
            # ensure data is up to date
            video.reload()
            for collection in video.collections:
                # print(f"Checking collection '{collection}' vs '{collectionName}'...")
                if str(collection).lower() == collectionName.lower():
                    # print(f"Collection {collection} matches {collectionName}!")
                    foundCollection = True
        if foundCollection:
            print(f"{bcolors.OKCYAN}'{video.title}' is already part of '{thisCollection.title}'{bcolors.ENDC}")
        else:
            print(f"{bcolors.WARNING}'{video.title}' needs to be added to '{thisCollection.title}'{bcolors.ENDC}")
            thisCollection.addItems(video)
            collectionsAdded += 1
            print(f"{bcolors.OKGREEN}'{video.title}' has been added to {thisCollection.title}{bcolors.ENDC}")
    if matchesFound == 0:
        print('')
        print(f"{bcolors.FAIL}No matches found!{bcolors.ENDC}")
        print('')
    else:
        print('')
        print(f"{bcolors.OKCYAN}{matchesFound} matches found, {collectionsAdded} collections added.{bcolors.ENDC}")
        print('')
else:
    print("Collection not found.")
