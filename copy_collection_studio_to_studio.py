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
studios_updated_count = 0
studios_already_set_count = 0
studios_mismatch_count = 0
studios_not_found_count = 0
studios_multiple_count = 0
total_count = 0
for video in plex_section.all():
    # print(f"Checking video '{video.title}'...")
    # ensure data is up to date
    video.reload()
    total_count += 1
    found_studio = ''
    found_studio_count = 0
    if video.collections:
        for collection in video.collections:
            if str(collection).startswith('02: '):
                found_studio_count += 1
                found_studio = str(collection).replace('02: Studio: ', '').replace('02: ', '')
    if found_studio_count > 1:
        print(f"{bcolors.FAIL}'{video.title}' is in multiple studio collections!{bcolors.ENDC}")
        studios_multiple_count += 1
    elif found_studio_count == 1:
        if video.studio != '' and video.studio != None:
            if video.studio == found_studio:
                # print(f"{bcolors.OKGREEN}'{video.title}' is already in studio '{video.studio}'{bcolors.ENDC}")
                studios_already_set_count += 1
            else:
                print(f"{bcolors.WARNING}'{video.title}' is set to a different studio ({video.studio}) rather than the collection studio ({found_studio})!{bcolors.ENDC}")
                studios_mismatch_count += 1
        else:
            print(f"{bcolors.WARNING}'{video.title}' needs to be set to studio '{found_studio}'...{bcolors.ENDC}")
            video.edit(**{"studio.value": found_studio, 'label.locked': 1})
            print(f"{bcolors.OKGREEN}'{video.title}' added to studio '{found_studio}'.{bcolors.ENDC}")
            studios_updated_count += 1
    else:
        print(f"{bcolors.FAIL}'{video.title}' is not in a studio collection currently!{bcolors.ENDC}")
        studios_not_found_count += 1

print("")
print(f"{bcolors.FAIL}Total studios missing: {studios_not_found_count}{bcolors.ENDC}")
print(f"{bcolors.FAIL}Total videos with multiple studio collections: {studios_multiple_count}{bcolors.ENDC}")
print(f"{bcolors.WARNING}Total videos with a studio mismatch: {studios_mismatch_count}{bcolors.ENDC}")
print(f"{bcolors.OKCYAN}Total studios updated: {studios_updated_count}{bcolors.ENDC}")
print(f"{bcolors.OKGREEN}Total studios set correctly: {studios_already_set_count}{bcolors.ENDC}")
print(f"{bcolors.OKGREEN}Total videos: {total_count}{bcolors.ENDC}")
