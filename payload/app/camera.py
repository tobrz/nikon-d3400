"""Nikon D3400 access through gphoto2.

Every control the camera actually exposes is read from gphoto2 at runtime.
Nothing here invents a setting the body did not return.
"""

import os
import re
import subprocess
import threading
from datetime import datetime


class CameraError(RuntimeError):
    pass


def parse_configs(text):
    """Parse `gphoto2 --list-all-config` into a list of control dicts."""
    blocks = []
    cur = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("/") and not line.startswith("//"):
            if cur:
                blocks.append(cur)
            cur = {"path": line.strip(), "choices": [], "readonly": False, "type": "TEXT", "current": ""}
            continue
        if cur is None:
            continue
        if line.startswith("Label:"):
            cur["label"] = line.split(":", 1)[1].strip()
        elif line.startswith("Readonly:"):
            cur["readonly"] = line.split(":", 1)[1].strip() in ("1", "true", "True")
        elif line.startswith("Type:"):
            cur["type"] = line.split(":", 1)[1].strip()
        elif line.startswith("Current:"):
            cur["current"] = line.split(":", 1)[1].strip()
        elif line.startswith("Bottom:"):
            cur["bottom"] = line.split(":", 1)[1].strip()
        elif line.startswith("Top:"):
            cur["top"] = line.split(":", 1)[1].strip()
        elif line.startswith("Step:"):
            cur["step"] = line.split(":", 1)[1].strip()
        elif line.startswith("Choice:"):
            rest = line.split(":", 1)[1].strip()
            index, _, label = rest.partition(" ")
            cur["choices"].append({"index": index, "label": label or index})
        elif line.strip() == "END":
            blocks.append(cur)
            cur = None
    if cur:
        blocks.append(cur)
    for block in blocks:
        block.setdefault("label", block["path"].rsplit("/", 1)[-1])
        block["key"] = block["path"].rsplit("/", 1)[-1]
    return blocks


def parse_files(text):
    """Parse `gphoto2 --list-files --recurse` into folder/index/name rows."""
    files = []
    folder = ""
    for line in text.splitlines():
        folder_match = re.search(r"in folder '([^']+)'", line)
        if folder_match:
            folder = folder_match.group(1)
            continue
        row = re.match(r"^#(\d+)\s+(\S+)", line.strip())
        if row and folder:
            files.append({"folder": folder, "index": int(row.group(1)), "name": row.group(2)})
    return files


def deletion_order(files):
    """Highest index first inside each folder.

    gphoto2 numbers the files that are still on the card. Deleting a lower
    number first can make a later number point at a different picture.
    """
    grouped = {}
    for item in files:
        grouped.setdefault(item["folder"], []).append(item)
    ordered = []
    for folder in grouped:
        ordered.extend(sorted(grouped[folder], key=lambda row: row["index"], reverse=True))
    return ordered


class Camera:
    def __init__(self, shots_dir):
        self.shots_dir = shots_dir
        self._lock = threading.Lock()
        os.makedirs(shots_dir, exist_ok=True)

    def run(self, args, timeout=45):
        try:
            done = subprocess.run(
                ["gphoto2", *args],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise CameraError("gphoto2 is not installed yet. Plug in ethernet and let the first boot finish.") from exc
        except subprocess.TimeoutExpired as exc:
            raise CameraError("The camera did not answer in time. Wake it and set USB to MTP/PTP.") from exc
        if done.returncode != 0:
            detail = (done.stderr or done.stdout or "").strip()
            raise CameraError(detail or f"gphoto2 failed ({done.returncode})")
        return done.stdout

    def connected(self):
        try:
            text = self.run(["--auto-detect"], timeout=12)
        except CameraError:
            return None
        for line in text.splitlines():
            if "usb:" in line.lower() and not line.lower().startswith("model"):
                model = line.rsplit("usb:", 1)[0].strip()
                return {"model": model, "port": "usb:" + line.rsplit("usb:", 1)[1].strip()}
        return None

    def summary(self):
        with self._lock:
            text = self.run(["--summary"], timeout=25)
        return text

    def abilities(self):
        with self._lock:
            return self.run(["--abilities"], timeout=20)

    def configs(self):
        with self._lock:
            text = self.run(["--list-all-config"], timeout=60)
        return parse_configs(text)

    def set_config(self, path, value):
        if not path.startswith("/"):
            raise CameraError("Control path must come from the camera.")
        with self._lock:
            self.run(["--set-config", f"{path}={value}"], timeout=25)
        return {"path": path, "value": value}

    def apply_settings(self, settings):
        """Set each path that exists. Return what stuck and what the body refused."""
        applied, skipped = [], []
        try:
            known = {item["path"]: item for item in self.configs()}
        except CameraError as exc:
            return {"applied": [], "skipped": [{"path": k, "value": v, "reason": str(exc)} for k, v in settings.items()]}
        by_key = {}
        for item in known.values():
            by_key.setdefault(item["key"], item["path"])
        for key, value in settings.items():
            path = key if key.startswith("/") else by_key.get(key)
            if not path or path not in known:
                skipped.append({"path": key, "value": value, "reason": "This body did not offer that control."})
                continue
            item = known[path]
            if item.get("readonly"):
                skipped.append({"path": path, "value": value, "reason": "Read only."})
                continue
            try:
                self.set_config(path, value)
                applied.append({"path": path, "value": value, "label": item.get("label", path)})
            except CameraError as exc:
                skipped.append({"path": path, "value": value, "reason": str(exc)})
        return {"applied": applied, "skipped": skipped}

    def capture(self):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = os.path.join(self.shots_dir, f"shot-{stamp}.%C")
        with self._lock:
            try:
                text = self.run(
                    ["--capture-image-and-download", "--filename", filename, "--force-overwrite"],
                    timeout=90,
                )
                mode = "capture-image-and-download"
            except CameraError:
                text = self.run(["--trigger-capture"], timeout=30)
                mode = "trigger-capture"
        saved = _saved_paths(text, self.shots_dir)
        return {"mode": mode, "output": text.strip(), "files": saved}

    def trigger(self):
        with self._lock:
            text = self.run(["--trigger-capture"], timeout=20)
        return {"output": text.strip()}

    def preview(self, path):
        """One live-view frame. Turns the viewfinder on when the body allows it."""
        with self._lock:
            for spec in ("viewfinder=1", "/main/actions/viewfinder=1", "liveview=1"):
                try:
                    self.run(["--set-config", spec], timeout=8)
                    break
                except CameraError:
                    continue
            self.run(["--capture-preview", "--filename", path, "--force-overwrite"], timeout=25)
        return path

    def focus(self, direction):
        moves = {
            "near3": ("manualfocusdrive", "Near 3"),
            "near2": ("manualfocusdrive", "Near 2"),
            "near1": ("manualfocusdrive", "Near 1"),
            "far1": ("manualfocusdrive", "Far 1"),
            "far2": ("manualfocusdrive", "Far 2"),
            "far3": ("manualfocusdrive", "Far 3"),
            "auto": ("autofocusdrive", "1"),
        }
        if direction not in moves:
            raise CameraError("Unknown focus move.")
        key, value = moves[direction]
        with self._lock:
            try:
                self.run(["--set-config", f"{key}={value}"], timeout=20)
            except CameraError as exc:
                raise CameraError(
                    f"The D3400 refused {key}. Live view has to be on, and the lens switch may need to be on A for autofocus or M for the near/far steps. {exc}"
                ) from exc
        return {"direction": direction, "set": f"{key}={value}"}

    def pull(self, folder, index, name):
        safe = os.path.basename(name) or f"frame-{index}.jpg"
        dest = os.path.join(self.shots_dir, safe)
        if os.path.exists(dest):
            stem, ext = os.path.splitext(safe)
            dest = os.path.join(self.shots_dir, f"{stem}-{index}{ext}")
        with self._lock:
            self.run(
                ["--folder", folder, "--get-file", str(index), "--filename", dest, "--force-overwrite"],
                timeout=120,
            )
        if os.path.getsize(dest) <= 0:
            raise CameraError(f"{os.path.basename(dest)} arrived empty, so it was not removed from the camera.")
        return {"name": os.path.basename(dest), "path": dest, "bytes": os.path.getsize(dest)}

    def delete_file(self, folder, index):
        with self._lock:
            self.run(["--folder", folder, "--delete-file", str(index)], timeout=40)
        return {"folder": folder, "index": index}

    def list_files(self):
        with self._lock:
            text = self.run(["--list-files", "--recurse"], timeout=40)
        return parse_files(text)

    def download_new(self, already):
        """Download files whose folder+name were not in `already` (a set of 'folder/name')."""
        current = self.list_files()
        fresh = [item for item in current if f"{item['folder']}/{item['name']}" not in already]
        saved = []
        for item in fresh:
            dest = os.path.join(self.shots_dir, item["name"])
            if os.path.exists(dest):
                stem, ext = os.path.splitext(item["name"])
                dest = os.path.join(self.shots_dir, f"{stem}-{item['index']}{ext}")
            with self._lock:
                self.run(
                    ["--folder", item["folder"], "--get-file", str(item["index"]), "--filename", dest, "--force-overwrite"],
                    timeout=90,
                )
            saved.append(dest)
        return saved


def _saved_paths(text, folder):
    found = []
    for line in text.splitlines():
        match = re.search(r"Saving file as ([^\s]+)", line)
        if match:
            name = match.group(1)
            found.append(name if os.path.isabs(name) else os.path.join(folder, name))
    if found:
        return found
    # gphoto2 sometimes only prints the filename it was given, with %C expanded on disk.
    return []
