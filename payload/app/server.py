#!/usr/bin/env python3
"""Web console for a headless Nikon D3400 tethered to a Raspberry Pi."""

import io
import json
import os
import shutil
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from camera import Camera, CameraError
from guide import plan, rephrase
from jobs import Jobs
from update import REPO, UpdateError, apply_update, read_revision
from wifi import AP_ADDRESS, bringup, load_networks, save_networks, wifi_state

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
        return self.headers.get("X-Nikon-Password", "") == password()

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
        elif path == "/api/shots.zip":
            self._zip_shots()
        elif path == "/api/wifi":
            self._guard(lambda: wifi_state(WIFI_PATH), wifi=True)
        elif path == "/preview.jpg":
            preview = os.path.join(DATA, "preview.jpg")
            try:
                CAMERA.preview(preview)
            except CameraError as exc:
                self._send(502, {"error": str(exc)})
                return
            self._file(preview, "image/jpeg")
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
            self._guard(CAMERA.capture)
        elif path == "/api/focus":
            self._guard(lambda: CAMERA.focus(str(body.get("direction", ""))))
        elif path == "/api/camera-files/pull":
            self._pull(body)
        elif path == "/api/apply":
            settings = body.get("settings") or {}
            self._guard(lambda: CAMERA.apply_settings({str(k): str(v) for k, v in settings.items()}))
        elif path == "/api/timelapse/start":
            self._guard(lambda: JOBS.start_timelapse(body.get("interval", 10), body.get("count", 0)))
        elif path == "/api/timelapse/stop":
            self._send(200, JOBS.stop_timelapse())
        elif path == "/api/lightning/start":
            self._guard(lambda: JOBS.start_lightning(body.get("frames", 30), body.get("gap", 0.4)))
        elif path == "/api/lightning/stop":
            self._send(200, JOBS.stop_lightning())
        elif path == "/api/guide":
            self._guide(body)
        elif path == "/api/wifi":
            self._add_wifi(body)
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
        folder = os.path.join(DATA, "shots")
        rows = []
        for name in sorted(os.listdir(folder), reverse=True):
            path = os.path.join(folder, name)
            if not os.path.isfile(path):
                continue
            rows.append({"name": name, "size": os.path.getsize(path)})
        return rows[:200]

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
        kind = "image/jpeg" if name.lower().endswith((".jpg", ".jpeg")) else "application/octet-stream"
        disposition = f'attachment; filename="{name}"' if download else ""
        self._file(path, kind, disposition)

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


def main():
    port = int(os.environ.get("NIKON_PORT", "80"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
