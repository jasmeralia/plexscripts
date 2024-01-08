#!/usr/bin/env python3
#
# import modules
#
import configparser
from pprint import pprint
from plexapi.server import PlexServer
#
# Color support
#
class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
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
multi_studio_vid_count = 0
total_count = 0
for video in plex_section.all():
    total_count += 1
    # ensure data is up to date
    video.reload()
    studios_found_count = 0
    studios_found_set = set()
    if video.collections:
        for collection in video.collections:
            if str(collection).startswith('02: '):
                studios_found_count += 1
                studios_found_set.add(str(collection))
    if studios_found_count > 1:
        multi_studio_vid_count += 1
        print(f"{bcolors.WARNING}Title: '{video.title}' is in multiple studio collections: ", end='')
        pprint(studios_found_set)
        print(f"{bcolors.ENDC}", end='')
    # else:
    #     if studios_found_count == 1:
    #         print(f"{bcolors.OKGREEN}Title: '{video.title}' is in 1 studio collection.{bcolors.ENDC}")
    #     else:
    #         print(f"{bcolors.OKCYAN}Title: '{video.title}' is in {studios_found_count} studio collections.{bcolors.ENDC}")

print(f"{bcolors.ENDC}")
print(f"{multi_studio_vid_count} titles are in multiple studio collections out of a total {total_count} titles.")
