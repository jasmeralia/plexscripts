#!/usr/bin/env python3

import os
import json

ofdl_mappings = {}
# Opening JSON file
with open('indie_usernames_to_map.json') as json_file:
    indieMappings = json.load(json_file)
    for userName, modelName in sorted(indieMappings.items()):
        mapping = {}
        mapping["MessageFileNameFormat"]     = f"{modelName} - Message - {{mediaCreatedAt}}_{{id}}_{{mediaid}}"
        mapping["PaidMessageFileNameFormat"] = f"{modelName} - PPV Message - {{mediaCreatedAt}}_{{id}}_{{mediaid}}"
        mapping["PaidPostFileNameFormat"]    = f"{modelName} - PPV Post - {{mediaCreatedAt}}_{{id}}_{{mediaid}}"
        mapping["PostFileNameFormat"]        = f"{modelName} - Post - {{mediaCreatedAt}}_{{id}}_{{mediaid}}"
        # print(json.dumps(mapping, indent=2))
        ofdl_mappings[userName] = mapping

ofdl_full_dict = {}
ofdl_full_dict["CreatorConfigs"] = ofdl_mappings
json_object = json.dumps(ofdl_full_dict, indent=2) 
print(json_object)
