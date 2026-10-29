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
import exposure
import geo
import imaging
import notify
import sky

DETECTED = 2.0          # percent of the sky glowing green that counts as "the aurora is showing"
KEEP_GOING_MINUTES = 15  # keep shooting this long after the last frame that showed aurora, whatever the forecast says


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
        self.tether = {"running": False, "saved": 0, "error": "", "note": "", "last": ""}
        self._stop_tether = threading.Event()

    def _busy(self):
        return (
            self.timelapse["running"]
            or self.bracket["running"]
            or self.lightning["running"]
            or self.offload["running"]
            or self.aurora["running"]
            or self.tether["running"]
        )

    def snapshot(self):
        with self._lock:
            return {
                "timelapse": dict(self.timelapse),
                "bracket": dict(self.bracket),
                "lightning": dict(self.lightning),
                "offload": dict(self.offload),
                "aurora": dict(self.aurora),
                "tether": dict(self.tether),
                "usb_resets": self.camera.resets,
                "last_usb_reset": self.camera.last_reset,
            }

    def start_timelapse(self, interval, count, seconds=None, fps=24, auto=False):
        interval = max(1, int(round(float(interval))))
        count = int(count)
        fps = min(60, max(1, int(fps or 24)))
        exposure_s = optional_seconds(seconds)
        auto = bool(auto)
        with self._lock:
            if self._busy():
                raise CameraError("A run is already going.")
            self.timelapse = {
                "running": True,
                "taken": 0,
                "error": "",
                "interval": interval,
                "count": count,
                "seconds": exposure_s,
                "fps": fps,
                "auto": auto,
                "note": "Starting the timelapse.",
                "movie": "",
            }
        self._stop_timelapse.clear()
        geo.before_shot(self.camera)
        threading.Thread(
            target=self._timelapse_loop,
            args=(interval, count, exposure_s, fps, auto),
            daemon=True,
        ).start()
        return self.snapshot()

    def stop_timelapse(self):
        self._stop_timelapse.set()
        with self._lock:
            if self.timelapse["running"]:
                self.timelapse["note"] = "Stopping after this shutter closes."
        return self.snapshot()

    def _timelapse_loop(self, interval, count, seconds, fps, auto=False):
        taken = 0
        saved = []
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        movie = ""
        ramp = None
        iso_set = None
        try:
            if auto:
                # Day to night: the shutter can stretch to just under the interval (30 s at most), then ISO climbs.
                rungs = exposure.ladder(max(1, min(30, interval - 2)), base_iso=100, max_iso=6400)
                current = shutter_seconds(self.camera.current_shutter()) or seconds or 1 / 250
                ramp = exposure.Ramp(rungs, exposure.nearest_rung(rungs, current, 100), exposure.DAY)
                hold = "an exposure that follows the light"
            elif seconds is None:
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
                if ramp:
                    shot_seconds, iso = ramp.current
                    if iso != iso_set:
                        self.camera.set_iso(iso)
                        iso_set = iso
                else:
                    shot_seconds = seconds
                result = self.camera.capture(seconds=shot_seconds, name=f"timelapse-{run_id}-{coming:04d}")
                saved.extend(result.get("files") or [])
                taken = coming
                used = result.get("shutter") or hold
                if ramp:
                    mean = self._measure(result.get("files") or [], keep=False)
                    if mean is not None:
                        # Let night look like night: once the shutter is long, aim for the darker band.
                        ramp.low, ramp.high = exposure.NIGHT if ramp.current[0] >= 1 else exposure.DAY
                        ramp.step(mean["mean"])
                        used = f"{used}, ISO {iso_set}, brightness {round(mean['mean'])}"
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

    def start_aurora(self, threshold=30, interval=20, seconds=8, iso="1600", aperture="", check_minutes=5, hours=12,
                     max_cloud=80, auto_exposure=True, detect=True):
        """Watch all night. Shoots when it is dark, clear enough, and either NOAA says the aurora is likely or the
        test frames show it; follows the light with the exposure; sends alerts; makes a movie at the end."""
        threshold = max(1, min(100, int(threshold)))
        interval = max(1, int(round(float(interval))))
        exposure_s = optional_seconds(seconds) or 8
        max_cloud = max(0, min(100, int(max_cloud if max_cloud not in (None, "") else 80)))
        state = geo.load()
        if state.get("lat") is None or state.get("lon") is None:
            raise CameraError("Save a location first (Place, or Use this device's location).")
        with self._lock:
            if self._busy():
                raise CameraError("A run is already going.")
            self.aurora = {
                "running": True, "taken": 0, "checks": 0, "error": "", "threshold": threshold, "interval": interval,
                "seconds": exposure_s, "shooting": False, "visible": 0, "direction": "", "bearing": None, "dark": False,
                "kp": None, "last_check": "", "note": "Checking NOAA's forecast.", "cloud": None, "max_cloud": max_cloud,
                "auto_exposure": bool(auto_exposure), "detect": bool(detect), "detected": 0, "last_seen": "",
                "score": None, "exposure": "", "best": [], "movie": "", "tests": 0,
            }
        self._stop_aurora.clear()
        threading.Thread(
            target=self._aurora_loop,
            args=(float(state["lat"]), float(state["lon"]), threshold, interval, exposure_s, str(iso or "1600"),
                  str(aperture or ""), max(1, int(check_minutes)), float(hours), max_cloud, bool(auto_exposure),
                  bool(detect)),
            daemon=True,
        ).start()
        return self.snapshot()

    def stop_aurora(self):
        self._stop_aurora.set()
        with self._lock:
            if self.aurora["running"]:
                self.aurora["note"] = "Stopping after this shutter closes."
        return self.snapshot()

    def _measure(self, files, keep=True):
        """Brightness and aurora score of the JPEG among files (or the NEF's embedded preview). Saved for the app."""
        jpg = next((f for f in files if f.lower().endswith((".jpg", ".jpeg"))), None)
        temp = None
        if not jpg:
            previews = _previews_from_raw([f for f in files if f.lower().endswith(".nef")])
            jpg = temp = previews[0] if previews else None
        if not jpg:
            return None
        try:
            score = imaging.measure(jpg)
        except imaging.ImagingError:
            return None
        finally:
            if temp:
                try:
                    os.remove(temp)
                except OSError:
                    pass
        if keep:
            for f in files:
                imaging.save_score(self.camera.shots_dir, os.path.basename(f), score)
        return score

    def _aurora_loop(self, lat, lon, threshold, interval, seconds, iso, aperture, check_minutes, hours, max_cloud,
                     auto_exposure, detect):
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        end = time.time() + hours * 3600
        taken = 0
        tests = 0
        detected = 0
        last_seen = 0.0
        was_dark = False
        aperture_set = False
        told_forecast = False
        told_seen = 0.0
        frames = []           # (files, aurora score) of kept frames that were measured
        kept = []             # every file kept, for the movie
        iso_set = None
        try:
            base = float(iso)
        except ValueError:
            base = 1600.0
        rungs = exposure.ladder(seconds, base_iso=400, max_iso=6400, shortest=1 / 4)
        ramp = exposure.Ramp(rungs, exposure.nearest_rung(rungs, seconds, base), exposure.NIGHT)
        if not auto_exposure:
            ramp = exposure.Ramp([(seconds, int(base))], 0, exposure.NIGHT)

        def shoot(name):
            nonlocal iso_set
            shot_seconds, shot_iso = ramp.current
            if shot_iso != iso_set:
                try:
                    used_iso = self.camera.set_iso(shot_iso)
                except CameraError:
                    used_iso = None
                iso_set = shot_iso
                with self._lock:
                    self.aurora["iso"] = used_iso
            result = self.camera.capture(seconds=shot_seconds, name=name)
            files = result.get("files") or []
            geo.stamp_many(files)
            score = self._measure(files, keep=True) if (detect or auto_exposure) else None
            if score and auto_exposure:
                ramp.step(score["mean"])
            with self._lock:
                self.aurora["exposure"] = f"{format_shutter(shot_seconds)} at ISO {shot_iso}"
                if score:
                    self.aurora["score"] = score["aurora"]
            return files, score

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
                try:
                    c = sky.cloud_now(lat, lon)
                    cloud = c["total"] if c else None
                except sky.SkyError:
                    cloud = None
                cloudy = cloud is not None and max_cloud < 100 and cloud > max_cloud
                seen_lately = detect and last_seen and time.time() - last_seen < KEEP_GOING_MINUTES * 60
                forecast_go = out["dark"] and out["visible"] >= threshold and not cloudy
                go = out["dark"] and (forecast_go or seen_lately)
                was_dark = was_dark or out["dark"]
                with self._lock:
                    self.aurora.update({
                        "checks": self.aurora["checks"] + 1, "visible": out["visible"], "direction": out["direction"],
                        "bearing": out["bearing"], "dark": out["dark"], "kp": out["kp"], "cloud": cloud,
                        "last_check": datetime.now().strftime("%H:%M"), "shooting": go,
                    })
                if was_dark and not out["dark"] and out["sun_altitude"] > -6:
                    with self._lock:
                        self.aurora["note"] = "Dawn. Stopped after " + str(taken) + " frames."
                    break
                if out["dark"] and not aperture_set and aperture:
                    try:
                        self.camera.apply_settings({"f-number": aperture})
                    except CameraError:
                        pass
                    aperture_set = True
                if go and forecast_go and not told_forecast:
                    told_forecast = True
                    notify.send("Aurora likely", f"{out['visible']}% chance in view, aim {out['direction']}. "
                                f"Shooting started" + (f", {cloud}% cloud." if cloud is not None else "."), tags="sparkles")
                if not go and out["dark"] and detect:
                    # The forecast says no, but it is dark: one test frame each check, in case the forecast is wrong.
                    with self._lock:
                        self.aurora["note"] = "Test frame: is anything showing?"
                    tests += 1
                    files, score = shoot(f"aurora-{run_id}-test-{tests:04d}")
                    with self._lock:
                        self.aurora["tests"] = tests
                    if score and score["aurora"] >= DETECTED:
                        last_seen = time.time()
                        go = True
                        frames.append((files, score["aurora"]))
                        kept.extend(files)
                        taken += 1
                    else:
                        for f in files:
                            try:
                                os.remove(f)
                            except OSError:
                                pass
                        imaging.forget_scores(self.camera.shots_dir, [os.path.basename(f) for f in files])
                if not go:
                    with self._lock:
                        if not out["dark"]:
                            why = "not dark yet"
                        elif cloudy:
                            why = f"{cloud}% cloud (limit {max_cloud}%)"
                        else:
                            why = f"{out['visible']}% is under {threshold}%"
                        seen = " Test frame showed nothing." if detect and out["dark"] else ""
                        self.aurora["note"] = f"Watching: {why}.{seen} Next check in {check_minutes} min. {taken} frames so far."
                    if self._stop_aurora.wait(check_minutes * 60):
                        break
                    continue
                # Shoot until the next forecast check is due.
                check_at = time.time() + check_minutes * 60
                while time.time() < check_at and not self._stop_aurora.is_set():
                    with self._lock:
                        why = f"Aurora likely ({out['visible']}%, aim {out['direction']})" if forecast_go else "Aurora showing in the frames"
                        self.aurora["note"] = f"{why}. Frame {taken + 1}."
                    files, score = shoot(f"aurora-{run_id}-{taken + 1:04d}")
                    taken += 1
                    kept.extend(files)
                    if score:
                        frames.append((files, score["aurora"]))
                        if score["aurora"] >= DETECTED:
                            detected += 1
                            last_seen = time.time()
                            if time.time() - told_seen > 3600:
                                told_seen = time.time()
                                jpg = next((f for f in files if f.lower().endswith((".jpg", ".jpeg"))), None)
                                notify.send("Aurora showing", f"Green in the frames ({score['aurora']}% of the sky). "
                                            f"{taken} frames so far.", tags="sparkles,camera", priority=4, picture=jpg)
                    with self._lock:
                        self.aurora["taken"] = taken
                        self.aurora["detected"] = detected
                        if last_seen:
                            self.aurora["last_seen"] = datetime.fromtimestamp(last_seen).strftime("%H:%M")
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
            notify.send("Aurora watch stopped", str(exc)[:300], tags="warning", priority=4)
        finally:
            best = [os.path.basename(f) for files, score in sorted(frames, key=lambda fs: -fs[1])[:5] if score > 0
                    for f in files if f.lower().endswith((".jpg", ".jpeg"))]
            movie = ""
            if taken >= 10:
                with self._lock:
                    self.aurora["note"] = (self.aurora.get("note") or "") + " Making the movie."
                try:
                    movie = os.path.basename(compile_movie(
                        kept, os.path.join(self.camera.shots_dir, f"aurora-{run_id}.mp4"), 24))
                except (CameraError, OSError):
                    movie = ""
            with self._lock:
                self.aurora["running"] = False
                self.aurora["shooting"] = False
                self.aurora["taken"] = taken
                self.aurora["best"] = best
                self.aurora["movie"] = movie
                if self._stop_aurora.is_set():
                    self.aurora["note"] = "Stopped. " + str(taken) + " frames."
                elif movie:
                    self.aurora["note"] = (self.aurora.get("note") or "").replace(" Making the movie.", "") + " Movie saved."
            if taken:
                notify.send("Aurora watch finished",
                            f"{taken} frames, {detected} showed aurora." + (" Movie saved." if movie else ""),
                            tags="camera")

    # ---- tethered: pictures taken with the camera's own shutter button copy onto the Pi as they happen

    def start_tether(self):
        with self._lock:
            if self._busy():
                raise CameraError("A run is already going.")
            self.tether = {"running": True, "saved": 0, "error": "", "note": "Reading the card.", "last": ""}
        self._stop_tether.clear()
        threading.Thread(target=self._tether_loop, daemon=True).start()
        return self.snapshot()

    def stop_tether(self):
        self._stop_tether.set()
        with self._lock:
            if self.tether["running"]:
                self.tether["note"] = "Stopping."
        return self.snapshot()

    def _tether_loop(self):
        saved = 0
        known = set()
        rounds = 0
        try:
            try:
                known = {item["name"] for item in self.camera.list_files()}
            except CameraError as exc:
                with self._lock:
                    self.tether["note"] = "Couldn't read the card yet (" + str(exc).splitlines()[-1][:80] + "). Listening anyway."
            while not self._stop_tether.is_set():
                with self._lock:
                    self.tether["note"] = "Listening. Press the camera's shutter button; pictures copy here and stay on the card."
                try:
                    new = self.camera.wait_and_download(15)
                except CameraError as exc:
                    with self._lock:
                        self.tether["error"] = str(exc).splitlines()[-1][:200]
                    if self._stop_tether.wait(10):
                        break
                    continue
                for path in new:
                    # tether-YYYYmmdd-HHMMSS-<card name>.<ext>: remember the card name so the sweep skips it.
                    base = os.path.basename(path)
                    known.add(base.split("-", 3)[-1] if base.count("-") >= 3 else base)
                    saved += 1
                    with self._lock:
                        self.tether["saved"] = saved
                        self.tether["last"] = base
                        self.tether["error"] = ""
                rounds += 1
                if rounds % 8 == 0:
                    # A sweep every ~2 minutes catches pictures taken between listening sessions.
                    try:
                        for item in self.camera.list_files():
                            if item["name"] in known:
                                continue
                            got = self.camera.pull(item["folder"], item["index"], item["name"])
                            known.add(item["name"])
                            saved += 1
                            with self._lock:
                                self.tether["saved"] = saved
                                self.tether["last"] = got["name"]
                    except (CameraError, OSError):
                        pass
        finally:
            with self._lock:
                self.tether["running"] = False
                self.tether["saved"] = saved
                self.tether["note"] = f"Stopped. {saved} pictures copied this session."

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
            # deflicker evens out frame-to-frame brightness jumps (exposure steps, auto ISO), like rpi-timelapse's
            # auto-gamma pass but inside the same ffmpeg run.
            "-vf", "deflicker=mode=pm:size=10,scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
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
