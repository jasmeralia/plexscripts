#!/usr/bin/env python3
#
# import modules
#
import configparser
import sys
from pprint import pprint
from plexapi.server import PlexServer
#
# Check CLI arguments
#
if len(sys.argv) == 2:
    search_pattern = sys.argv[1]
else:
    search_pattern = ''
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
# collection_count = len(plex_section.collections())
# collection_smart_count = 0
# collection_empty_count = 0
# collection_sort_change = 0
for collection in plex_section.collections():
    if collection.title.startswith("02: "):
        print(f"Deleting studio collection '{collection.title}'")
        collection.delete()
        print("Done.")
