#!/usr/bin/env python3
from plexapi.server import PlexServer
import configparser, os

config = configparser.ConfigParser()
config.read(os.path.expanduser("~/.plexconfig.ini"))
baseurl = f"http://{config['default']['plexHost']}:{config['default']['plexPort']}"
plex = PlexServer(baseurl, config['default']['plexToken'])
section = plex.library.section(config['default']['plexSectionName'])

target = os.environ["PLEXADM_MISSING_FILE_TARGET"]
for video in section.all():
    for part in video.iterParts():
        if part.file == target:
            print("FOUND:", video.title, video.guid)
