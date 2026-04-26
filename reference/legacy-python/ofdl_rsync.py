#!/usr/bin/env python3

import os
import json
import paramiko

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
# OF-DL directories that contain videos
#
videoDirectories = [
    "Archived/Posts/Free/Videos",
    "Messages/Free/Videos",
    "Messages/Paid/Videos",
    "Posts/Free/Videos",
    "Posts/Paid/Videos"
]

#
# settings, ultimately to be moved to a config file
#
ofdlDataDir = "/mnt/f/onlyfans/data"
remoteFilePath = "/mnt/myzmirror/plexdata/NSFW Scenes"
remoteHostName = "truenas.windsofstorm.net"
remoteUserName = "morgan"
remoteTarget = f"{remoteUserName}@{remoteHostName}:{remoteFilePath}"
sshKeyPath = "/home/morgan/.ssh/id_ed25519"

#
# set up SSH connection
#
ssh = paramiko.SSHClient()
sshPrivKey = paramiko.Ed25519Key.from_private_key_file(sshKeyPath)
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(hostname=remoteHostName, username=remoteUserName, pkey=sshPrivKey)
sftp = ssh.open_sftp()

# Opening JSON file
with open('indie_usernames_to_map.json') as json_file:
    indieMappings = json.load(json_file)
    for userName,modelName in sorted(indieMappings.items()):
        sftp.chdir(remoteFilePath)
        remoteModelPath = f"{remoteFilePath}/{modelName}"
        print(f"Checking if '{remoteModelPath}' exists on {remoteHostName}\n")
        if modelName not in sftp.listdir(remoteFilePath):
            # Create directory on remote server if needed.
            sftp.mkdir(os.path.join(remoteFilePath, modelName))
            # print(f"{bcolors.WARNING}Directory did not exist, created!{bcolors.ENDC}")
        # else:
            # print(f"{bcolors.OKGREEN}Directory does exist on {remoteHostName}.{bcolors.ENDC}")
        for videoDir in videoDirectories:
            userVideoPath = f"{ofdlDataDir}/{userName}/{videoDir}"
            # print(f"Checking path '{userVideoPath}'...")
            if os.path.exists(userVideoPath):
                # print(f"{bcolors.OKGREEN}Directory '{userVideoPath}' exists!{bcolors.ENDC}")
                for sourceFileName in os.listdir(userVideoPath):
                    sourceFilePath = os.path.join(userVideoPath, sourceFileName)
                    if os.path.isfile(sourceFilePath):
                        print(f"{bcolors.OKCYAN}Found file '{sourceFileName}'{bcolors.ENDC}")
                        newFileName = sourceFileName.replace(userName, modelName)
                        newFilePath = f"{remoteModelPath}/{newFileName}"
                        print(f"{bcolors.OKCYAN}Target: {newFilePath}{bcolors.ENDC}")
                        if newFileName not in sftp.listdir(remoteModelPath):
                            print(f"{bcolors.FAIL}{newFileName} does not exist on {remoteModelPath}!{bcolors.ENDC}")
                            sftp.put(sourceFilePath, newFilePath)
                            print(f"{bcolors.OKGREEN}Finished copying {newFileName}.{bcolors.ENDC}")
                        else:
                            print(f"{bcolors.OKGREEN}{newFileName} does exist on {remoteModelPath}, skipping!{bcolors.ENDC}")
            # else:
                # print(f"{bcolors.WARNING}Directory '{userVideoPath}' does not exist!{bcolors.ENDC}")
        print()
        print()
