"""Timelapse and lightning runs. One camera, so the runs share its lock."""

import threading
import time

from camera import CameraError


class Jobs:
    def __init__(self, camera):
        self.camera = camera
        self._lock = threading.Lock()
        self.timelapse = {"running": False, "taken": 0, "error": "", "interval": 0, "count": 0}
        self.lightning = {"running": False, "triggers": 0, "downloaded": 0, "error": ""}
        self._stop_timelapse = threading.Event()
        self._stop_lightning = threading.Event()

    def snapshot(self):
        with self._lock:
            return {"timelapse": dict(self.timelapse), "lightning": dict(self.lightning)}

    def start_timelapse(self, interval, count):
        interval = max(3, int(interval))
        count = int(count)
        with self._lock:
            if self.timelapse["running"] or self.lightning["running"]:
                raise CameraError("A run is already going.")
            self.timelapse = {"running": True, "taken": 0, "error": "", "interval": interval, "count": count}
        self._stop_timelapse.clear()
        threading.Thread(target=self._timelapse_loop, args=(interval, count), daemon=True).start()
        return self.snapshot()

    def stop_timelapse(self):
        self._stop_timelapse.set()
        return self.snapshot()

    def _timelapse_loop(self, interval, count):
        taken = 0
        try:
            while not self._stop_timelapse.is_set():
                if count and taken >= count:
                    break
                started = time.monotonic()
                self.camera.capture()
                taken += 1
                with self._lock:
                    self.timelapse["taken"] = taken
                wait = interval - (time.monotonic() - started)
                if wait > 0 and self._stop_timelapse.wait(wait):
                    break
        except CameraError as exc:
            with self._lock:
                self.timelapse["error"] = str(exc)
        finally:
            with self._lock:
                self.timelapse["running"] = False
                self.timelapse["taken"] = taken

    def start_lightning(self, frames, gap):
        frames = max(1, int(frames))
        gap = max(0.2, float(gap))
        with self._lock:
            if self.timelapse["running"] or self.lightning["running"]:
                raise CameraError("A run is already going.")
            self.lightning = {"running": True, "triggers": 0, "downloaded": 0, "error": "", "frames": frames, "gap": gap}
        self._stop_lightning.clear()
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
