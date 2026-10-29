"""Phone alerts through ntfy (https://ntfy.sh): free, no account. Install the ntfy app and subscribe to this Pi's topic.

Each Pi makes up its own long random topic on first use; anyone who knows it can read the alerts, so it is only
shown on this Pi's own page and app. A different server (a self-hosted ntfy) can be set instead.
"""

import json
import os
import secrets
import subprocess
import threading
import urllib.request

DEFAULTS = {"enabled": False, "server": "https://ntfy.sh", "topic": "", "pictures": True}
_lock = threading.Lock()


def data_dir():
    return os.environ.get("NIKON_DATA", "/var/lib/nikon-d3400")


def path():
    return os.path.join(data_dir(), "notify.json")


def load():
    try:
        with open(path()) as handle:
            data = {**DEFAULTS, **json.load(handle)}
    except (OSError, ValueError):
        data = dict(DEFAULTS)
    if not data["topic"]:
        data["topic"] = "nikon-d3400-" + secrets.token_hex(8)
        save(data)
    return data


def save(data):
    os.makedirs(data_dir(), exist_ok=True)
    with open(path(), "w") as handle:
        json.dump(data, handle)
    os.chmod(path(), 0o600)
    return data


def update(fields):
    with _lock:
        data = load()
        if "enabled" in fields:
            data["enabled"] = bool(fields["enabled"])
        if "pictures" in fields:
            data["pictures"] = bool(fields["pictures"])
        if fields.get("server"):
            server = str(fields["server"]).strip().rstrip("/")
            if not server.startswith(("https://", "http://")):
                raise ValueError("The server needs to start with https://")
            data["server"] = server
        if fields.get("new_topic"):
            data["topic"] = "nikon-d3400-" + secrets.token_hex(8)
        return save(data)


def public(data=None):
    data = data or load()
    return {**data, "url": data["server"] + "/" + data["topic"]}


def _ascii(text):
    """HTTP headers have to be plain ASCII."""
    return (text or "").replace("°", " deg").replace("—", "-").replace("’", "'").encode("ascii", "replace").decode()


def small_jpeg(source):
    """A ~1000 px copy of a picture for the alert, so a phone on cellular isn't sent 6 MB."""
    dest = os.path.join(data_dir(), "notify-picture.jpg")
    try:
        done = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", source, "-vf", "scale=1000:-2", "-q:v", "5", dest],
                              capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return dest if done.returncode == 0 and os.path.isfile(dest) else None


def send(title, message, tags="", priority=3, picture=None, force=False):
    """Post one alert. Never raises: a failed alert must not stop a night of shooting. Returns an error or ''."""
    data = load()
    if not data["enabled"] and not force:
        return "Alerts are off."
    url = data["server"] + "/" + data["topic"]
    headers = {"Title": _ascii(title), "Priority": str(priority)}
    if tags:
        headers["Tags"] = tags
    body = message.encode()
    method = "POST"
    attach = small_jpeg(picture) if picture and data.get("pictures") else None
    if attach:
        with open(attach, "rb") as handle:
            body = handle.read()
        headers["Filename"] = "aurora.jpg"
        headers["Message"] = _ascii(message)
        method = "PUT"
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        return ""
    except Exception as exc:
        return "The alert didn't go out: " + str(exc)
