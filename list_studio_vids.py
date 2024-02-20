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
# Sanity check CLI arguments and assign them to readable variable names
#
if len(sys.argv) != 2:
    print(f"Usage: {os.path.basename(__file__)} <studio name>")
    sys.exit(1)
studioName = sys.argv[1]
# print(f"Studio: {studioName}")
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
results = plexSection.search(studio__exact=studioName, sort="titleSort")
studioCount = len(results)

if len(results) == 0:
    print(f"{bcolors.FAIL}No videos found belonging to '{studioName}'!{bcolors.ENDC}")
else:
    print(f"{bcolors.OKGREEN}{len(results)} videos found.{bcolors.ENDC}")
    print('')

    for video in results:
        print(f"{video.title}")
