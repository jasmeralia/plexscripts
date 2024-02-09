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
if len(sys.argv) != 2:
    print(f"Usage: {os.path.basename(__file__)} <filename of writers>")
    sys.exit(1)
fileName = sys.argv[1]
if not os.path.isfile(fileName):
    print(f"Error: {fileName} is not readable!")
    sys.exit(1)
print(f"Filename: '{fileName}'")
fileHandle = open(fileName, 'r', encoding="utf-8")
fileData = fileHandle.read()
writerList = fileData.split("\n")
writerCount = len(writerList)
print(f"Imported {writerCount} writers to set as independent content creators.")
print('')
studioName = "Independent Content"
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
matchesFoundCount = 0
studiosAddedCount = 0
studiosAlreadyMatchCount = 0
studiosSkippedCount = 0
#
# Search for empty studio videos only, as we don't want to iterate over the whole section,
# and we don't support overriding the current value if present, so just iterate through the
# videos where it is not currently set.
#
# If we add support to override later on, we can parameterize the search query appropriately.
#
results = plexSection.search(studio__exact='', sort="titleSort")
for video in results:
    # not all pattern matches will actually match one of the writers, but this eliminates the overhead of doing reload() on every single video...
    foundWriterMatch = False
    for writerName in writerList:
        if writerName.lower() in video.title.lower():
            foundWriterMatch = True
    #print(f"Checking video '{video.title}' for pattern '{pattern}'...")
    if foundWriterMatch:
        # ensure data is up to date
        if video.isPartialObject():
            video.reload()
        matchesFoundCount += 1
        if " (Scene #" in video.title:
            print(f"{bcolors.WARNING}'{video.title}' is not an indie video, skipping!{bcolors.ENDC}")
            studiosSkippedCount += 1
        else:
            if video.studio is None or video.studio == '':
                print(f"{bcolors.WARNING}'{video.title}' needs to be added to '{studioName}'{bcolors.ENDC}")
                video.edit(**{"studio.value": studioName, 'label.locked': 1})
                studiosAddedCount += 1
                print(f"{bcolors.OKGREEN}'{video.title}' has been added to {studioName}{bcolors.ENDC}")
            elif video.studio == studioName:
                print(f"{bcolors.OKCYAN}'{video.title}' is already part of '{studioName}'{bcolors.ENDC}")
                studiosAlreadyMatchCount += 1

if matchesFoundCount == 0:
    print('')
    print(f"{bcolors.FAIL}No writer matches found!{bcolors.ENDC}")
    print('')
else:
    print('')
    print(f"{bcolors.HEADER}{matchesFoundCount} writer matches found.{bcolors.ENDC}")
    print(f"{bcolors.OKGREEN}{studiosAlreadyMatchCount} videos already flagged as indie.{bcolors.ENDC}")
    print(f"{bcolors.OKCYAN}{studiosAddedCount} videos flagged as indie.{bcolors.ENDC}")
    print(f"{bcolors.WARNING}{studiosSkippedCount} videos were skipped due to being industry content!{bcolors.ENDC}")
    print('')
