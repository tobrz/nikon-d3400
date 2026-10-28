"""Nikon D3400 access through gphoto2.

Every control the camera actually exposes is read from gphoto2 at runtime.
Nothing here invents a setting the body did not return.
"""

import os
import re
import subprocess
import threading
from datetime import datetime

import geo


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


def thumb_cache_key(folder, name):
    """Stable file name for one camera picture. The index changes when files are deleted."""
    folder = (folder or "").replace("\\", "/").strip("/")
    name = (name or "").replace("\\", "/").strip()
    if not folder or not name or "/" in name or ".." in folder.split("/") or name in (".", ".."):
        raise ValueError("Bad thumbnail name")
    raw = folder + "/" + name
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._")
    if not safe:
        raise ValueError("Bad thumbnail name")
    return safe + ".jpg"


def jpeg_payload(blob):
    """Return the JPEG inside a gphoto2 stdout buffer, if one is there."""
    if not blob:
        return b""
    start = blob.find(b"\xff\xd8")
    if start < 0:
        return b""
    return blob[start:]


def preview_download_path(requested):
    """gphoto2 saves a preview as thumb_<name> in the same directory.

    --filename /var/lib/nikon-d3400/preview.jpg becomes thumb_preview.jpg.
    The page then looks for preview.jpg and reports a missing file.
    """
    directory, name = os.path.split(requested)
    if not name:
        name = "preview.jpg"
    return os.path.join(directory, "thumb_" + name)


def adopt_preview(requested):
    """Move gphoto2's thumb_ preview onto the path the page serves."""
    downloaded = preview_download_path(requested)
    if os.path.isfile(downloaded) and os.path.getsize(downloaded) > 0:
        if os.path.abspath(downloaded) != os.path.abspath(requested):
            os.replace(downloaded, requested)
        return requested
    if os.path.isfile(requested) and os.path.getsize(requested) > 0:
        return requested
    return ""


def live_view_block_reason(current):
    """Return a user-facing reason when live view is actually prohibited.

    The D3400 reports "Liveview should not be prohibited" when the dial is
    already on P, A, S, or M. That sentence is permission, not a block.
    """
    text = (current or "").strip()
    lowered = text.lower()
    if not text or lowered.startswith("no ") or "should not be prohibited" in lowered:
        return ""
    if "prohibit" not in lowered:
        return ""
    if "not p/a/s/m" in lowered:
        return text + " Turn the mode dial to P, A, S, or M. The page will not release the shutter."
    return text


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

    def set_clock(self):
        """Set the body clock from the Pi. gphoto2 accepts the value 'now'."""
        known = {item["key"]: item for item in self.configs()}
        for key in ("datetime", "datetimeutc"):
            item = known.get(key)
            if item and not item.get("readonly"):
                self.set_config(item["path"], "now")
                return {"set": item["path"], "value": "now", "label": item.get("label", key)}
        raise CameraError("This body did not offer a writable date and time control.")

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
        geo.stamp_many(saved)
        return {"mode": mode, "output": text.strip(), "files": saved}

    def trigger(self):
        with self._lock:
            text = self.run(["--trigger-capture"], timeout=20)
        return {"output": text.strip()}

    def preview(self, path):
        """One live-view frame.

        Do not set viewfinder=1. On this Nikon that control releases the shutter.
        """
        with self._lock:
            try:
                text = self.run(["--get-config", "/main/status/liveviewprohibit"], timeout=15)
            except CameraError:
                text = ""
            current = ""
            for line in text.splitlines():
                if line.strip().startswith("Current:"):
                    current = line.split(":", 1)[1].strip()
            reason = live_view_block_reason(current)
            if reason:
                raise CameraError(reason)
            for stale in (path, preview_download_path(path)):
                try:
                    os.remove(stale)
                except OSError:
                    pass
            self.run(["--capture-preview", "--filename", path, "--force-overwrite"], timeout=25)
            if not adopt_preview(path):
                raise CameraError("The camera did not return a live view frame.")
            with open(path, "rb") as handle:
                frame = handle.read()
        if frame[:2] != b"\xff\xd8":
            raise CameraError("The camera did not return a live view frame.")
        return frame

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
        geo.stamp(dest)
        return {"name": os.path.basename(dest), "path": dest, "bytes": os.path.getsize(dest)}

    def set_movie(self, recording):
        """Start or stop video. movie=1 is the body's record control, not the still shutter."""
        value = "1" if recording else "0"
        with self._lock:
            self.run(["--set-config", f"movie={value}"], timeout=30)
        return {"recording": bool(recording)}

    def thumbnail(self, folder, index, dest, name=""):
        """Small JPEG from the camera card. This does not copy the full picture.

        gphoto2 saves that JPEG as thumb_<name>, and a missing thumbnail still
        exits 0. Read the bytes from stdout, then from the thumb_ file.
        """
        target = name if name and "/" not in name and ".." not in name else str(index)
        with self._lock:
            try:
                done = subprocess.run(
                    ["gphoto2", "--folder", folder, "--get-thumbnail", target, "--stdout"],
                    capture_output=True,
                    timeout=30,
                )
            except FileNotFoundError as exc:
                raise CameraError("gphoto2 is not installed yet. Plug in ethernet and let the first boot finish.") from exc
            except subprocess.TimeoutExpired as exc:
                raise CameraError("The camera did not answer in time. Wake it and set USB to MTP/PTP.") from exc
            frame = jpeg_payload(done.stdout)
            if frame:
                return frame
            detail = (done.stderr or b"").decode("utf-8", "replace").strip()
            if done.returncode != 0:
                raise CameraError(detail or f"gphoto2 failed ({done.returncode})")
            for stale in (dest, preview_download_path(dest)):
                try:
                    os.remove(stale)
                except OSError:
                    pass
            self.run(
                ["--folder", folder, "--get-thumbnail", target, "--filename", dest, "--force-overwrite"],
                timeout=30,
            )
            if not adopt_preview(dest):
                raise CameraError(detail or "The camera sent no thumbnail for this file.")
            with open(dest, "rb") as handle:
                frame = handle.read()
        if not jpeg_payload(frame):
            raise CameraError(detail or "The camera sent no thumbnail for this file.")
        return frame

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
            geo.stamp(dest)
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
