#!/usr/bin/env python3
#
# import modules
#
import argparse
import configparser
import os
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

parser = argparse.ArgumentParser(
    description=(
        "List videos that would be renamed. Use 'output' for old/new names or "
        "'script' for mv commands."
    )
)
parser.add_argument("mode", choices=["output", "script"])
parser.add_argument(
    "filter_text",
    nargs="?",
    help="Only include videos where the title or any file location contains this text.",
)
args = parser.parse_args()

filter_text = args.filter_text

for video in plexSection.all():
    if filter_text:
        haystack = [video.title] + video.locations
        if not any(filter_text in entry for entry in haystack):
            continue

    matchFound = False
    filename = os.path.basename(video.locations[0])
    # if len(video.locations) > 1:
        # print(f"{video.title} has multiple locations!")
        # for location in video.locations:
        #     print(location)
        # print('')
    # else:
    for location in video.locations:
        if video.title in location:
            matchFound = True

    if " - Message " in filename or " - Post " in filename or "PPV" in filename:
        # Exclude Message/Post/PPV files from results
        matchFound = True
    elif " PPV " in video.locations[0]:
        # Leave these alone for rsync purposes
        matchFound = True
    elif '?' in video.title:
        # Can't use this in a filename
        matchFound = True

    has_location_mismatch = any(video.title not in location for location in video.locations)
    needs_review = args.mode == "output" and len(video.locations) > 1 and has_location_mismatch

    if matchFound is False or needs_review:
        oldLocation = video.locations[0].replace('/data/NSFW Scenes/', '')
        newFname = f"{video.title}.mp4"
        writerNames = newFname.split(' - ', 1)[0]
        writersList = writerNames.split(',')
        firstWriter = writersList[0]
        if args.mode == "script":
            print(f"mv \"{oldLocation}\" \"{firstWriter}/{newFname}\"")
        else:
            if len(video.locations) > 1:
                print(f"WARNING: {video.title} has multiple locations!")
                for location in video.locations:
                    print(f"  {location}")
                print("")
            else:
                print(f"{oldLocation} -> {firstWriter}/{newFname}")
