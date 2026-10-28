"""Compare the D3400 C firmware with the version Nikon publishes."""

import re
import urllib.request

NIKON_PAGE = "https://downloadcenter.nikonimglib.com/en/download/fw/284.html"


def version_key(text):
    match = re.search(r"(\d+)\.(\d+)", text or "")
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)))


def parse_published(page):
    """The Nikon download page says which C version the file installs."""
    match = re.search(r"firmware to version\s+(\d+\.\d+)", page or "", re.I)
    if not match:
        match = re.search(r"Firmware Version\s+(\d+\.\d+)", page or "", re.I)
    return match.group(1) if match else ""


def parse_camera(summary):
    match = re.search(r"Device Version:\s*(\S+)", summary or "")
    return match.group(1) if match else ""


def compare(camera_text, published_text):
    camera = version_key(camera_text)
    published = version_key(published_text)
    if camera is None or published is None:
        relation = "unknown"
    elif camera == published:
        relation = "current"
    elif camera < published:
        relation = "behind"
    else:
        relation = "newer"
    return {
        "camera": camera_text or "",
        "published": published_text or "",
        "relation": relation,
        "url": NIKON_PAGE,
    }


def published_version():
    request = urllib.request.Request(NIKON_PAGE, headers={"User-Agent": "nikon-d3400"})
    with urllib.request.urlopen(request, timeout=20) as response:
        page = response.read().decode("utf-8", "replace")
    found = parse_published(page)
    if not found:
        raise RuntimeError("Nikon's download page did not name a firmware version.")
    return found
