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
total_count = 0
missing_studio_count = 0
for video in plex_section.all():
    total_count += 1
    if video.studio == None and not " (Scene #" in video.title:
        missing_studio_count += 1
        print(f"Title: {video.title}")

print("")
print(f"{missing_studio_count} titles are potentially missing the indie label out of a total {total_count} titles.")
