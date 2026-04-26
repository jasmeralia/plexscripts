#!/usr/bin/env python3
#
# import modules
#
import configparser
import sys
import os
# import time
# from pprint import pprint
from plexapi.server import PlexServer
#
# Sanity check CLI arguments and assign them to readable variable names
#
if len(sys.argv) != 3:
    print(f"Usage: {os.path.basename(__file__)} <studio collection name> <pattern match>")
    sys.exit(1)
pattern = sys.argv[2]
studioName = sys.argv[1]
print(f"Pattern: '{pattern}'")
#print(f"Studio: {studioName}")
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

matchesFound = 0
studiosAdded = 0
studioFound = False

#
# Check if the studio has been used previously by looking at the smart collections for studios
# (this is much faster than other methods).
#
for collection in plexSection.collections():
    if collection.title == f"02: Studio: {studioName}":
        studioFound = True
#
# No previous matches, abort!
#
if not studioFound:
    print(f"{bcolors.FAIL}Could not find match for existing studio '{studioName}', aborting!{bcolors.ENDC}")
    sys.exit(1)
else:
    print(f"{bcolors.OKGREEN}Studio '{studioName}' has been located, proceeding.{bcolors.ENDC}")
    print('')
#
# Previous use of studio name, proceed.
#
for video in plexSection.all():
    #print(f"Checking video '{video.title}' for pattern '{pattern}'...")
    if pattern.lower() in video.title.lower():
        # ensure data is up to date
        video.reload()
        matchesFound += 1
        if video.studio is None:
            print(f"{bcolors.WARNING}'{video.title}' needs to be set to '{studioName}'{bcolors.ENDC}")
            video.edit(**{"studio.value": studioName, 'label.locked': 1})
            studiosAdded += 1
            print(f"{bcolors.OKGREEN}'{video.title}' has been set to '{studioName}'{bcolors.ENDC}")
        elif video.studio == studioName:
            print(f"{bcolors.OKCYAN}'{video.title}' already belongs to '{studioName}'{bcolors.ENDC}")
        else:
            print(f"{bcolors.WARNING}'{video.title}' already belongs in studio '{video.studio}', skipping!{bcolors.ENDC}")

if matchesFound == 0:
    print('')
    print(f"{bcolors.FAIL}No matches found for pattern '{pattern}'!{bcolors.ENDC}")
    print('')
else:
    print('')
    print(f"{bcolors.OKCYAN}{matchesFound} matches found, {studiosAdded} studios added.{bcolors.ENDC}")
    print('')
