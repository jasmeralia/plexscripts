#!/usr/bin/env python3

import os
import re
import sys

DEBUG = 0
START_NAME = 'TBD - ' if len(sys.argv) < 2 or sys.argv[1] == '' else f"{sys.argv[1]} - "
base_dir = '/home/morgan/Downloads'
file_list = [f for f in os.listdir(base_dir) if os.path.isfile(os.path.join(base_dir, f))]

for orig_fname in file_list:
    if not orig_fname.endswith(".mp4"):
        continue
    if not orig_fname.startswith("Scene "):
        continue
    if DEBUG == 1:
        print(f"Original Filename: {orig_fname}")
    match = re.match(r"Scene ([0-9]+) From .*", orig_fname)
    if not match:
        print(f"Error: Could not find scene number in string match of '{orig_fname}'!")
        sys.exit(1)
    scene_number = match.group(1)
    if DEBUG == 1:
        print(f"Scene number: {scene_number}")
    new_fname = re.sub(rf"Scene {scene_number} From ", START_NAME, orig_fname)
    new_fname = re.sub(r" - 2160p", '', new_fname)
    new_fname = re.sub(r" - 1080p", '', new_fname)
    new_fname = re.sub(r" - 720p", '', new_fname)
    new_fname = re.sub(r" - 480p", '', new_fname)
    new_fname = re.sub(r" - 360p", '', new_fname)
    new_fname = re.sub(r" - Low", '', new_fname)
    new_fname = re.sub(r" Volume ", ' ', new_fname)
    new_fname = re.sub(r" Vol ", ' ', new_fname)
    new_fname = re.sub(r"Vol([0-9]+)\.mp4", r"#\1.mp4", new_fname)
    new_fname = re.sub(r"V([0-9]+)\.mp4", r"#\1.mp4", new_fname)
    new_fname = re.sub(r" ([0-9]+)\.mp4", r" #\1.mp4", new_fname)
    new_fname = re.sub(r"(.*) - (.*) The\.mp4", r"\1 - The \2.mp4", new_fname)
    new_fname = re.sub(r"\.mp4", f" (Scene #{scene_number}).mp4", new_fname)
    print(f"Renaming '{orig_fname}' to '{new_fname}'...")
    os.rename(os.path.join(base_dir, orig_fname), os.path.join(base_dir, new_fname))
    print("Done.")
