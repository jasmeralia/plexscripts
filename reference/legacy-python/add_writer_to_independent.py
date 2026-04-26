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
# Sanity check CLI arguments and assign them to readable variable names
#
if len(sys.argv) != 2:
    print(f"Usage: {os.path.basename(__file__)} <pattern match>")
    sys.exit(1)
pattern = sys.argv[1]
studioName = "Independent Content"
print(f"Pattern: '{pattern}'")
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
matchesFoundCount = 0
studiosAddedCount = 0
studiosAlreadyMatchCount = 0
studiosSetDifferentCount = 0
industrySkipped = 0
for video in plexSection.all():
    # not all pattern matches will actually match the writer, but this eliminates the overhead of doing reload() on every single video...
    if pattern.lower() in video.title.lower():
        # ensure data is up to date
        video.reload()
        if " (Scene #" in video.title:
            industrySkipped += 1
            # print(f"{bcolors.WARNING}'{video.title}' is not an indie video, skipping!{bcolors.ENDC}")
        else:
            for writer in video.writers:
                # print(f"Comparing '{str(writer)}' against '{pattern}' on '{video.title}'")
                if str(writer).lower() == pattern.lower():
                    # print(f"Match found for '{pattern}' in '{video.title}'")
                    matchesFoundCount += 1
                    if video.studio is None or video.studio == '':
                        print(f"{bcolors.WARNING}'{video.title}' needs to be added to '{studioName}'{bcolors.ENDC}")
                        video.edit(**{"studio.value": studioName, 'label.locked': 1})
                        studiosAddedCount += 1
                        print(f"{bcolors.OKGREEN}'{video.title}' has been added to {studioName}{bcolors.ENDC}")
                    elif video.studio == studioName:
                        print(f"{bcolors.OKCYAN}'{video.title}' is already part of '{studioName}'{bcolors.ENDC}")
                        studiosAlreadyMatchCount += 1
                    else:
                        print(f"{bcolors.WARNING}'{video.title}' already belongs to studio '{video.studio}', skipping!{bcolors.ENDC}")
                        studiosSetDifferentCount += 1

if matchesFoundCount == 0:
    print('')
    print(f"{bcolors.FAIL}No matches found for pattern '{pattern}'!{bcolors.ENDC}")
    print('')
else:
    print('')
    print(f"{bcolors.OKCYAN}{matchesFoundCount} matches found, {studiosAddedCount} studios added.{bcolors.ENDC}")
    print('')
