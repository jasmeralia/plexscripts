#!/usr/bin/env python3
from plexapi.server import PlexServer
import configparser, os

config = configparser.ConfigParser()
config.read(os.path.expanduser("~/.plexconfig.ini"))
baseurl = f"http://{config['default']['plexHost']}:{config['default']['plexPort']}"
plex = PlexServer(baseurl, config['default']['plexToken'])
section = plex.library.section(config['default']['plexSectionName'])

target = "/data/NSFW Scenes/00 Rin/00 Rin - 184140411221_2191516559_2021-08-12.mp4"
for video in section.all():
    for part in video.iterParts():
        if part.file == target:
            print("FOUND:", video.title, video.guid)
