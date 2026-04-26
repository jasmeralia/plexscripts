#!/usr/bin/env python3
#
# import modules
#
import sys
import os
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
idieContent = bool(collectionName == "02: Independent Content")
print(f"Pattern: '{pattern}'")
#print(f"Collection: {collectionName}")
#
# set default variables
#
plexHost = '192.168.1.220'
plexPort = 32_400
plexSection = 17
plexToken = 'v1-wDHYg2XymMhtz5rNz'
plexSectionName = 'NSFW Scenes'
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
matchResults = []
for video in plexSection.all():
    #print(f"Checking video '{video.title}' for pattern '{pattern}'...")
    skipNonIndie = False
    if indieContent and " (Scene #" in video.title and video.title.lower().startswith(pattern.lower()):
        skipNonIndie = True
        print(f"Skipping non-indie content match '{video.title}'")
    if not skipNonIndie and video.title.lower().startswith(pattern.lower()):
        matchesFound = True
        foundCollection = False
        if video.collections:
            for collection in video.collections:
                if str(collection).lower() == collectionName.lower():
                    foundCollection = True
        if not foundCollection:
            print(f"'{video.title}' needs to be added to '{thisCollection.title}'")
            matchResults.append(video)
            # thisCollection.addItems(video)
            # print(f"'{video.title}' has been added to {thisCollection.title}")

if not matchesFound:
    print('')
    print(f"{bcolors.OKCYAN}No matches found for pattern '{pattern}'{bcolors.ENDC}")
else:
    thisCollection.addItems(matchResults)
    print('')
    print(f"{bcolors.OKCYAN}{matchesFound} matches found, {collectionsAdded} collections added.{bcolors.ENDC}")
    print('')
