#!/usr/bin/env python
#
# import modules
#
import sys
import os
from pprint import pprint
from plexapi.server import PlexServer
#
# set default variables
#
plexHost = '192.168.1.25'
plexPort = 32_400
plexSection = 17
plexToken = 'v1-wDHYg2XymMhtz5rNz'
plexSectionName = 'NSFW Scenes'
baseURL = f"http://{plexHost}:{plexPort}"
#
# Connect to server
#
plex = PlexServer(baseURL, plexToken)
#
# Select section
#
mySection = plex.library.section(plexSectionName)
#
# Loop through models
#
modelFilters = {"writer": modelName}
modelTitle = f"0.3: Model: {starName}"
mySection.createCollection(title=modelTitle, smart=True, sort="title:asc", filters=modelFilters)
