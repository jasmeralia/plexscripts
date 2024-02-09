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
# format summary info
#
def getSummaryString(collectionsUnchanged, collectionsAdded, collectionsRemoved):
    return f"({collectionsUnchanged} unchanged, {collectionsAdded} added, {collectionsRemoved} removed)"
#
# Sanity check CLI arguments and assign them to readable variable names
#
if len(sys.argv) != 2:
    print(f"Usage: {os.path.basename(__file__)} <unrated collection name>")
    sys.exit(1)
collectionName = sys.argv[1]
print(f"Collection: {collectionName}")
print('')
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
collectionsRemoved = 0
collectionsUnchanged = 0
videosRated = 0
videosUnrated = 0
videoCount = 0
print(f"Checking for unrated videos not in collection '{thisCollection.title}'...")
print('')
searchFilters = {
    'and': [
        {'userRating': -1},
        {'collection!': thisCollection.title}
    ]
}
results = plexSection.search(filters=searchFilters, sort="titleSort")
resultsCount = len(results)
print(f"{bcolors.OKCYAN}Found {resultsCount} unrated videos not in collection '{thisCollection.title}':{bcolors.ENDC}")
matchCount = 0
for video in results:
    # ensure data is up to date
    if video.isPartialObject():
        video.reload()
    matchCount += 1
    collectionsAdded += 1
    progressStr = f"[{matchCount}/{resultsCount}] "
    print(f"{bcolors.WARNING}{progressStr}'{video.title}' needs to be added to '{thisCollection.title}'{bcolors.ENDC}")
    thisCollection.addItems(video)
    print(f"{bcolors.OKGREEN}{progressStr}'{video.title}' has been added to '{thisCollection.title}'{bcolors.ENDC}")

print('')
print(f"Checking for rated videos present in collection '{thisCollection.title}'...")
searchFilters = {
    'and': [
        {'userRating>>': 0},
        {'collection=': thisCollection.title}
    ]
}
results = plexSection.search(filters=searchFilters, sort="titleSort")
resultsCount = len(results)
matchCount = 0
print(f"{bcolors.OKCYAN}Found {resultsCount} rated videos in collection '{thisCollection.title}':{bcolors.ENDC}")
for video in results:
    # ensure data is up to date
    if video.isPartialObject():
        video.reload()
    matchCount += 1
    collectionsRemoved += 1
    progressStr = f"[{matchCount}/{resultsCount}] "
    print(f"{bcolors.WARNING}{progressStr}'{video.title}' needs to be removed from collection '{thisCollection.title}'!{bcolors.ENDC}")
    thisCollection.removeItems(video)
    print(f"{bcolors.OKGREEN}{progressStr}'{video.title}' has been removed from {thisCollection.title}{bcolors.ENDC}")

print('')
print(f"{bcolors.OKCYAN}{collectionsAdded} collections added.{bcolors.ENDC}")
print(f"{bcolors.OKCYAN}{collectionsRemoved} collections removed.{bcolors.ENDC}")
print('')
