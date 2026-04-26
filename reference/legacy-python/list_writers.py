#!/usr/bin/env python3
#
# import modules
#
import configparser
import os
#from pprint import pprint
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
writerGlobalSet = set()
writerBadCount = 0
writerGoodCount = 0
for video in plexSection.all():
    if not video.writers:
        writerCount = 0
    else:
        writerCount = len(video.writers)
    # print(f"Title: {video.title} has {writerCount} writers.")
    if video.writers:
        for writer in video.writers:
            if "," in f"{writer}":
                print(f"{bcolors.FAIL}Title: {video.title} - Writer: {writer} has a comma in it!{bcolors.ENDC}")
                writerBadCount += 1
            else:
                # print(f"{bcolors.OKGREEN}Writer: {writer}{bcolors.ENDC}")
                writerGoodCount += 1
                writerGlobalSet.add(f"{writer}")

writerCount = len(writerGlobalSet)
print(" ")
print(f"{bcolors.OKGREEN}Total number of good writers: {writerGoodCount}{bcolors.ENDC}")
print(f"{bcolors.FAIL}Total number of bad writers: {writerBadCount}{bcolors.ENDC}")
