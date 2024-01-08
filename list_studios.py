#!/usr/bin/env python3
#
# import modules
#
import configparser
import sys
import os
from pprint import pprint
from plexapi.server import PlexServer
from datetime import datetime
#
# Check CLI arguments
#
if len(sys.argv) == 2:
    debug_val = sys.argv[1]
else:
    debug_val = 0

print(f"DEBUG = {debug_val}")

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
reloaded_count = 0
unreloaded_count = 0
studio_empty_count = 0
studio_count = 0
studio_dict = {}
studio_dict['unset'] = 0
video_total_count = len(plex_section.all())
video_current_count = 0
for video in plex_section.all():
    # ensure the data is up to date if necessary
    if video.isPartialObject():
        # print(f"Video {video.title} is being reloaded as it is a partial object")
        video.reload()
        reloaded_count += 1
    else:
        unreloaded_count += 1

    video_current_count += 1
    if (video_current_count % 100) == 0:
        current_time = datetime.now().strftime("%H:%M:%S")
        print(f"[{current_time}] Processing {video_current_count}/{video_total_count}...")

    if video.studio == None or video.studio == '':
        studio_empty_count += 1
    else:
        if video.studio in studio_dict.keys():
            studio_dict[video.studio] += 1
            # print(f"{bcolors.OKGREEN}Found subsequent instance of '{video.studio}' on '{video.title}', current count: {studio_dict[video.studio]}{bcolors.ENDC}")
        else:
            studio_dict[video.studio] = 1
            # print(f"{bcolors.OKCYAN}Found first instance of '{video.studio}' on '{video.title}'{bcolors.ENDC}")

if debug_val == 0:
    for this_studio_name, this_studio_count in studio_dict.items():
        print("%4d: Studio: %s" % (this_studio_count, this_studio_name))
    print("")
    current_time = datetime.now().strftime("%H:%M:%S")
    print(f"{bcolors.OKCYAN}[{current_time}] Total number of unique studios: {len(studio_dict)}{bcolors.ENDC}")
    print(f"{bcolors.FAIL}[{current_time}] Total number of empty studios: {studio_empty_count}{bcolors.ENDC}")
    print(f"{bcolors.OKCYAN}[{current_time}] Total number of reloaded videos: {reloaded_count}{bcolors.ENDC}")
    print(f"{bcolors.FAIL}[{current_time}] Total number of unreloaded videos: {unreloaded_count}{bcolors.ENDC}")
else:
    studio_list = studio_dict.keys()
    # pprint(studio_list)
    for this_studio_name in sorted(studio_list):
        print("%4d: Studio: %s" % (studio_dict[this_studio_name], this_studio_name))
