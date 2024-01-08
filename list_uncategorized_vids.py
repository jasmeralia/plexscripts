#!/usr/bin/env python3
#
# import modules
#
import configparser
#from pprint import pprint
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
missing_category_count = 0
total_count = 0
for video in plex_section.all():
    total_count += 1
    # ensure data is up to date
    video.reload()
    category_found = False
    if video.collections:
        for collection in video.collections:
            if str(collection).startswith("01: Category: "):
                category_found = True
    if not category_found:
        missing_category_count += 1
        print(f"Title: {video.title}")

print("")
print(f"{missing_category_count} titles are missing categories out of a total {total_count} titles.")
