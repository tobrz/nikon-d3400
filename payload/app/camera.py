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


def index_spec(indexes):
    """Turn file numbers into one gphoto2 range, such as 1-3,5."""
    numbers = sorted({int(number) for number in indexes})
    if not numbers:
        return ""
    parts = []
    start = previous = numbers[0]
    for number in numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        parts.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = number
    parts.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(parts)


def saved_thumbnail_name(filename):
    """gphoto2 stores a card thumbnail as thumb_<camera file name>."""
    name = os.path.basename(filename or "")
    if name.startswith("thumb_"):
        return name[len("thumb_"):]
    return name


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


SHUTTER_PATH = "/main/capturesettings/shutterspeed"
EXPOSURE_COMPENSATION_PATH = "/main/capturesettings/exposurecompensation"
PROGRAM_PATH = "/main/capturesettings/expprogram"


def shutter_seconds(label):
    """Seconds for a shutter label such as 30.0000s or 1/100. Bulb and Time are None."""
    text = (label or "").strip().lower().replace(" ", "")
    if not text or text in ("bulb", "time", "auto", "automatic"):
        return None
    if text.endswith("s") and not text.startswith("1/"):
        text = text[:-1]
    if text.startswith("1/"):
        try:
            return 1.0 / float(text[2:])
        except ValueError:
            return None
    try:
        value = float(text)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


def format_shutter(seconds):
    """A short phrase for a shutter time, such as 2 seconds or 1/100."""
    if seconds is None:
        return "the camera's shutter"
    if seconds >= 0.95:
        whole = round(seconds)
        if abs(seconds - whole) < 0.05:
            unit = "second" if whole == 1 else "seconds"
            return f"{whole} {unit}"
        return f"{seconds:.1f} seconds"
    if seconds > 0:
        nearest = int(round(1 / seconds))
        if nearest > 0 and abs(seconds - (1 / nearest)) <= 0.0008:
            return f"1/{nearest}"
    return f"{seconds:g} seconds"


def nearest_shutter_label(seconds, choices):
    """Closest timed shutter choice. None when the request is longer than the body can time."""
    best_label = None
    best_gap = None
    longest = 0.0
    for label in choices:
        duration = shutter_seconds(label)
        if duration is None:
            continue
        longest = max(longest, duration)
        gap = abs(duration - float(seconds))
        if best_label is None or gap < best_gap:
            best_label = label
            best_gap = gap
    if best_label is None or float(seconds) > longest + 0.05:
        return None
    return best_label


def nearest_number_label(target, choices):
    parsed = []
    for label in choices:
        try:
            parsed.append((float(label), str(label)))
        except (TypeError, ValueError):
            continue
    if not parsed:
        raise ValueError("The camera did not offer those steps.")
    return min(parsed, key=lambda item: (abs(item[0] - target), item[1]))[1]


def parse_ev_step(step):
    if isinstance(step, str):
        text = step.strip()
        named = {"1/3": 1 / 3, "2/3": 2 / 3, "1": 1.0, "1.0": 1.0}
        if text in named:
            return named[text]
        step = float(text)
    step = float(step)
    for candidate in (1 / 3, 2 / 3, 1.0):
        if abs(step - candidate) < 0.05:
            return candidate
    raise ValueError("Step must be 1/3, 2/3, or 1 stop.")


def optional_seconds(value):
    """None leaves the camera's shutter alone. A number is how long to hold it open."""
    if value in (None, "", "auto"):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise CameraError("Shutter seconds need to be a number.") from exc
    if seconds <= 0 or seconds > 900:
        raise CameraError("Use a shutter from a fraction of a second up to 15 minutes.")
    return seconds


def bracket_plan(program, shutter_label, shutter_choices, ec_label, ec_choices, count, step):
    """Frames for one bracket, dark to bright.

    Manual and shutter-priority step the shutter. Aperture and program step
    exposure compensation. The dial itself is not moved.
    """
    count = int(count)
    if count not in (3, 5):
        raise ValueError("Take 3 or 5 frames.")
    step = parse_ev_step(step)
    mode = (program or "").strip().upper()
    offsets = [step * (index - (count // 2)) for index in range(count)]
    if mode in ("M", "S"):
        current = shutter_seconds(shutter_label)
        if current is None:
            raise ValueError(
                "The shutter is on "
                + (shutter_label or "Bulb")
                + ". Set a timed speed first. Bulb and Time need a number of seconds on Shoot."
            )
        frames = []
        for ev in offsets:
            target = current * (2 ** ev)
            label = nearest_shutter_label(target, shutter_choices)
            if label is None:
                frames.append({"control": "bulb", "seconds": round(target, 3), "ev": ev})
            else:
                frames.append({
                    "control": "shutterspeed",
                    "value": label,
                    "seconds": shutter_seconds(label),
                    "ev": ev,
                })
        return {"mode": mode, "control": "shutterspeed", "restore": shutter_label, "frames": frames}
    if mode in ("A", "P"):
        try:
            current = float(ec_label)
        except (TypeError, ValueError):
            current = 0.0
        frames = []
        for ev in offsets:
            frames.append({
                "control": "exposurecompensation",
                "value": nearest_number_label(current + ev, ec_choices),
                "ev": ev,
            })
        return {
            "mode": mode,
            "control": "exposurecompensation",
            "restore": str(ec_label),
            "frames": frames,
        }
    raise ValueError("Turn the mode dial to M, A, S, or P. The page cannot move the dial.")


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
        """Who is on USB. Skip the probe while a picture holds the camera.

        A second gphoto2 process during an exposure can take the USB device
        and leave the shutter open.
        """
        if not self._lock.acquire(blocking=False):
            return {"model": "Busy with the shutter", "port": ""}
        try:
            try:
                text = self.run(["--auto-detect"], timeout=12)
            except CameraError:
                return None
            for line in text.splitlines():
                if "usb:" in line.lower() and not line.lower().startswith("model"):
                    model = line.rsplit("usb:", 1)[0].strip()
                    return {"model": model, "port": "usb:" + line.rsplit("usb:", 1)[1].strip()}
            return None
        finally:
            self._lock.release()

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

    def capture(self, seconds=None, name=None):
        """Take one still and return only after the shutter has closed.

        seconds None uses the speed already on the camera. On this D3400, Bulb
        and Time open on one press and close on the next, so a number of
        seconds is required before that press. A single trigger-capture is not
        used as a fallback: that press opens the shutter and returns at once.
        """
        seconds = optional_seconds(seconds)
        if name:
            stem = os.path.basename(str(name))
            if not stem or stem in (".", "..") or stem != str(name):
                raise CameraError("Bad picture name.")
        else:
            stem = "shot-" + datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = os.path.join(self.shots_dir, stem + ".%C")
        os.makedirs(self.shots_dir, exist_ok=True)
        with self._lock:
            shutter = self._config_unlocked(SHUTTER_PATH)
            choices = [item["label"] for item in shutter.get("choices") or []]
            current = shutter.get("current") or ""
            if seconds is None:
                duration = shutter_seconds(current)
                if duration is None:
                    raise CameraError(
                        "The shutter is on "
                        + (current or "Bulb")
                        + ". Choose how many seconds to leave it open so the page can close it."
                    )
                text = self._timed_capture_unlocked(filename, None, duration)
                used = current
            else:
                label = nearest_shutter_label(seconds, choices)
                if label is None:
                    text = self._bulb_capture_unlocked(filename, seconds, restore=current)
                    used = format_shutter(seconds)
                else:
                    duration = shutter_seconds(label) or seconds
                    text = self._timed_capture_unlocked(filename, label, duration)
                    used = label
        saved = _collected_files(text, self.shots_dir, stem)
        geo.stamp_many(saved)
        return {"mode": "capture", "output": (text or "").strip(), "files": saved, "shutter": used}

    def current_shutter(self):
        with self._lock:
            shutter = self._config_unlocked(SHUTTER_PATH)
        return shutter.get("current") or ""

    def plan_bracket(self, count, step):
        with self._lock:
            program = self._config_unlocked(PROGRAM_PATH)
            shutter = self._config_unlocked(SHUTTER_PATH)
            compensation = self._config_unlocked(EXPOSURE_COMPENSATION_PATH)
        try:
            return bracket_plan(
                program.get("current"),
                shutter.get("current"),
                [item["label"] for item in shutter.get("choices") or []],
                compensation.get("current"),
                [item["label"] for item in compensation.get("choices") or []],
                count,
                step,
            )
        except ValueError as exc:
            raise CameraError(str(exc)) from exc

    def _config_unlocked(self, path):
        text = self.run(["--get-config", path], timeout=20)
        blocks = parse_configs(path + "\n" + text)
        if not blocks:
            raise CameraError("The camera did not return " + path + ".")
        return blocks[0]

    def _timed_capture_unlocked(self, filename, label, duration):
        args = []
        if label:
            args.extend(["--set-config", SHUTTER_PATH + "=" + label])
        args.extend(["--capture-image-and-download", "--filename", filename, "--force-overwrite"])
        return self.run(args, timeout=max(45, int(duration) + 45))

    def _bulb_capture_unlocked(self, filename, seconds, restore):
        """Open on one press, wait, close on the next press. One gphoto2 process."""
        whole = max(1, int(round(float(seconds))))
        args = [
            "--set-config", SHUTTER_PATH + "=Bulb",
            "--filename", filename,
            "--force-overwrite",
            "--trigger-capture",
            "--wait-event=" + str(whole) + "s",
            "--trigger-capture",
            "--wait-event-and-download=30s",
        ]
        try:
            text = self.run(args, timeout=whole + 90)
        except CameraError as exc:
            if "did not answer in time" in str(exc):
                try:
                    self.run(["--trigger-capture"], timeout=20)
                except CameraError:
                    pass
                raise CameraError("The shutter was told to close. " + str(exc)) from exc
            raise
        finally:
            if restore and shutter_seconds(restore) is not None:
                try:
                    self.run(["--set-config", SHUTTER_PATH + "=" + restore], timeout=20)
                except CameraError:
                    pass
        return text

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

    def thumbnail_range(self, folder, indexes, dest_dir):
        """Download many thumbnails in one gphoto2 session.

        A separate session per picture spends most of the time starting gphoto2.
        Returns camera file name to JPEG bytes.
        """
        spec = index_spec(indexes)
        if not spec:
            return {}
        os.makedirs(dest_dir, exist_ok=True)
        for name in os.listdir(dest_dir):
            path = os.path.join(dest_dir, name)
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        pattern = os.path.join(dest_dir, "%f.%C")
        error = ""
        with self._lock:
            try:
                self.run(
                    ["--folder", folder, "--get-thumbnail", spec, "--filename", pattern, "--force-overwrite"],
                    timeout=max(60, 4 * len(spec.split(",")) + 3 * len(indexes)),
                )
            except CameraError as exc:
                error = str(exc)
        found = {}
        for name in os.listdir(dest_dir):
            path = os.path.join(dest_dir, name)
            if not os.path.isfile(path):
                continue
            with open(path, "rb") as handle:
                frame = jpeg_payload(handle.read())
            try:
                os.remove(path)
            except OSError:
                pass
            label = saved_thumbnail_name(name)
            if frame and label:
                found[label] = frame
        if not found and error:
            raise CameraError(error)
        return found

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


def _collected_files(text, folder, stem):
    """Paths gphoto2 saved for one still, from its log and from the shots folder."""
    found = _saved_paths(text, folder)
    prefix = stem + "."
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if not name.startswith(prefix):
                continue
            path = os.path.join(folder, name)
            if path not in found and os.path.isfile(path) and os.path.getsize(path) > 0:
                found.append(path)
    if not found:
        raise CameraError("The shutter closed, but no picture file was saved on the Pi.")
    return found


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
