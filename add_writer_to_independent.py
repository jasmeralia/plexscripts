#!/usr/bin/env python3
#
# import modules
#
import configparser
import sys
import os
import time
from pprint import pprint
from plexapi.server import PlexServer
#
# Sanity check CLI arguments and assign them to readable variable names
#
if len(sys.argv) != 2:
    print(f"Usage: {os.path.basename(__file__)} <pattern match>")
    sys.exit(1)
pattern = sys.argv[1]
studio_name = "Independent Content"
print(f"Pattern: '{pattern}'")
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
sleep_interval = 10
#
# Connect to server
#
plex = PlexServer(baseurl, plex_token)
#
# Select section
#
plex_section = plex.library.section(plex_section_name)
matches_found_count = 0
studios_added_count = 0
studios_already_match_count = 0
studios_set_different_count = 0
industry_skipped = 0
for video in plex_section.all():
    # not all pattern matches will actually match the writer, but this eliminates the overhead of doing reload() on every single video...
    if pattern.lower() in video.title.lower():
        # ensure data is up to date
        video.reload()
        if " (Scene #" in video.title:
            industry_skipped += 1
            # print(f"{bcolors.WARNING}'{video.title}' is not an indie video, skipping!{bcolors.ENDC}")
        else:
            for writer in video.writers:
                # print(f"Comparing '{str(writer)}' against '{pattern}' on '{video.title}'")
                if str(writer).lower() == pattern.lower():
                    # print(f"Match found for '{pattern}' in '{video.title}'")
                    matches_found_count += 1
                    if video.studio == None or video.studio == '':
                        print(f"{bcolors.WARNING}'{video.title}' needs to be added to '{studio_name}'{bcolors.ENDC}")
                        video.edit(**{"studio.value": studio_name, 'label.locked': 1})
                        studios_added_count += 1
                        print(f"{bcolors.OKGREEN}'{video.title}' has been added to {studio_name}{bcolors.ENDC}")
                    elif video.studio == studio_name:
                        print(f"{bcolors.OKCYAN}'{video.title}' is already part of '{studio_name}'{bcolors.ENDC}")
                        studios_already_match_count += 1
                    else:
                        print(f"{bcolors.WARNING}'{video.title}' already belongs to studio '{video.studio}', skipping!{bcolors.ENDC}")
                        studios_set_different_count += 1

if matches_found_count == 0:
    print("")
    print(f"{bcolors.FAIL}No matches found for pattern '{pattern}'!{bcolors.ENDC}")
    print("")
else:
    print("")
    print(f"{bcolors.OKCYAN}{matches_found_count} matches found, {studios_added_count} studios added.{bcolors.ENDC}")
    print("")
