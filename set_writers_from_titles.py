#!/usr/bin/env python3
#-*- coding: utf-8 -*-
#
# import modules
#
import configparser
import sys
import os
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
writer_global_set = set()
plex_section = plex.library.section(plex_section_name)
title_count = 0
writer_appearance_count = 0
writer_missing_count = 0
writer_already_set_count = 0
for video in plex_section.all():
    title_count += 1
    # ensure data is up to date
    video.reload()
    # replace nbsp; with space and emdash with hyphen... fuck utf8!
    this_title = video.title.replace(" – ", " - ").replace("\xa0", " ")
    writer_names = this_title.split(' - ', 1)[0]
    writers_list = writer_names.split(',')
    stripped_set = set()
    some_writers_missing = False
    for writer_name in writers_list:
        stripped_name = writer_name.strip()
        stripped_set.add(stripped_name)
        # print(f"Found writer: {writer_name}")
        writer_global_set.add(stripped_name)
        writer_appearance_count += 1
        writer_already_set = False
        for thiswriter in video.writers:
            if f"{thiswriter}".lower() == stripped_name.lower():
                writer_already_set = True
        if writer_already_set:
            # print(f"{bcolors.OKGREEN}Writer '{stripped_name}' already set on this title.{bcolors.ENDC}")
            writer_already_set_count += 1
        else:
            print(f"{bcolors.WARNING}Writer '{stripped_name}' not yet set on {video.title}, need to add it!{bcolors.ENDC}")
            writer_missing_count += 1
            some_writers_missing = True
    if some_writers_missing:
        print(f"{bcolors.WARNING}List extracted from title: ", end="")
        pprint(sorted(stripped_set))
        print(f"{bcolors.OKCYAN}Current list in Plex: ", end="")
        pprint(video.writers)
        print(f"{bcolors.WARNING}Updating list...{bcolors.ENDC}")
        video.addWriter(sorted(stripped_set), True)
        print(f"{bcolors.OKGREEN}Writers list updated!{bcolors.ENDC}")
        print("")

writer_global_count = len(writer_global_set)
print(f"Total titles: {title_count}")
print(f"Total appearances: {writer_appearance_count}")
print(f"Total individual writers: {writer_global_count}")
print(f"{bcolors.OKGREEN}Instances of writers already set: {writer_already_set_count}{bcolors.ENDC}")
print(f"{bcolors.WARNING}Instances of writers not yet set: {writer_missing_count}{bcolors.ENDC}")
print("")
