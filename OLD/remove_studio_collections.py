#!/usr/bin/env python3
#
# import modules
#
import configparser
import sys
import os
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
# collectionCount = len(plexSection.collections())
# collectionSmartCount = 0
# collectionEmptyCount = 0
# collectionSortChange = 0
for collection in plexSection.collections():
    if collection.title.startswith("02: "):
        print(f"Deleting studio collection '{collection.title}'")
        collection.delete()
        print("Done.")
