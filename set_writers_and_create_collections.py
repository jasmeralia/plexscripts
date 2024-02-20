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
writerGlobalSet = set()
writerAppearanceCount = 0
writerMissingCount = 0
writerAlreadySetCount = 0
badWriterNames = 0
titleCount = 0
collectionsAlreadyCreated = 0
collectionsNewlyCreated = 0
results = plexSection.all()
totalVideoCount = len(results)
#
# Scan all videos and build lists of studios and writers
#
currentTime = datetime.now().strftime("%H:%M:%S")
startTime = datetime.now()
print(f"{bcolors.OKGREEN}[{currentTime}] Collecting list of studios and writers...{bcolors.ENDC}")
for video in results:
    titleCount += 1
    # ensure data is up to date
    if video.isPartialObject():
        video.reload()
    progressString = f"[{titleCount}/{totalVideoCount}] "
    # replace nbsp; with space and emdash with hyphen... fuck utf8!
    thisTitle = video.title.replace(" – ", " - ").replace("\xa0", " ")
    writerNames = thisTitle.split(' - ', 1)[0]
    writersList = writerNames.split(',')
    strippedSet = set()
    someWritersMissing = False
    for writerName in writersList:
        strippedName = writerName.strip()
        strippedSet.add(strippedName)
        # print(f"Found writer: {writerName}")
        writerGlobalSet.add(strippedName)
        writerAppearanceCount += 1
        writerAlreadySet = False
        for thiswriter in video.writers:
            if f"{thiswriter}".lower() == strippedName.lower():
                writerAlreadySet = True
        if writerAlreadySet:
            # print(f"{bcolors.OKGREEN}Writer '{strippedName}' already set on this title.{bcolors.ENDC}")
            writerAlreadySetCount += 1
        else:
            print(f"{bcolors.WARNING}{progressString}Writer '{strippedName}' not yet set on {video.title}, need to add it!{bcolors.ENDC}")
            writerMissingCount += 1
            someWritersMissing = True
    if someWritersMissing:
        print(f"{bcolors.WARNING}{progressString}List extracted from title: ", end="")
        pprint(sorted(strippedSet))
        print(f"{bcolors.OKCYAN}{progressString}Current list in Plex: ", end="")
        pprint(video.writers)
        print(f"{bcolors.WARNING}{progressString}Updating list...{bcolors.ENDC}")
        video.addWriter(sorted(strippedSet), True)
        print(f"{bcolors.OKGREEN}{progressString}Writers list updated!{bcolors.ENDC}")
        print('')
    if video.studio is None or video.studio == '':
        studioEmptyCount += 1
    else:
        studioSet.add(video.studio)
#
# Output scan statistics
#
studioCount = len(studioSet)
writerGlobalCount = len(writerGlobalSet)
currentTime = datetime.now().strftime("%H:%M:%S")
elapsed = datetime.now() - startTime
print(f"{bcolors.OKGREEN}[{currentTime}] Studio/writer scanning completed in {elapsed}.{bcolors.ENDC}")
print(f"[{currentTime}] Total studios: {studioCount}")
print(f"[{currentTime}] Total empty studios: {studioEmptyCount}")
print(f"[{currentTime}] Total titles: {titleCount}")
print(f"[{currentTime}] Total individual writers: {writerGlobalCount}")
print(f"[{currentTime}] Total appearances: {writerAppearanceCount}")
print(f"{bcolors.OKGREEN}[{currentTime}] Instances of writers already set: {writerAlreadySetCount}{bcolors.ENDC}")
print(f"{bcolors.WARNING}[{currentTime}] Instances of writers not yet set: {writerMissingCount}{bcolors.ENDC}")
print('')
#
# Scan collections in section
#
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
#
# Create missing smart collections for studios
#
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
#
# Create missing smart collections for writers
#
# pprint(sorted(writerGlobalSet))
# sys.exit(1)
for writerName in sorted(writerGlobalSet):
    writerFilters = {"writer": writerName}
    writerTitle = f"03: Star: {writerName}"
    # print(f"Checking if '{writerTitle}' collection already exists...")
    collectionFound = False
    for collection in collectionGlobalSet:
        # print(f"Comparing '{collection.title.lower()}' against '{writerTitle.lower()}'")
        if collection.lower() == writerTitle.lower():
            # print(f"{bcolors.OKCYAN}Collection match found!{bcolors.ENDC}")
            collectionFound = True
    if collectionFound:
        collectionsAlreadyCreated += 1
        # print(f"{bcolors.OKCYAN}Collection {writerTitle} already exists, skipping.{bcolors.ENDC}")
    else:
        currentTime = datetime.now().strftime("%H:%M:%S")
        print(f"{bcolors.WARNING}[{currentTime}] Creating smart collection '{writerTitle}'{bcolors.ENDC}")
        plexSection.createCollection(title=writerTitle, smart=True, sort="titleSort:asc", filters=writerFilters)
        currentTime = datetime.now().strftime("%H:%M:%S")
        print(f"{bcolors.OKGREEN}[{currentTime}] Created smart collection '{writerTitle}'{bcolors.ENDC}")
        collectionsNewlyCreated += 1
#
# Output statistics
#
print('')
currentTime = datetime.now().strftime("%H:%M:%S")
print(f"{bcolors.OKCYAN}[{currentTime}] Existing smart collections: {collectionsAlreadyCreated}{bcolors.ENDC}")
print(f"{bcolors.OKGREEN}[{currentTime}] Newly created smart collections: {collectionsNewlyCreated}{bcolors.ENDC}")
print('')
