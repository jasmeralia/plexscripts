#!/usr/bin/env python3
#
# import modules
#
import configparser
from pprint import pprint
from plexapi.server import PlexServer
#
# set default variables
#
config = configparser.ConfigParser()
config.read(os.getenv('HOME')+'/.plexconfig.ini')
plex_host = config['default']['plex_host']
plex_port = config['default']['plex_port']
plex_section = config['default']['plex_section']
plex_token = config['default']['plex_token']
plex_section_name = config['default']['plex_section_name']
baseurl = f"http://{plex_host}:{plex_port}"
#
# Connect to server
#
plex = PlexServer(baseurl, plex_token)
#
# Select section
#
plex_section = plex.library.section(plex_section_name)
for video in plex_section.all():
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
