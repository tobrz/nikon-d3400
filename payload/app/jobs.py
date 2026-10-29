"""Timelapse, bracketing, and lightning runs. One camera, so the runs share its lock."""

import os
import shutil
import subprocess
import threading
import time
from datetime import datetime

from camera import (
    EXPOSURE_COMPENSATION_PATH,
    SHUTTER_PATH,
    CameraError,
    deletion_order,
    format_shutter,
    optional_seconds,
    shutter_seconds,
)
import aurora
import geo


class Jobs:
    def __init__(self, camera):
        self.camera = camera
        self._lock = threading.Lock()
        self.timelapse = {
            "running": False, "taken": 0, "error": "", "interval": 0, "count": 0,
            "note": "", "movie": "",
        }
        self.bracket = {"running": False, "taken": 0, "error": "", "note": "", "count": 0}
        self.lightning = {"running": False, "triggers": 0, "downloaded": 0, "error": ""}
        self.offload = {"running": False, "total": 0, "copied": 0, "deleted": 0, "kept": 0, "error": "", "note": ""}
        self._stop_timelapse = threading.Event()
        self._stop_bracket = threading.Event()
        self._stop_lightning = threading.Event()
        self.aurora = {"running": False, "taken": 0, "checks": 0, "error": "", "note": "", "visible": 0, "threshold": 0,
                       "shooting": False, "direction": "", "bearing": None, "dark": False, "kp": None, "last_check": ""}
        self._stop_aurora = threading.Event()

    def _busy(self):
        return (
            self.timelapse["running"]
            or self.bracket["running"]
            or self.lightning["running"]
            or self.offload["running"]
            or self.aurora["running"]
        )

    def snapshot(self):
        with self._lock:
            return {
                "timelapse": dict(self.timelapse),
                "bracket": dict(self.bracket),
                "lightning": dict(self.lightning),
                "offload": dict(self.offload),
                "aurora": dict(self.aurora),
            }

    def start_timelapse(self, interval, count, seconds=None, fps=24):
        interval = max(1, int(round(float(interval))))
        count = int(count)
        fps = min(60, max(1, int(fps or 24)))
        exposure = optional_seconds(seconds)
        with self._lock:
            if self._busy():
                raise CameraError("A run is already going.")
            self.timelapse = {
                "running": True,
                "taken": 0,
                "error": "",
                "interval": interval,
                "count": count,
                "seconds": exposure,
                "fps": fps,
                "note": "Starting the timelapse.",
                "movie": "",
            }
        self._stop_timelapse.clear()
        geo.before_shot(self.camera)
        threading.Thread(
            target=self._timelapse_loop,
            args=(interval, count, exposure, fps),
            daemon=True,
        ).start()
        return self.snapshot()

    def stop_timelapse(self):
        self._stop_timelapse.set()
        with self._lock:
            if self.timelapse["running"]:
                self.timelapse["note"] = "Stopping after this shutter closes."
        return self.snapshot()

    def _timelapse_loop(self, interval, count, seconds, fps):
        taken = 0
        saved = []
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        movie = ""
        try:
            if seconds is None:
                current = self.camera.current_shutter()
                duration = shutter_seconds(current)
                hold = format_shutter(duration) if duration is not None else (current or "Bulb")
            else:
                hold = format_shutter(seconds)
            while not self._stop_timelapse.is_set():
                if count and taken >= count:
                    break
                coming = taken + 1
                label = f"Frame {coming}" + (f" of {count}" if count else "")
                with self._lock:
                    self.timelapse["note"] = label + ". Leaving the shutter open for " + hold + "."
                result = self.camera.capture(seconds=seconds, name=f"timelapse-{run_id}-{coming:04d}")
                saved.extend(result.get("files") or [])
                taken = coming
                used = result.get("shutter") or hold
                with self._lock:
                    self.timelapse["taken"] = taken
                    self.timelapse["note"] = (
                        label + " is saved. Shutter was " + str(used) + ". Waiting " + str(interval) + " seconds."
                    )
                if count and taken >= count:
                    break
                if self._stop_timelapse.wait(interval):
                    break
            if len(saved) >= 2:
                with self._lock:
                    self.timelapse["note"] = "Making the movie from " + str(taken) + " frames."
                movie = compile_movie(
                    saved,
                    os.path.join(self.camera.shots_dir, f"timelapse-{run_id}.mp4"),
                    fps,
                )
                with self._lock:
                    self.timelapse["movie"] = os.path.basename(movie)
                    self.timelapse["note"] = "Saved " + str(taken) + " frames and the movie."
            elif taken:
                with self._lock:
                    self.timelapse["note"] = "Saved " + str(taken) + " frame. A movie needs at least two."
        except (CameraError, ValueError, OSError) as exc:
            with self._lock:
                self.timelapse["error"] = str(exc)
                self.timelapse["note"] = str(exc)
        finally:
            with self._lock:
                self.timelapse["running"] = False
                self.timelapse["taken"] = taken
                if movie:
                    self.timelapse["movie"] = os.path.basename(movie)

    def start_aurora(self, threshold=30, interval=20, seconds=8, iso="1600", aperture="", check_minutes=5, hours=12):
        """Watch the forecast all night; when the aurora is likely in view and it is dark, shoot until it fades or dawn."""
        threshold = max(1, min(100, int(threshold)))
        interval = max(1, int(round(float(interval))))
        exposure = optional_seconds(seconds)
        state = geo.load()
        if state.get("lat") is None or state.get("lon") is None:
            raise CameraError("Save a location first (Place, or Use this device's location).")
        with self._lock:
            if self._busy():
                raise CameraError("A run is already going.")
            self.aurora = {
                "running": True, "taken": 0, "checks": 0, "error": "", "threshold": threshold, "interval": interval,
                "seconds": exposure, "shooting": False, "visible": 0, "direction": "", "bearing": None, "dark": False,
                "kp": None, "last_check": "", "note": "Checking NOAA's forecast.",
            }
        self._stop_aurora.clear()
        threading.Thread(
            target=self._aurora_loop,
            args=(float(state["lat"]), float(state["lon"]), threshold, interval, exposure, str(iso or ""),
                  str(aperture or ""), max(1, int(check_minutes)), float(hours)),
            daemon=True,
        ).start()
        return self.snapshot()

    def stop_aurora(self):
        self._stop_aurora.set()
        with self._lock:
            if self.aurora["running"]:
                self.aurora["note"] = "Stopping after this shutter closes."
        return self.snapshot()

    def _aurora_loop(self, lat, lon, threshold, interval, seconds, iso, aperture, check_minutes, hours):
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        end = time.time() + hours * 3600
        taken = 0
        was_dark = False
        settings_applied = False
        try:
            while not self._stop_aurora.is_set() and time.time() < end:
                try:
                    out = aurora.outlook(lat, lon)
                except aurora.AuroraError as exc:
                    with self._lock:
                        self.aurora["note"] = str(exc) + " Trying again in " + str(check_minutes) + " minutes."
                    if self._stop_aurora.wait(check_minutes * 60):
                        break
                    continue
                go = out["dark"] and out["visible"] >= threshold
                was_dark = was_dark or out["dark"]
                with self._lock:
                    self.aurora.update({
                        "checks": self.aurora["checks"] + 1, "visible": out["visible"], "direction": out["direction"],
                        "bearing": out["bearing"], "dark": out["dark"], "kp": out["kp"],
                        "last_check": datetime.now().strftime("%H:%M"), "shooting": go,
                    })
                if was_dark and not out["dark"] and out["sun_altitude"] > -6:
                    with self._lock:
                        self.aurora["note"] = "Dawn. Stopped after " + str(taken) + " frames."
                    break
                if not go:
                    with self._lock:
                        why = "not dark yet" if not out["dark"] else f"{out['visible']}% is under {threshold}%"
                        self.aurora["note"] = f"Watching: {why}. Next check in {check_minutes} min. {taken} frames so far."
                    if self._stop_aurora.wait(check_minutes * 60):
                        break
                    continue
                if not settings_applied:
                    wanted = {}
                    if iso:
                        wanted["iso"] = iso
                    if aperture:
                        wanted["f-number"] = aperture
                    if wanted:
                        try:
                            self.camera.apply_settings(wanted)
                        except CameraError:
                            pass
                    settings_applied = True
                # Shoot until the next forecast check is due.
                check_at = time.time() + check_minutes * 60
                while time.time() < check_at and not self._stop_aurora.is_set():
                    with self._lock:
                        self.aurora["note"] = (f"Aurora likely ({out['visible']}%, aim {out['direction']}). "
                                               f"Frame {taken + 1}.")
                    result = self.camera.capture(seconds=seconds, name=f"aurora-{run_id}-{taken + 1:04d}")
                    taken += 1
                    geo.stamp_many(result.get("files") or [])
                    with self._lock:
                        self.aurora["taken"] = taken
                    if self._stop_aurora.wait(interval):
                        break
            else:
                with self._lock:
                    if not self._stop_aurora.is_set():
                        self.aurora["note"] = "Watch time is over. " + str(taken) + " frames."
        except (CameraError, ValueError, OSError) as exc:
            with self._lock:
                self.aurora["error"] = str(exc)
                self.aurora["note"] = str(exc)
        finally:
            with self._lock:
                self.aurora["running"] = False
                self.aurora["shooting"] = False
                self.aurora["taken"] = taken
                if self._stop_aurora.is_set():
                    self.aurora["note"] = "Stopped. " + str(taken) + " frames."

    def start_bracket(self, count, step):
        count = int(count)
        with self._lock:
            if self._busy():
                raise CameraError("A run is already going.")
            self.bracket = {
                "running": True,
                "taken": 0,
                "error": "",
                "note": "Reading the exposure on the camera.",
                "count": count,
                "step": str(step),
            }
        self._stop_bracket.clear()
        geo.before_shot(self.camera)
        threading.Thread(target=self._bracket_loop, args=(count, step), daemon=True).start()
        return self.snapshot()

    def stop_bracket(self):
        self._stop_bracket.set()
        with self._lock:
            if self.bracket["running"]:
                self.bracket["note"] = "Stopping after this shutter closes."
        return self.snapshot()

    def _bracket_loop(self, count, step):
        taken = 0
        restore_path = None
        restore_value = None
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        try:
            plan = self.camera.plan_bracket(count, step)
            restore_value = plan.get("restore")
            if plan["control"] == "exposurecompensation":
                restore_path = EXPOSURE_COMPENSATION_PATH
            else:
                restore_path = SHUTTER_PATH
            total = len(plan["frames"])
            for index, frame in enumerate(plan["frames"], start=1):
                if self._stop_bracket.is_set():
                    break
                detail = frame.get("value") or format_shutter(frame.get("seconds"))
                with self._lock:
                    self.bracket["note"] = f"Frame {index} of {total}, {detail}."
                if frame["control"] == "bulb":
                    self.camera.capture(seconds=frame["seconds"], name=f"bracket-{run_id}-{index:02d}")
                else:
                    path = SHUTTER_PATH if frame["control"] == "shutterspeed" else EXPOSURE_COMPENSATION_PATH
                    self.camera.set_config(path, frame["value"])
                    self.camera.capture(name=f"bracket-{run_id}-{index:02d}")
                taken = index
                with self._lock:
                    self.bracket["taken"] = taken
                    self.bracket["note"] = f"Saved frame {index} of {total}."
            with self._lock:
                if not self.bracket.get("error"):
                    self.bracket["note"] = f"Bracket finished. {taken} frames are on the Pi. The camera is back where it was."
        except (CameraError, ValueError, OSError) as exc:
            with self._lock:
                self.bracket["error"] = str(exc)
                self.bracket["note"] = str(exc)
        finally:
            if restore_path and restore_value is not None:
                try:
                    self.camera.set_config(restore_path, restore_value)
                except CameraError as exc:
                    with self._lock:
                        extra = " The original setting was not restored. " + str(exc)
                        self.bracket["error"] = (self.bracket.get("error") or "") + extra
                        self.bracket["note"] = (self.bracket.get("note") or "") + extra
            with self._lock:
                self.bracket["running"] = False
                self.bracket["taken"] = taken

    def start_lightning(self, frames, gap):
        frames = max(1, int(frames))
        gap = max(0.2, float(gap))
        with self._lock:
            if self._busy():
                raise CameraError("A run is already going.")
            self.lightning = {"running": True, "triggers": 0, "downloaded": 0, "error": "", "frames": frames, "gap": gap}
        self._stop_lightning.clear()
        geo.before_shot(self.camera)
        threading.Thread(target=self._lightning_loop, args=(frames, gap), daemon=True).start()
        return self.snapshot()

    def stop_lightning(self):
        self._stop_lightning.set()
        return self.snapshot()

    def _lightning_loop(self, frames, gap):
        triggers = 0
        downloaded = 0
        try:
            before = {f"{item['folder']}/{item['name']}" for item in self.camera.list_files()}
        except CameraError as exc:
            with self._lock:
                self.lightning["error"] = str(exc)
                self.lightning["running"] = False
            return
        try:
            while triggers < frames and not self._stop_lightning.is_set():
                self.camera.trigger()
                triggers += 1
                with self._lock:
                    self.lightning["triggers"] = triggers
                if self._stop_lightning.wait(gap):
                    break
            saved = self.camera.download_new(before)
            downloaded = len(saved)
        except CameraError as exc:
            with self._lock:
                self.lightning["error"] = str(exc)
        finally:
            with self._lock:
                self.lightning["running"] = False
                self.lightning["triggers"] = triggers
                self.lightning["downloaded"] = downloaded

    def start_offload(self):
        with self._lock:
            if self._busy():
                raise CameraError("A run is already going.")
            self.offload = {
                "running": True,
                "total": 0,
                "copied": 0,
                "deleted": 0,
                "kept": 0,
                "error": "",
                "note": "Reading the camera card.",
            }
        geo.before_shot(self.camera)
        threading.Thread(target=self._offload_loop, daemon=True).start()
        return self.snapshot()

    def _offload_loop(self):
        copied = []
        try:
            files = self.camera.list_files()
            with self._lock:
                self.offload["total"] = len(files)
                self.offload["note"] = f"Copying {len(files)} files onto the Pi."
            for item in files:
                try:
                    saved = self.camera.pull(item["folder"], item["index"], item["name"])
                    copied.append({**item, "saved": saved["name"]})
                    with self._lock:
                        self.offload["copied"] = len(copied)
                        self.offload["note"] = f"Copied {saved['name']} onto the Pi."
                except (CameraError, OSError) as exc:
                    with self._lock:
                        self.offload["kept"] += 1
                        self.offload["error"] = f"{item['name']} stayed on the camera. {exc}"
            deleted = 0
            for item in deletion_order(copied):
                try:
                    self.camera.delete_file(item["folder"], item["index"])
                    deleted += 1
                    with self._lock:
                        self.offload["deleted"] = deleted
                        self.offload["note"] = f"Removed {item['name']} from the camera."
                except CameraError as exc:
                    with self._lock:
                        self.offload["kept"] += 1
                        self.offload["error"] = f"{item['name']} is on the Pi and still on the camera. {exc}"
            with self._lock:
                self.offload["note"] = (
                    f"Copied {len(copied)} onto the Pi and removed {deleted} from the camera."
                )
        except CameraError as exc:
            with self._lock:
                self.offload["error"] = str(exc)
        finally:
            with self._lock:
                self.offload["running"] = False


def concat_script(paths, fps):
    """ffmpeg concat list. Each still is shown for one frame at the playback rate."""
    duration = 1.0 / max(1, int(fps))
    lines = []
    for path in paths:
        quoted = path.replace("'", "'\\''")
        lines.append("file '" + quoted + "'")
        lines.append(f"duration {duration:.6f}")
    if paths:
        lines.append("file '" + paths[-1].replace("'", "'\\''") + "'")
    return "\n".join(lines) + "\n"


def jpeg_frames(paths):
    return [path for path in paths if path.lower().endswith((".jpg", ".jpeg")) and os.path.isfile(path)]


def ensure_ffmpeg():
    if shutil.which("ffmpeg"):
        return
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        raise CameraError("ffmpeg is not installed. The frames are on the Pi. The movie was not made.")
    subprocess.run(["apt-get", "update"], timeout=180, check=False)
    done = subprocess.run(["apt-get", "install", "-y", "ffmpeg"], timeout=300, check=False)
    if done.returncode != 0 or not shutil.which("ffmpeg"):
        raise CameraError("The frames are saved. Installing ffmpeg failed, so the movie was not made.")


def compile_movie(paths, dest, fps):
    frames = jpeg_frames(paths)
    if not frames:
        frames = _previews_from_raw(paths)
    if not frames:
        raise CameraError("No JPEG frames were saved, so there is nothing to compile.")
    ensure_ffmpeg()
    script = dest + ".txt"
    with open(script, "w") as handle:
        handle.write(concat_script(frames, fps))
    done = subprocess.run(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", script,
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
            "-r", str(int(fps)),
            "-c:v", "libx264",
            "-movflags", "+faststart",
            dest,
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    try:
        os.remove(script)
    except OSError:
        pass
    if done.returncode != 0 or not os.path.isfile(dest):
        detail = (done.stderr or "").strip().splitlines()
        tail = detail[-1] if detail else "ffmpeg failed"
        raise CameraError("The frames are saved. The movie was not made. " + tail)
    return dest


def _previews_from_raw(paths):
    if not shutil.which("exiftool"):
        return []
    extracted = []
    for path in paths:
        if not path.lower().endswith(".nef") or not os.path.isfile(path):
            continue
        dest = os.path.splitext(path)[0] + "-preview.jpg"
        try:
            proc = subprocess.run(["exiftool", "-b", "-PreviewImage", path], capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0 and proc.stdout[:2] == b"\xff\xd8":
            with open(dest, "wb") as handle:
                handle.write(proc.stdout)
            extracted.append(dest)
    return extracted
