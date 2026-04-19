#!/usr/bin/env python3
#
# List videos with multiple files (merged or multi-part).
#
import configparser
import os
import sys
from plexapi.server import PlexServer

config = configparser.ConfigParser()
config.read(os.path.expanduser("~/.plexconfig.ini"))
plexHost = config["default"]["plexHost"]
plexPort = config["default"]["plexPort"]
plexToken = config["default"]["plexToken"]
plexSectionName = config["default"]["plexSectionName"]
baseurl = f"http://{plexHost}:{plexPort}"

plex = PlexServer(baseurl, plexToken)
plexSection = plex.library.section(plexSectionName)

filter_text = sys.argv[1] if len(sys.argv) > 1 else None

for video in plexSection.all():
    files = []
    for part in video.iterParts():
        if part.file and part.file not in files:
            files.append(part.file)

    if len(files) > 1:
        if filter_text:
            haystack = [video.title] + files
            if not any(filter_text in entry for entry in haystack):
                continue
        print(f"Title: {video.title}")
        for filename in files:
            print(f"  {filename}")
        print("")
