#!/usr/bin/env python3
#
# import modules
#
import configparser
import sys
import os
from datetime import datetime
from pprint import pprint
from plexapi.server import PlexServer
#
# Check CLI arguments
#
if len(sys.argv) == 2:
    debugVal = sys.argv[1]
else:
    debugVal = 0

print(f"DEBUG = {debugVal}")

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
reloadedCount = 0
unreloadedCount = 0
studioEmptyCount = 0
studioCount = 0
studioDict = {}
studioDict['unset'] = 0
videoTotalCount = len(plexSection.all())
videoCurrentCount = 0
for video in plexSection.all():
    # ensure the data is up to date if necessary
    if video.isPartialObject():
        # print(f"Video {video.title} is being reloaded as it is a partial object")
        video.reload()
        reloadedCount += 1
    else:
        unreloadedCount += 1

    videoCurrentCount += 1
    if (videoCurrentCount % 100) == 0:
        currentTime = datetime.now().strftime("%H:%M:%S")
        print(f"[{currentTime}] Processing {videoCurrentCount}/{videoTotalCount}...")

    if video.studio is None or video.studio == '':
        studioEmptyCount += 1
    else:
        if video.studio in studioDict.keys():
            studioDict[video.studio] += 1
            # print(f"{bcolors.OKGREEN}Found subsequent instance of '{video.studio}' on '{video.title}', current count: {studioDict[video.studio]}{bcolors.ENDC}")
        else:
            studioDict[video.studio] = 1
            # print(f"{bcolors.OKCYAN}Found first instance of '{video.studio}' on '{video.title}'{bcolors.ENDC}")

if debugVal == 0:
    for thisStudioName, thisStudioCount in studioDict.items():
        print("%4d: Studio: %s" % (thisStudioCount, thisStudioName))
    print('')
    currentTime = datetime.now().strftime("%H:%M:%S")
    print(f"{bcolors.OKCYAN}[{currentTime}] Total number of unique studios: {len(studioDict)}{bcolors.ENDC}")
    print(f"{bcolors.FAIL}[{currentTime}] Total number of empty studios: {studioEmptyCount}{bcolors.ENDC}")
    print(f"{bcolors.OKCYAN}[{currentTime}] Total number of reloaded videos: {reloadedCount}{bcolors.ENDC}")
    print(f"{bcolors.FAIL}[{currentTime}] Total number of unreloaded videos: {unreloadedCount}{bcolors.ENDC}")
else:
    studioList = studioDict.keys()
    # pprint(studioList)
    for thisStudioName in sorted(studioList):
        print("%4d: Studio: %s" % (studioDict[thisStudioName], thisStudioName))
