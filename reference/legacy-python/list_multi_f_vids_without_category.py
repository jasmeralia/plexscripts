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
    # replace nbsp; with space and emdash with hyphen... fuck utf8!
    thisTitle = video.title.replace(" – ", " - ").replace("\xa0", " ")
    writerNames = thisTitle.split(' - ', 1)[0]
    if ',' in writerNames:
        categoryFound = False
        if video.collections:
            for collection in video.collections:
                if str(collection).lower() == "01: Category: FFF+".lower():
                    categoryFound = True
                elif str(collection).lower() == "01: Category: FFM".lower():
                    categoryFound = True
                elif str(collection).lower() == "01: Category: FFFM".lower():
                    categoryFound = True
                elif str(collection).lower() == "01: Category: Lesbian".lower():
                    categoryFound = True
                elif str(collection).lower() == "01: Category: Orgy".lower():
                    categoryFound = True
                elif str(collection).lower() == "01: Category: MF Only".lower():
                    categoryFound = True
                elif str(collection).lower() == "01: Category: Reverse Gangbang".lower():
                    categoryFound = True
        if not categoryFound:
            missingCategoryCount += 1
            print(f"Title: {video.title}")

print('')
print(f"{missingCategoryCount} titles are missing categories out of a total {totalCount} titles.")
