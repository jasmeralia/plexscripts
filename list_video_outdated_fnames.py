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
    matchFound = False
    if len(video.locations) > 1:
        print(f"{video.title} has multiple locations!")
        for location in video.locations:
            print(location)
        print('')
    else:
        for location in video.locations:
            if video.title in location:
                matchFound = True

    if matchFound is False:
        oldLocation = video.locations[0].replace('/data/NSFW Scenes/', '')
        print(f"mv \"{oldLocation}\" \"{video.title}.mp4\"")
