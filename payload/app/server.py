#!/usr/bin/env python3
"""Web console for a headless Nikon D3400 tethered to a Raspberry Pi."""

import io
import json
import os
import shutil
import subprocess
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from camera import Camera, CameraError, jpeg_payload, optional_seconds, thumb_cache_key
import firmware
import aurora
import geo
from guide import plan, rephrase
from jobs import Jobs
from update import REPO, UpdateError, apply_update, check_update, read_revision
from wifi import AP_ADDRESS, bringup, load_networks, save_networks, scan_wifi, wifi_state

DATA = os.environ.get("NIKON_DATA", "/var/lib/nikon-d3400")
WIFI_PATH = os.environ.get("NIKON_WIFI", os.path.join(DATA, "wifi.json"))
PASSWORD_PATH = os.environ.get("NIKON_PASSWORD_FILE", os.path.join(DATA, "password"))
DEFAULT_PASSWORD = "nikon-d3400"
HERE = os.path.dirname(os.path.abspath(__file__))

os.makedirs(DATA, exist_ok=True)
os.makedirs(os.path.join(DATA, "shots"), exist_ok=True)
CAMERA = Camera(os.path.join(DATA, "shots"))
JOBS = Jobs(CAMERA)


def password():
    try:
        with open(PASSWORD_PATH) as handle:
            stored = handle.read().strip()
    except OSError:
        return DEFAULT_PASSWORD
    return stored or DEFAULT_PASSWORD


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode())

    def _send(self, code, payload, content_type="application/json", disposition=""):
        if not isinstance(payload, (bytes, bytearray)):
            payload = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        if disposition:
            self.send_header("Content-Disposition", disposition)
        self.end_headers()
        self.wfile.write(payload)

    def _authorized(self):
        secret = password()
        if self.headers.get("X-Nikon-Password", "") == secret:
            return True
        return password_from_cookie(self.headers.get("Cookie", "")) == secret

    def _require(self):
        if self._authorized():
            return True
        self._send(401, {"error": "Sign in. The factory password is nikon-d3400."})
        return False

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._file(os.path.join(HERE, "index.html"), "text/html; charset=utf-8")
            return
        if path == "/api/login-info":
            self._send(200, {"factory": password() == DEFAULT_PASSWORD, "address": AP_ADDRESS})
            return
        if not self._require():
            return
        if path == "/api/status":
            self._send(200, self._status())
        elif path == "/api/config":
            self._guard(lambda: {"controls": CAMERA.configs()})
        elif path == "/api/summary":
            self._guard(lambda: {"summary": CAMERA.summary(), "abilities": CAMERA.abilities()})
        elif path == "/api/jobs":
            self._send(200, JOBS.snapshot())
        elif path == "/api/shots":
            self._send(200, {"shots": self._shots()})
        elif path.startswith("/shots/"):
            query = parse_qs(urlparse(self.path).query)
            self._shot(unquote(path[len("/shots/"):]), download="download" in query)
        elif path == "/api/camera-files":
            self._guard(lambda: {"files": CAMERA.list_files()})
        elif path == "/api/camera-thumb":
            self._camera_thumb()
        elif path == "/api/shots.zip":
            self._zip_shots()
        elif path == "/api/firmware":
            self._firmware()
        elif path == "/api/wifi/scan":
            self._wifi_scan()
        elif path == "/api/wifi":
            self._guard(lambda: wifi_state(WIFI_PATH), wifi=True)
        elif path == "/api/geo":
            self._send(200, geo.load())
        elif path == "/api/aurora":
            self._aurora_outlook()
        elif path == "/preview.jpg":
            try:
                frame = CAMERA.preview(os.path.join(DATA, "preview.jpg"))
            except CameraError as exc:
                self._send(502, {"error": str(exc)})
                return
            self._send(200, frame, "image/jpeg")
        else:
            self._send(404, {"error": "Not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._body()
        except json.JSONDecodeError:
            self._send(400, {"error": "Send JSON."})
            return
        if path == "/api/login":
            if body.get("password", "") == password():
                self._send(200, {"ok": True})
            else:
                self._send(401, {"error": "Wrong password."})
            return
        if not self._require():
            return
        if path == "/api/password":
            new = str(body.get("password", "")).strip()
            if len(new) < 8:
                self._send(400, {"error": "Use at least 8 characters."})
                return
            with open(PASSWORD_PATH, "w") as handle:
                handle.write(new + "\n")
            os.chmod(PASSWORD_PATH, 0o600)
            self._send(200, {"ok": True})
        elif path == "/api/config":
            self._guard(lambda: CAMERA.set_config(str(body.get("path", "")), str(body.get("value", ""))))
        elif path == "/api/capture":
            self._guard(lambda: self._capture(body))
        elif path == "/api/geo":
            self._save_geo(body)
        elif path == "/api/geo/clock":
            self._guard(lambda: geo.before_shot(CAMERA))
        elif path == "/api/geo/stamp":
            self._stamp_saved()
        elif path == "/api/movie":
            self._guard(lambda: CAMERA.set_movie(bool(body.get("recording"))))
        elif path == "/api/focus":
            self._guard(lambda: CAMERA.focus(str(body.get("direction", ""))))
        elif path == "/api/camera-thumbs":
            self._camera_thumbs(body)
        elif path == "/api/camera-files/pull":
            self._pull(body)
        elif path == "/api/shots/delete":
            self._delete_shots(body)
        elif path == "/api/offload/start":
            self._guard(JOBS.start_offload)
        elif path == "/api/apply":
            settings = body.get("settings") or {}
            self._guard(lambda: CAMERA.apply_settings({str(k): str(v) for k, v in settings.items()}))
        elif path == "/api/timelapse/start":
            self._guard(lambda: JOBS.start_timelapse(
                body.get("interval", 10),
                body.get("count", 0),
                body.get("seconds"),
                body.get("fps", 24),
            ))
        elif path == "/api/timelapse/stop":
            self._send(200, JOBS.stop_timelapse())
        elif path == "/api/bracket/start":
            self._guard(lambda: JOBS.start_bracket(body.get("count", 3), body.get("step", 1)))
        elif path == "/api/bracket/stop":
            self._send(200, JOBS.stop_bracket())
        elif path == "/api/lightning/start":
            self._guard(lambda: JOBS.start_lightning(body.get("frames", 30), body.get("gap", 0.4)))
        elif path == "/api/lightning/stop":
            self._send(200, JOBS.stop_lightning())
        elif path == "/api/aurora/start":
            self._guard(lambda: JOBS.start_aurora(
                body.get("threshold", 30), body.get("interval", 20), body.get("seconds", 8),
                body.get("iso", "1600"), body.get("aperture", ""), body.get("check_minutes", 5), body.get("hours", 12),
            ))
        elif path == "/api/aurora/stop":
            self._send(200, JOBS.stop_aurora())
        elif path == "/api/guide":
            self._guide(body)
        elif path == "/api/wifi":
            self._add_wifi(body)
        elif path == "/api/update/check":
            self._update_check()
        elif path == "/api/update":
            self._update()
        else:
            self._send(404, {"error": "Not found"})

    def _status(self):
        gphoto = shutil.which("gphoto2") is not None
        model = CAMERA.connected() if gphoto else None
        try:
            radio = wifi_state(WIFI_PATH)
        except Exception as exc:
            radio = {"error": str(exc), "ap_address": AP_ADDRESS}
        return {
            "gphoto2": gphoto,
            "camera": model,
            "jobs": JOBS.snapshot(),
            "wifi": radio,
            "page": f"http://{AP_ADDRESS}",
            "revision": read_revision(),
            "repo": REPO,
        }

    def _capture(self, body=None):
        body = body or {}
        clock = geo.before_shot(CAMERA)
        result = CAMERA.capture(seconds=optional_seconds(body.get("seconds")))
        result["clock"] = clock
        return result

    def _aurora_outlook(self):
        state = geo.load()
        try:
            self._send(200, aurora.outlook(state.get("lat"), state.get("lon")))
        except aurora.AuroraError as exc:
            self._send(502, {"error": str(exc)})

    def _save_geo(self, body):
        try:
            self._send(200, geo.update(body))
        except (TypeError, ValueError) as exc:
            self._send(400, {"error": str(exc)})

    def _stamp_saved(self):
        folder = os.path.join(DATA, "shots")
        names = [os.path.join(folder, name) for name in os.listdir(folder)] if os.path.isdir(folder) else []
        self._send(200, {"results": geo.stamp_many(names)})

    def _update_check(self):
        try:
            self._send(200, check_update())
        except UpdateError as exc:
            self._send(502, {"error": str(exc)})

    def _update(self):
        try:
            self._send(200, apply_update())
        except UpdateError as exc:
            self._send(502, {"error": str(exc)})

    def _guide(self, body):
        text = str(body.get("text", "")).strip()
        if not text:
            self._send(400, {"error": "Say what you want to shoot."})
            return
        configs = []
        if shutil.which("gphoto2"):
            try:
                configs = CAMERA.configs()
            except CameraError:
                configs = []
        built = plan(text, configs)
        speech, model = rephrase(built)
        result = {
            "title": built["title"],
            "kind": built["kind"],
            "speech": speech,
            "model": model,
            "steps": built["steps"],
            "settings": built["settings"],
            "ready_step": built["ready_step"],
        }
        if body.get("apply"):
            try:
                result["apply"] = CAMERA.apply_settings(built["settings"])
            except CameraError as exc:
                result["apply"] = {"error": str(exc)}
        if body.get("shoot"):
            try:
                result["capture"] = CAMERA.capture()
            except CameraError as exc:
                result["capture"] = {"error": str(exc)}
        self._send(200, result)

    def _firmware(self):
        try:
            summary = CAMERA.summary()
            camera = firmware.parse_camera(summary)
            published = firmware.published_version()
            self._send(200, firmware.compare(camera, published))
        except CameraError as exc:
            self._send(502, {"error": str(exc)})
        except Exception as exc:
            self._send(502, {"error": str(exc)})

    def _wifi_scan(self):
        try:
            self._send(200, {"networks": scan_wifi()})
        except (RuntimeError, subprocess.TimeoutExpired, OSError) as exc:
            self._send(502, {"error": str(exc)})

    def _camera_thumb(self):
        query = parse_qs(urlparse(self.path).query)
        folder = (query.get("folder") or [""])[0]
        if not folder.startswith("/") or ".." in folder:
            self._send(400, {"error": "Bad folder"})
            return
        try:
            index = int((query.get("index") or [""])[0])
        except ValueError:
            self._send(400, {"error": "Bad index"})
            return
        name = (query.get("name") or [""])[0]
        cached = ""
        try:
            cached = os.path.join(DATA, "thumbs", thumb_cache_key(folder, name))
        except ValueError:
            cached = ""
        if cached and os.path.isfile(cached) and os.path.getsize(cached) > 0:
            self._file(cached, "image/jpeg")
            return
        dest = os.path.join(DATA, "thumb.jpg")
        try:
            frame = CAMERA.thumbnail(folder, index, dest, name=name)
        except CameraError as exc:
            self._send(502, {"error": str(exc)})
            return
        if cached and jpeg_payload(frame):
            os.makedirs(os.path.dirname(cached), exist_ok=True)
            temporary = cached + ".part"
            with open(temporary, "wb") as handle:
                handle.write(frame)
            os.replace(temporary, cached)
        self._send(200, frame, "image/jpeg")

    def _store_thumb(self, folder, name, frame):
        cached = os.path.join(DATA, "thumbs", thumb_cache_key(folder, name))
        os.makedirs(os.path.dirname(cached), exist_ok=True)
        temporary = cached + ".part"
        with open(temporary, "wb") as handle:
            handle.write(frame)
        os.replace(temporary, cached)

    def _camera_thumbs(self, body):
        """Fill the local thumbnail cache for many card files in one camera session per folder."""
        wanted = []
        for item in (body.get("files") or [])[:40]:
            if not isinstance(item, dict):
                continue
            folder = str(item.get("folder") or "")
            name = str(item.get("name") or "")
            if not folder.startswith("/") or ".." in folder:
                continue
            try:
                index = int(item.get("index"))
                thumb_cache_key(folder, name)
            except (TypeError, ValueError):
                continue
            wanted.append({"folder": folder, "index": index, "name": name})
        ready = []
        missing = {}
        for item in wanted:
            cached = os.path.join(DATA, "thumbs", thumb_cache_key(item["folder"], item["name"]))
            if os.path.isfile(cached) and os.path.getsize(cached) > 0:
                ready.append(item["name"])
                continue
            missing.setdefault(item["folder"], []).append(item)
        cached_count = len(ready)
        errors = []
        incoming = os.path.join(DATA, "thumbs", "incoming")
        for folder, items in missing.items():
            try:
                found = CAMERA.thumbnail_range(folder, [item["index"] for item in items], incoming)
            except CameraError as exc:
                errors.append(str(exc))
                continue
            for item in items:
                frame = found.get(item["name"])
                if not frame:
                    continue
                self._store_thumb(folder, item["name"], frame)
                ready.append(item["name"])
        self._send(200, {
            "ready": ready,
            "cached": cached_count,
            "fetched": len(ready) - cached_count,
            "errors": errors,
        })

    def _add_wifi(self, body):
        ssid = str(body.get("ssid", "")).strip()
        secret = str(body.get("password", ""))
        if not ssid:
            self._send(400, {"error": "The network needs a name."})
            return
        networks = [item for item in load_networks(WIFI_PATH) if item["ssid"] != ssid]
        networks.append({"ssid": ssid, "password": secret})
        save_networks(WIFI_PATH, networks)
        boot_copy = "/boot/firmware/nikon-wifi.json"
        if os.path.isdir("/boot/firmware"):
            save_networks(boot_copy, networks)
        try:
            mode = bringup(WIFI_PATH)
        except Exception as exc:
            self._send(200, {"saved": True, "warning": str(exc), "networks": [item["ssid"] for item in networks]})
            return
        self._send(200, {"saved": True, "mode": mode, "networks": [item["ssid"] for item in networks]})

    def _shots(self):
        return list_shot_rows(os.path.join(DATA, "shots"))

    def _delete_shots(self, body):
        folder = os.path.join(DATA, "shots")
        try:
            if body.get("all"):
                removed = delete_shots(folder, all_files=True)
            else:
                names = body.get("names")
                if isinstance(names, str):
                    names = [names]
                if not isinstance(names, list) or not names:
                    self._send(400, {"error": "Pick a picture."})
                    return
                removed = delete_shots(folder, names=names)
        except ValueError:
            self._send(400, {"error": "Bad picture name."})
            return
        except OSError as exc:
            self._send(500, {"error": str(exc)})
            return
        self._send(200, {"removed": removed, "count": len(removed)})

    def _pull(self, body):
        folder = str(body.get("folder", ""))
        if not folder.startswith("/"):
            self._send(400, {"error": "Pick a file the camera listed."})
            return
        try:
            index = int(body.get("index"))
        except (TypeError, ValueError):
            self._send(400, {"error": "Pick a file the camera listed."})
            return
        self._guard(lambda: CAMERA.pull(folder, index, str(body.get("name", ""))))

    def _shot(self, name, download=False):
        if "/" in name or name.startswith("."):
            self._send(400, {"error": "Bad name"})
            return
        path = os.path.join(DATA, "shots", name)
        if not os.path.isfile(path):
            self._send(404, {"error": "No such frame"})
            return
        query = parse_qs(urlparse(self.path).query)
        if "preview" in query and not name.lower().endswith((".jpg", ".jpeg", ".mp4")):
            preview = self._embedded_preview(path)
            if preview:
                self._send(200, preview, "image/jpeg")
                return
            self._send(404, {"error": "No preview in that file"})
            return
        lowered = name.lower()
        if lowered.endswith((".jpg", ".jpeg")):
            kind = "image/jpeg"
        elif lowered.endswith(".mp4"):
            kind = "video/mp4"
        else:
            kind = "application/octet-stream"
        disposition = f'attachment; filename="{name}"' if download else ""
        self._file(path, kind, disposition)

    def _embedded_preview(self, path):
        if not shutil.which("exiftool"):
            return b""
        for tag in ("PreviewImage", "JpgFromRaw", "OtherImage"):
            try:
                proc = subprocess.run(
                    ["exiftool", "-b", "-" + tag, path],
                    capture_output=True,
                    timeout=30,
                )
            except (OSError, subprocess.TimeoutExpired):
                return b""
            if proc.returncode == 0 and proc.stdout[:2] == b"\xff\xd8":
                return proc.stdout
        return b""

    def _zip_shots(self):
        folder = os.path.join(DATA, "shots")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as archive:
            for name in sorted(os.listdir(folder)):
                path = os.path.join(folder, name)
                if os.path.isfile(path):
                    archive.write(path, arcname=name)
        data = buf.getvalue()
        self._send(200, data, "application/zip", 'attachment; filename="nikon-d3400.zip"')

    def _file(self, path, content_type, disposition=""):
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError:
            self._send(404, {"error": "Missing file"})
            return
        self._send(200, data, content_type, disposition)

    def _guard(self, fn, wifi=False):
        try:
            self._send(200, fn())
        except CameraError as exc:
            self._send(502, {"error": str(exc)})
        except Exception as exc:
            if wifi:
                self._send(200, {"error": str(exc), "ap_address": AP_ADDRESS, "known": []})
                return
            self._send(500, {"error": str(exc)})


def password_from_cookie(header):
    """The page password stored so a normal link can download the zip."""
    for part in (header or "").split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name == "nikon-password":
            return unquote(value)
    return ""


def shot_filename(name):
    """A picture name with no folder. Rejects paths that could leave the shots directory."""
    text = str(name or "")
    base = os.path.basename(text)
    if not base or base in (".", "..") or base != text or "/" in text or "\\" in text:
        raise ValueError("Bad picture name")
    return base


def delete_shots(folder, names=None, all_files=False):
    """Remove pictures stored on the Pi. This does not touch the camera card."""
    os.makedirs(folder, exist_ok=True)
    folder_real = os.path.realpath(folder)
    if all_files:
        chosen = []
        for name in os.listdir(folder_real):
            if os.path.isfile(os.path.join(folder_real, name)):
                chosen.append(name)
    else:
        chosen = [shot_filename(name) for name in (names or [])]
    removed = []
    for name in chosen:
        path = os.path.join(folder_real, name)
        if os.path.realpath(os.path.dirname(path)) != folder_real:
            raise ValueError("Bad picture name")
        if not os.path.isfile(path):
            continue
        os.remove(path)
        removed.append(name)
    return removed


def list_shot_rows(folder):
    """Newest picture first. Name order put the raw file ahead of its JPEG."""
    rows = []
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    for name in names:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        try:
            stat = os.stat(path)
        except OSError:
            continue
        rows.append({"name": name, "size": stat.st_size, "mtime": stat.st_mtime})
    rows.sort(key=lambda row: (row["mtime"], row["name"]), reverse=True)
    return rows[:200]


def ensure_exiftool():
    """The shots page reads a JPEG out of a NEF. This Pi was imaged before that tool was present."""
    if shutil.which("exiftool"):
        return
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        return
    subprocess.run(["apt-get", "update"], timeout=180, check=False)
    subprocess.run(["apt-get", "install", "-y", "libimage-exiftool-perl"], timeout=300, check=False)


def main():
    threading.Thread(target=ensure_exiftool, daemon=True).start()
    port = int(os.environ.get("NIKON_PORT", "80"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
