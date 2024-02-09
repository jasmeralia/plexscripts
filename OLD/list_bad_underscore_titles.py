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
totalCount = 0
badCount = 0
plexSection = plex.library.section(plexSectionName)
for video in plexSection.all():
    totalCount += 1
    if "_" in video.title and not "she_is_sam" in video.title:
        print(f"Title: {video.title}")
        badCount += 1

print("")
print(f"{badCount} bad names of {totalCount} total names.")
