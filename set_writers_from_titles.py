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
plexHost = config['default']['plexHost']
plexPort = config['default']['plexPort']
plexSection = config['default']['plexSection']
plexToken = config['default']['plexToken']
plexSectionName = config['default']['plexSectionName']
baseurl = f"http://{plexHost}:{plexPort}"
#
# Connect to server
#
plex = PlexServer(baseurl, plexToken)
#
# Select section
#
writerGlobalSet = set()
plexSection = plex.library.section(plexSectionName)
titleCount = 0
writerAppearanceCount = 0
writerMissingCount = 0
writerAlreadySetCount = 0
results = plexSection.all()
totalVideoCount = len(results)
for video in results:
    titleCount += 1
    # ensure data is up to date
    if video.isPartialObject():
        video.reload()
    progressString = f"[{titleCount}/{totalVideoCount}] "
    # replace nbsp; with space and emdash with hyphen... fuck utf8!
    thisTitle = video.title.replace(" – ", " - ").replace("\xa0", " ")
    writerNames = thisTitle.split(' - ', 1)[0]
    writersList = writerNames.split(',')
    strippedSet = set()
    someWritersMissing = False
    for writerName in writersList:
        strippedName = writerName.strip()
        strippedSet.add(strippedName)
        # print(f"Found writer: {writerName}")
        writerGlobalSet.add(strippedName)
        writerAppearanceCount += 1
        writerAlreadySet = False
        for thiswriter in video.writers:
            if f"{thiswriter}".lower() == strippedName.lower():
                writerAlreadySet = True
        if writerAlreadySet:
            # print(f"{bcolors.OKGREEN}Writer '{strippedName}' already set on this title.{bcolors.ENDC}")
            writerAlreadySetCount += 1
        else:
            print(f"{bcolors.WARNING}{progressString}Writer '{strippedName}' not yet set on {video.title}, need to add it!{bcolors.ENDC}")
            writerMissingCount += 1
            someWritersMissing = True
    if someWritersMissing:
        print(f"{bcolors.WARNING}{progressString}List extracted from title: ", end="")
        pprint(sorted(strippedSet))
        print(f"{bcolors.OKCYAN}{progressString}Current list in Plex: ", end="")
        pprint(video.writers)
        print(f"{bcolors.WARNING}{progressString}Updating list...{bcolors.ENDC}")
        video.addWriter(sorted(strippedSet), True)
        print(f"{bcolors.OKGREEN}{progressString}Writers list updated!{bcolors.ENDC}")
        print('')

writerGlobalCount = len(writerGlobalSet)
print(f"Total titles: {titleCount}")
print(f"Total appearances: {writerAppearanceCount}")
print(f"Total individual writers: {writerGlobalCount}")
print(f"{bcolors.OKGREEN}Instances of writers already set: {writerAlreadySetCount}{bcolors.ENDC}")
print(f"{bcolors.WARNING}Instances of writers not yet set: {writerMissingCount}{bcolors.ENDC}")
print('')
