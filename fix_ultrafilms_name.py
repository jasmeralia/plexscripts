#!/usr/bin/env python3

import os
import sys

def titleize(s):
    return ' '.join([word.capitalize() for word in s.replace('_', ' ').split()])

replacements = {
    'Bella Spark': 'Bella Spark aka Emma White',
    'Emma White': 'Bella Spark aka Emma White',
    'Black Angel': 'Black Angel aka Kate Rose',
    'Kate Rose': 'Black Angel aka Kate Rose',
    'Catalina': 'Catalina aka Crystal Gold',
    'Crystal Gold': 'Catalina aka Crystal Gold',
    'Elin Flame': 'Elin Flame aka Elin Holm',
    'Elin Holm': 'Elin Flame aka Elin Holm',
    'Kamy': 'Kamy aka Leona Mia',
    'Leona Mia': 'Kamy aka Leona Mia',
    'Madison': 'Karina Grand aka Madison',
    'Karina Grant': 'Karina Grand aka Madison',
    'Leona Levi': 'Leona Levi aka Zoi',
    'Zoi': 'Leona Levi aka Zoi',
    'Clany': 'Marceline Moore aka Clany',
    'Marceline Moore': 'Marceline Moore aka Clany',
    'Mia Ferrari': 'Mia Ferrari aka Shelly Bliss',
    'Shelly Bliss': 'Mia Ferrari aka Shelly Bliss',
    'Divina': 'Sheri Vi aka Divina',
    'Sheri Vi': 'Sheri Vi aka Divina',
    'SpookyBooBoo': 'SpookyBooBoo aka Deloris Jean',
    'Deloris Jean': 'SpookyBooBoo aka Deloris Jean',
    'Nancy A': 'Nancy Ace'
}

DEBUG = 0
if len(sys.argv) < 2 or sys.argv[1] == '':
    print("Usage: fix_ultrafilms_name.py <video name>")
    sys.exit(1)

FNAME = sys.argv[1]
base_dir = '/home/morgan/Downloads'
old_path = os.path.join(base_dir, FNAME)
if not os.path.isfile(old_path):
    print(f"Error: file '{old_path}' does not exist!")
    sys.exit(1)

parts = FNAME.split('_', 1)
title = parts[0].replace('-', ' ')
actress_info = parts[1] if len(parts) > 1 else ''
actresses = actress_info.split('_')
writers = []
for actress in actresses:
    if not any(char.isdigit() for char in actress):
        this_actress = titleize(actress.replace('-', ' '))
        writer = replacements.get(this_actress, this_actress)
        writers.append(writer)

writer_str = ', '.join(writers)
new_fname = f"{writer_str} - {titleize(title)}.mp4"
new_path = os.path.join(base_dir, new_fname)
print(f"Old filename: {old_path}")
print(f"New filename: {new_path}")
os.rename(old_path, new_path)
print("Done renaming file.")