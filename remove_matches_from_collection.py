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
if len(sys.argv) != 3:
    print(f"Usage: {os.path.basename(__file__)} <collection name> <pattern match>")
    sys.exit(1)
pattern = sys.argv[2]
collectionName = sys.argv[1]
indieContent = bool(collectionName == "02: Independent Content")
print(f"Pattern: '{pattern}'")
matchedVideos = []
#print(f"Collection: {collectionName}")
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
    print(f"Collection '{thisCollection.title}' found.")
else:
    print(f"Collection '{collectionName}' not found.")
    sys.exit(1)

matchesFound = False
for video in plexSection.all():
    #print(f"Checking video '{video.title}' for pattern '{pattern}'...")
    skipNonIndie = False
    if indieContent and " (Scene #" in video.title and pattern.lower() in video.title.lower():
        skipNonIndie = True
        print(f"Skipping non-indie content match '{video.title}'")
    if not skipNonIndie and pattern.lower() in video.title.lower():
        matchesFound = True
        foundCollection = False
        if video.collections:
            for collection in video.collections:
                if str(collection).lower() == collectionName.lower():
                    foundCollection = True
        if foundCollection:
            print(f"'{video.title}' needs to be removed from '{thisCollection.title}'")
            matchedVideos.append(video)
            # thisCollection.removeItems(video)
            # print(f"'{video.title}' has been removed from {thisCollection.title}")
if not matchesFound:
    print(f"No matches found for pattern '{pattern}'")
else:
    print(f"{len(matchedVideos)} matches need to be removed from {thisCollection.title}")
    thisCollection.removeItems(matchedVideos)
    print(f"{len(matchedVideos)} matches have been removed from {thisCollection.title}")
