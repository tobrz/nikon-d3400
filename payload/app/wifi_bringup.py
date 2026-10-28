#!/usr/bin/env python3
"""Boot entry: join a known network or raise the Nikon-D3400 access point."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wifi import bringup

DATA = os.environ.get("NIKON_DATA", "/var/lib/nikon-d3400")
path = os.environ.get("NIKON_WIFI", os.path.join(DATA, "wifi.json"))
print(bringup(path))
