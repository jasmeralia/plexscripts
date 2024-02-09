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
# Given a list of writers, build a Plex search filter
#
def writerListToSearchFilter(writerList):
    searchList = []
    for writerName in writerList:
        searchList.append({'writer': writerName})
    return {'or': searchList}
#
# Check CLI arguments
#
if len(sys.argv) != 2:
    print(f"Usage: {sys.argv[0]} <filename of writers>")
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
print(f"Imported {writerCount} writers to add to the collection.")
print('')
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
searchFilters = writerListToSearchFilter(writerList)
print(f"{bcolors.OKCYAN}Search filters: {bcolors.OKGREEN}{searchFilters}\n{bcolors.ENDC}")

results = plexSection.search(filters=searchFilters, sort="titleSort")
print(f"{bcolors.OKCYAN}Found {len(results)} search matches:{bcolors.ENDC}")
for video in results:
    # ensure data is up to date
    if video.isPartialObject():
        video.reload()
    print(f"{bcolors.ENDC}Title: {bcolors.WARNING}{video.title}{bcolors.ENDC}")
    # print(f"Locations: {video.locations}")
print('')
