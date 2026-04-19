#!/usr/bin/env python3
#
# import modules
#
import sys
import os
import configparser
from pprint import pprint
from plexapi.server import PlexServer
#
# Sanity check CLI arguments and assign them to readable variable names
#
if len(sys.argv) != 2:
    print(f"Usage: {os.path.basename(__file__)} <collection name>")
    sys.exit(1)
collectionName = sys.argv[1]
print(f"Collection: {collectionName}")
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
thisCollection = plexSection.collection(collectionName)
if str(thisCollection.title).lower() == collectionName.lower():
    for video in thisCollection.items():
        # ensure the data is up to date if needed
        if video.isPartialObject():
            video.reload()
        duration_ms = getattr(video, "duration", None)
        if duration_ms:
            total_seconds = duration_ms // 1000
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            duration_str = f"{minutes}:{seconds:02d}"
            print(f"Title: {video.title} ({duration_str})")
        else:
            print(f"Title: {video.title}")
else:
    print("Collection not found.")
