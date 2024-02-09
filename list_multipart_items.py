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
for video in plexSection.all():
    # print(f"          Video Title: {video.title}")
    for mediaItem in video.media:
        # print(f"     Media Item Parts: {len(mediaItem.parts)}")
        if len(mediaItem.parts) > 1:
            print(f"                Title: {video.title}")
            print(f"                 GUID: {video.guid}")
            print(f"        Media Item ID: {mediaItem.id}")
            print(f"          Media Title: {mediaItem.title}")
            print(f"Media Item Resolution: {mediaItem.videoResolution}")
            for mediaPart in mediaItem.parts:
                print(f"Media Part Accessible: {mediaPart.accessible}")
                print(f"      Media Part File: {mediaPart.file}")
                print(f"        Media Part ID: {mediaPart.id}")
                print(f"       Media Part Key: {mediaPart.key}")
            if video.collections:
                print("Collections:")
                pprint(video.collections)
            else:
                print("No collections associated.")
            print(" ")
            print(" ")
