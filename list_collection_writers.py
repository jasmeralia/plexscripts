#!/usr/bin/env python3
#
# import modules
#
import sys
import os
import configparser
from pprint import pprint
from plexapi.server import PlexServer
#
# Sanity check CLI arguments and assign them to readable variable names
#
if len(sys.argv) != 2:
    print(f"Usage: {os.path.basename(__file__)} <collection name>")
    sys.exit(1)
collection_name = sys.argv[1]
# print(f"Collection: {collection_name}")
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
this_collection = plex_section.collection(collection_name)
writer_global_set = set()
if not (str(this_collection.title).lower() == collection_name.lower()):
#     print(f"{bcolors.OKGREEN}Collection '{this_collection.title}' found.{bcolors.ENDC}")
#     print("")
# else:
    print(f"{bcolors.FAIL}Collection '{collection_name}' not found!{bcolors.ENDC}")
    sys.exit(1)

for video in this_collection.items():
    for this_writer in video.writers:
        writer_global_set.add(f"{this_writer}")

if len(writer_global_set) == 0:
    print(f"{bcolors.FAIL}No writers found!{bcolors.ENDC}")
else:
    # print(f"{bcolors.OKGREEN}{len(writer_global_set)} writers found.{bcolors.ENDC}")
    for writerName in sorted(writer_global_set):
        print(writerName)
