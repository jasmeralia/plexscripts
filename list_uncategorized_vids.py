#!/usr/bin/env python3
#
# import modules
#
import configparser
import os
#from pprint import pprint
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
missingCategoryCount = 0
totalCount = 0
for video in plexSection.all():
    totalCount += 1
    # ensure data is up to date
    video.reload()
    categoryFound = False
    if video.collections:
        for collection in video.collections:
            if str(collection).startswith("01: Category: "):
                categoryFound = True
    if not categoryFound:
        missingCategoryCount += 1
        print(f"Title: {video.title}")

print('')
print(f"{missingCategoryCount} titles are missing categories out of a total {totalCount} titles.")
