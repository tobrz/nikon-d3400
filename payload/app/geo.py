"""Time and GPS for pictures when SnapBridge is not connected.

The D3400 has no GPS of its own. SnapBridge is what writes a phone's
location into the camera. With SnapBridge off, the Pi sets the camera
clock from its own clock and writes a saved location into files after
they land on the Pi.
"""

import json
import os
import shutil
import subprocess

STAMP_EXTS = {".jpg", ".jpeg", ".nef", ".nrw", ".tif", ".tiff"}


def data_dir():
    return os.environ.get("NIKON_DATA", "/var/lib/nikon-d3400")


def path():
    return os.path.join(data_dir(), "geo.json")


def load():
    try:
        with open(path()) as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        data = {}
    data.setdefault("snapbridge", False)
    data.setdefault("lat", None)
    data.setdefault("lon", None)
    data.setdefault("alt", None)
    return data


def save(data):
    os.makedirs(data_dir(), exist_ok=True)
    with open(path(), "w") as handle:
        json.dump(data, handle)
    return data


def update(fields):
    data = load()
    if "snapbridge" in fields:
        data["snapbridge"] = bool(fields["snapbridge"])
    for key in ("lat", "lon", "alt"):
        if key not in fields:
            continue
        raw = fields[key]
        if raw is None or raw == "":
            data[key] = None
        else:
            data[key] = float(raw)
    if data["lat"] is not None and not -90 <= data["lat"] <= 90:
        raise ValueError("Latitude has to be between -90 and 90.")
    if data["lon"] is not None and not -180 <= data["lon"] <= 180:
        raise ValueError("Longitude has to be between -180 and 180.")
    return save(data)


def exif_args(lat, lon, alt=None):
    lat = float(lat)
    lon = float(lon)
    args = [
        "-overwrite_original",
        f"-GPSLatitude={abs(lat)}",
        f"-GPSLatitudeRef={'N' if lat >= 0 else 'S'}",
        f"-GPSLongitude={abs(lon)}",
        f"-GPSLongitudeRef={'E' if lon >= 0 else 'W'}",
    ]
    if alt is not None and alt != "":
        alt = float(alt)
        args.append(f"-GPSAltitude={abs(alt)}")
        args.append(f"-GPSAltitudeRef={'0' if alt >= 0 else '1'}")
    return args


def stamp(file_path, runner=None):
    state = load()
    if state.get("snapbridge"):
        return {"skipped": "snapbridge", "file": os.path.basename(file_path)}
    if state.get("lat") is None or state.get("lon") is None:
        return {"skipped": "no location", "file": os.path.basename(file_path)}
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in STAMP_EXTS:
        return {"skipped": "not a photo", "file": os.path.basename(file_path)}
    if shutil.which("exiftool") is None and runner is None:
        return {"skipped": "exiftool is not installed yet", "file": os.path.basename(file_path)}
    cmd = ["exiftool", *exif_args(state["lat"], state["lon"], state.get("alt")), file_path]
    if runner is None:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "exiftool failed").strip()
            return {"error": detail, "file": os.path.basename(file_path)}
    else:
        runner(cmd)
    return {"stamped": True, "file": os.path.basename(file_path)}


def stamp_many(paths):
    return [stamp(item) for item in paths if item]


def before_shot(camera):
    """Set the camera clock when SnapBridge is not doing it."""
    if load().get("snapbridge"):
        return {"skipped": "snapbridge"}
    try:
        result = camera.set_clock()
    except Exception as exc:
        result = {"error": str(exc)}
    data = load()
    data["clock"] = result
    save(data)
    return result
