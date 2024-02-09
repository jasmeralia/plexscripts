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
collectionName = sys.argv[1]
pattern = sys.argv[2]
print(f"Pattern   : '{pattern}'")
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

matchesFoundCount = 0
collectionsAddedCount = 0
collectionsAlreadySetCount = 0
for video in plexSection.all():
    # not all pattern matches will actually match the writer, but this eliminates the overhead of doing reload() on every single video...
    if pattern.lower() in video.title.lower():
        # ensure data is up to date
        video.reload()
        for writer in video.writers:
            # print(f"Comparing '{str(writer)}' against '{pattern}' on '{video.title}'")
            if str(writer).lower() == pattern.lower():
                # print(f"Match found for '{pattern}' in '{video.title}'")
                matchesFoundCount += 1
                foundCollection = False
                if video.collections:
                    for collection in video.collections:
                        if str(collection).lower() == collectionName.lower():
                            foundCollection = True
                if not foundCollection:
                    print(f"{bcolors.WARNING}'{video.title}' needs to be added to '{thisCollection.title}'{bcolors.ENDC}")
                    thisCollection.addItems(video)
                    collectionsAddedCount += 1
                    print(f"{bcolors.OKGREEN}'{video.title}' has been added to {thisCollection.title}{bcolors.ENDC}")
                    # print(f"{bcolors.OKGREEN}'{video.title}' has been added to {thisCollection.title} (sleeping for {sleepInterval}s...){bcolors.ENDC}")
                    # time.sleep(sleepInterval) # introduce a delay to avoid hammering the server
                else:
                    print(f"{bcolors.OKCYAN}'{video.title}' is already part of '{thisCollection.title}'{bcolors.ENDC}")
                    collectionsAlreadySetCount += 1

if matchesFoundCount == 0:
    print('')
    print(f"{bcolors.FAIL}No writer matches found for pattern '{pattern}'!{bcolors.ENDC}")
    print('')
else:
    print('')
    print(f"{bcolors.HEADER}{matchesFoundCount} writer matches found.{bcolors.ENDC}")
    print(f"{bcolors.OKGREEN}{collectionsAlreadySetCount} collections already set.{bcolors.ENDC}")
    print(f"{bcolors.OKCYAN}{collectionsAddedCount} collections added.{bcolors.ENDC}")
    print('')
