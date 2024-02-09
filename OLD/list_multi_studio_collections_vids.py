#!/usr/bin/env python3
#
# import modules
#
import configparser
import os
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
#
# Connect to server
#
plex = PlexServer(baseurl, plexToken)
#
# Select section
#
plexSection = plex.library.section(plexSectionName)
multiStudioVidCount = 0
totalCount = 0
for video in plexSection.all():
    totalCount += 1
    # ensure data is up to date
    video.reload()
    studiosFoundCount = 0
    studiosFoundSet = set()
    if video.collections:
        for collection in video.collections:
            if str(collection).startswith('02: '):
                studiosFoundCount += 1
                studiosFoundSet.add(str(collection))
    if studiosFoundCount > 1:
        multiStudioVidCount += 1
        print(f"{bcolors.WARNING}Title: '{video.title}' is in multiple studio collections: ", end='')
        pprint(studiosFoundSet)
        print(f"{bcolors.ENDC}", end='')
    # else:
    #     if studiosFoundCount == 1:
    #         print(f"{bcolors.OKGREEN}Title: '{video.title}' is in 1 studio collection.{bcolors.ENDC}")
    #     else:
    #         print(f"{bcolors.OKCYAN}Title: '{video.title}' is in {studiosFoundCount} studio collections.{bcolors.ENDC}")

print(f"{bcolors.ENDC}")
print(f"{multiStudioVidCount} titles are in multiple studio collections out of a total {totalCount} titles.")
