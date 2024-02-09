#!/usr/bin/env python3
#
# import modules
#
import configparser
import os
from pprint import pprint
from plexapi.server import PlexServer
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
totalCount = 0
missingStudioCount = 0
for video in plexSection.all():
    totalCount += 1
    if video.studio is None and not " (Scene #" in video.title:
        missingStudioCount += 1
        print(f"Title: {video.title}")

print('')
print(f"{missingStudioCount} titles are potentially missing the indie label out of a total {totalCount} titles.")
