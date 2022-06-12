# Copyright 2021 VicEdTools authors

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Executable script for exporting Compass class metadata."""

import argparse
import json
import sys
import os

from vicedtools.compass.compasssession import CompassSession, CompassAuthenticator


if __name__ == "__main__":
    from config import (academic_groups_json,
                        compass_authenticator, compass_school_code, class_details_dir)
    if not os.path.exists(class_details_dir):
        os.makedirs(class_details_dir)

    parser = argparse.ArgumentParser(
    description='Export Compass class metadata.')
    parser.add_argument('academic_group', type=int, default=-1, nargs='?', help='the academic group to export')
    args = parser.parse_args()    
    
    with open(academic_groups_json, 'r', encoding='utf-8') as f:
        cycles = json.load(f)
    if args.academic_group != -1:

        cycle_found = False
        for cycle in cycles:
            if cycle['id'] == args.academic_group:
                cycle_found = True
                cycle_name = cycle['name']
                break
        if not cycle_found:
            print("Academic group not found.")
            sys.exit(-2)
    else:
        for cycle in cycles:
            if cycle['isRelevant']:
                cycle_name = cycle['name']
                break


    s = CompassSession(compass_school_code, compass_authenticator)
    cycles = s.get_classes(args.academic_group)
    filename = os.path.join(class_details_dir, f"{cycle_name} classes.json")
    with open(filename, "w", encoding='utf-8') as f:
        json.dump(cycles, f)

    sys.exit(0)
