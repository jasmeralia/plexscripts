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
studiosUpdatedCount = 0
studiosAlreadySetCount = 0
studiosMismatchCount = 0
studiosNotFoundCount = 0
studiosMultipleCount = 0
totalCount = 0
for video in plexSection.all():
    # print(f"Checking video '{video.title}'...")
    # ensure data is up to date
    video.reload()
    totalCount += 1
    foundStudio = ''
    foundStudioCount = 0
    if video.collections:
        for collection in video.collections:
            if str(collection).startswith('02: '):
                foundStudioCount += 1
                foundStudio = str(collection).replace('02: Studio: ', '').replace('02: ', '')
    if foundStudioCount > 1:
        print(f"{bcolors.FAIL}'{video.title}' is in multiple studio collections!{bcolors.ENDC}")
        studiosMultipleCount += 1
    elif foundStudioCount == 1:
        if video.studio != '' and video.studio != None:
            if video.studio == foundStudio:
                # print(f"{bcolors.OKGREEN}'{video.title}' is already in studio '{video.studio}'{bcolors.ENDC}")
                studiosAlreadySetCount += 1
            else:
                print(f"{bcolors.WARNING}'{video.title}' is set to a different studio ({video.studio}) rather than the collection studio ({foundStudio})!{bcolors.ENDC}")
                studiosMismatchCount += 1
        else:
            print(f"{bcolors.WARNING}'{video.title}' needs to be set to studio '{foundStudio}'...{bcolors.ENDC}")
            video.edit(**{"studio.value": foundStudio, 'label.locked': 1})
            print(f"{bcolors.OKGREEN}'{video.title}' added to studio '{foundStudio}'.{bcolors.ENDC}")
            studiosUpdatedCount += 1
    else:
        print(f"{bcolors.FAIL}'{video.title}' is not in a studio collection currently!{bcolors.ENDC}")
        studiosNotFoundCount += 1

print("")
print(f"{bcolors.FAIL}Total studios missing: {studiosNotFoundCount}{bcolors.ENDC}")
print(f"{bcolors.FAIL}Total videos with multiple studio collections: {studiosMultipleCount}{bcolors.ENDC}")
print(f"{bcolors.WARNING}Total videos with a studio mismatch: {studiosMismatchCount}{bcolors.ENDC}")
print(f"{bcolors.OKCYAN}Total studios updated: {studiosUpdatedCount}{bcolors.ENDC}")
print(f"{bcolors.OKGREEN}Total studios set correctly: {studiosAlreadySetCount}{bcolors.ENDC}")
print(f"{bcolors.OKGREEN}Total videos: {totalCount}{bcolors.ENDC}")
