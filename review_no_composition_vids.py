#!/usr/bin/env python3
#
# import modules
#
import os
import sys
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
searchFilters = {
    'and': [
        {'collection!': '01: Category: FFF+'},
        {'collection!': '01: Category: FFFM'},
        {'collection!': '01: Category: FFM'},
        {'collection!': '01: Category: FFT'},
        {'collection!': '01: Category: Gangbang'},
        {'collection!': '01: Category: MF Only'},
        {'collection!': '01: Category: MMF'},
        {'collection!': '01: Category: Non-Sexual'},
        {'collection!': '01: Category: Orgy'},
        {'collection!': '01: Category: Reverse Gangbang'},
        {'collection!': '01: Category: Solo'},
        {'collection!': '01: Category: Trans MTF'},
    ]
}
print(f"{bcolors.OKCYAN}Search filters: {bcolors.OKGREEN}{searchFilters}\n{bcolors.ENDC}")

results = plexSection.search(filters=searchFilters, sort="titleSort")
print(f"{bcolors.OKCYAN}Found {len(results)} search matches:{bcolors.ENDC}")
for video in results:
    # ensure data is up to date
    # if video.isPartialObject():
    #     video.reload()
    print(f"Title: {video.title}")
    # print(f"Locations: {video.locations}")
print('')
