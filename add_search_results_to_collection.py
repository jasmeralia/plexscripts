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
    print(f"Usage: {os.path.basename(__file__)} <collection name> <search pattern>")
    sys.exit(1)
collectionName = sys.argv[1]
pattern = sys.argv[2]
print(f"Pattern: '{pattern}'")
print('')
# print(f"Collection: {collectionName}")
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
# Given a list of writers, build a Plex search filter
#
def writerListToSearchFilter(writerList):
    searchList = []
    for writerName in writerList:
        searchList.append({'writer': writerName})
    return {'or': searchList}
#
# Generate a search filter based on the pattern, excluding
# where the video is already part of the collection to improve
# speed of rerunning the script.
#
def generateFilters(pattern, collectionName):
    filterList = {
        'and': [
            {'collection!': collectionName},
            {'title': pattern}
        ]
    }
    return filterList
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
thisCollection = plexSection.collection(collectionName)
if str(thisCollection.title).lower() == collectionName.lower():
    print(f"{bcolors.OKGREEN}Collection '{thisCollection.title}' found.{bcolors.ENDC}")
    print('')
else:
    print(f"{bcolors.FAIL}Collection '{collectionName}' not found!{bcolors.ENDC}")
    sys.exit(1)

print('')
matchesFoundCount = 0
collectionsAddedCount = 0
# collectionsAlreadySetCount = 0
searchFilters = generateFilters(pattern, thisCollection.title)
print(f"{bcolors.OKCYAN}Search filters: {bcolors.OKGREEN}{searchFilters}\n{bcolors.ENDC}")

results = plexSection.search(filters=searchFilters, sort="titleSort")
resultsCount = len(results)
print(f"{bcolors.OKCYAN}Found {resultsCount} search matches:{bcolors.ENDC}")
for video in results:
    matchesFoundCount += 1
    # ensure data is up to date
    if video.isPartialObject():
        video.reload()
    foundCollection = False
    progressStr = f"[{matchesFoundCount}/{resultsCount}] "

    if video.collections:
        for collection in video.collections:
            if str(collection).lower() == collectionName.lower():
                foundCollection = True
    if not foundCollection:
        print(f"{bcolors.WARNING}{progressStr}'{video.title}' needs to be added to '{thisCollection.title}'{bcolors.ENDC}")
        thisCollection.addItems(video)
        collectionsAddedCount += 1
        print(f"{bcolors.OKGREEN}{progressStr}'{video.title}' has been added to {thisCollection.title}{bcolors.ENDC}")
        # print(f"{bcolors.OKGREEN}'{video.title}' has been added to {thisCollection.title} (sleeping for {sleepInterval}s...){bcolors.ENDC}")
        # time.sleep(sleepInterval) # introduce a delay to avoid hammering the server
        foundCollection = True
    # else:
    #     print(f"{bcolors.OKCYAN}{progressStr}'{video.title}' is already part of '{thisCollection.title}'{bcolors.ENDC}")
    #     foundCollection = True
    #     collectionsAlreadySetCount += 1

if matchesFoundCount == 0:
    print('')
    print(f"{bcolors.FAIL}No matches found!{bcolors.ENDC}")
    print('')
else:
    print('')
    print(f"{bcolors.HEADER}{matchesFoundCount} matches found.{bcolors.ENDC}")
    # print(f"{bcolors.OKGREEN}{collectionsAlreadySetCount} collections already set.{bcolors.ENDC}")
    print(f"{bcolors.OKCYAN}{collectionsAddedCount} collections added.{bcolors.ENDC}")
    print('')
