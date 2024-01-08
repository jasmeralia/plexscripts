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
    # replace nbsp; with space and emdash with hyphen... fuck utf8!
    this_title = video.title.replace(" – ", " - ").replace("\xa0", " ")
    writer_names = this_title.split(' - ', 1)[0]
    if ',' in writer_names:
        category_found = False
        if video.collections:
            for collection in video.collections:
                if str(collection).lower() == "01: Category: FFF+".lower():
                    category_found = True
                elif str(collection).lower() == "01: Category: FFM".lower():
                    category_found = True
                elif str(collection).lower() == "01: Category: FFFM".lower():
                    category_found = True
                elif str(collection).lower() == "01: Category: Lesbian".lower():
                    category_found = True
                elif str(collection).lower() == "01: Category: Orgy".lower():
                    category_found = True
                elif str(collection).lower() == "01: Category: MF Only".lower():
                    category_found = True
        if not category_found:
            missing_category_count += 1
            print(f"Title: {video.title}")

print("")
print(f"{missing_category_count} titles are missing categories out of a total {total_count} titles.")
