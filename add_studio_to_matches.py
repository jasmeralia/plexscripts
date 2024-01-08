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
#print(f"Studio: {studio_name}")
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
plexHost = config['default']['plex_host']
plexPort = config['default']['plex_port']
plexSection = config['default']['plex_section']
plexToken = config['default']['plex_token']
plexSectionName = config['default']['plex_section_name']
baseurl = f"http://{plexHost}:{plexPort}"
sleep_interval = 10
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
# Check if the studio has been used previously.
#
for video in plexSection.all():
    if video.studio == studioName:
        studioFound = True
#
# No pr3vious matches, abort!
#
if not studioFound:
    print(f"{bcolors.FAIL}Could not find match for existing studio '{studioName}', aborting!{bcolors.ENDC}")
    sys.exit(1)
#
# Previous use of studio name, proceed.
#
for video in plexSection.all():
    #print(f"Checking video '{video.title}' for pattern '{pattern}'...")
    if pattern.lower() in video.title.lower():
        # ensure data is up to date
        video.reload()
        matchesFound += 1
        if video.studio == None:
            print(f"{bcolors.WARNING}'{video.title}' needs to be added to '{studioName}'{bcolors.ENDC}")
            video.edit(**{"studio.value": studioName, 'label.locked': 1})
            studiosAdded += 1
            print(f"{bcolors.OKGREEN}'{video.title}' has been added to '{studioName}'{bcolors.ENDC}")
        elif video.studio == studioName:
            print(f"{bcolors.OKCYAN}'{video.title}' is already part of '{studioName}'{bcolors.ENDC}")
        else:
            print(f"{bcolors.WARNING}'{video.title}' already belongs in studio '{studioName}', skipping!{bcolors.ENDC}")

if matchesFound == 0:
    print("")
    print(f"{bcolors.FAIL}No matches found for pattern '{pattern}'!{bcolors.ENDC}")
    print("")
else:
    print("")
    print(f"{bcolors.OKCYAN}{matchesFound} matches found, {studiosAdded} collections added.{bcolors.ENDC}")
    print("")
