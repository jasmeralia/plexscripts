#!/usr/bin/env python3
#
# import modules
#
import configparser
#from pprint import pprint
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
writer_global_set = set()
writer_bad_count = 0
writer_good_count = 0
for video in plex_section.all():
    if not video.writers:
        writer_count = 0
    else:
        writer_count = len(video.writers)
    # print(f"Title: {video.title} has {writer_count} writers.")
    if video.writers:
        for writer in video.writers:
            if "," in f"{writer}":
                print(f"{bcolors.FAIL}Title: {video.title} - Writer: {writer} has a comma in it!{bcolors.ENDC}")
                writer_bad_count += 1
            else:
                # print(f"{bcolors.OKGREEN}Writer: {writer}{bcolors.ENDC}")
                writer_good_count += 1
                writer_global_set.add(f"{writer}")

writer_count = len(writer_global_set)
print(" ")
print(f"{bcolors.OKGREEN}Total number of good writers: {writer_good_count}{bcolors.ENDC}")
print(f"{bcolors.FAIL}Total number of bad writers: {writer_bad_count}{bcolors.ENDC}")
