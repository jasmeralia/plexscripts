#!/usr/bin/env python3
#
# import modules
#
import os
import sys
import configparser
import re
from pprint import pprint
from plexapi.server import PlexServer
#
# Check CLI arguments
#
if len(sys.argv) != 2:
    print(f"Usage: {sys.argv[0]} <pattern>")
    sys.exit(1)

searchPattern = sys.argv[1]
print(f"Search pattern: {searchPattern}")
print('')
searchRegex = re.compile(searchPattern)
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
for video in plexSection.all():
    # print(f"Checking if {video.title} matches regex...")
    if searchRegex.match(video.title):
        print(f"Title: {video.title}")
        # print(f"Locations: {video.locations}")
