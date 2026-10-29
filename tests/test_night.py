import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "payload", "app"))

import camera
import exposure
import imaging
import notify
import sky


def flat_rgb(size, color):
    w, h = size
    return bytes(color) * (w * h)


class ImagingTests(unittest.TestCase):
    def test_green_sky_scores_and_orange_glow_does_not(self):
        w, h = imaging.SMALL
        green = imaging.aurora_score(flat_rgb((w, h), (20, 90, 40)))
        orange = imaging.aurora_score(flat_rgb((w, h), (120, 70, 20)))
        black = imaging.aurora_score(flat_rgb((w, h), (5, 6, 5)))
        self.assertGreater(green, 90)
        self.assertEqual(orange, 0)
        self.assertEqual(black, 0)

    def test_brightness(self):
        self.assertAlmostEqual(imaging.brightness(flat_rgb((4, 4), (100, 100, 100))), 100, delta=1)

    def star(self, sigma):
        w, h = 120, 80
        gray = bytearray([10]) * (w * h)
        for y in range(h):
            for x in range(w):
                d2 = (x - 60) ** 2 + (y - 40) ** 2
                gray[y * w + x] = min(255, 10 + int(200 * 2.718 ** (-d2 / (2 * sigma * sigma))))
        return imaging.focus_from_gray(bytes(gray), (w, h))

    def test_tighter_star_has_smaller_hfd(self):
        sharp, soft = self.star(1.0), self.star(3.0)
        self.assertTrue(sharp["star"])
        self.assertLess(sharp["hfd"], soft["hfd"])
        self.assertAlmostEqual(sharp["x"], 0.5, delta=0.02)
        self.assertEqual(len(sharp["histogram"]), 32)

    def test_scores_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            shots = os.path.join(tmp, "shots")
            os.makedirs(shots)
            imaging.save_score(shots, "a.jpg", {"aurora": 5.0, "mean": 40})
            self.assertEqual(imaging.load_scores(shots)["a.jpg"]["aurora"], 5.0)
            imaging.forget_scores(shots, ["a.jpg"])
            self.assertEqual(imaging.load_scores(shots), {})


class ExposureTests(unittest.TestCase):
    def test_ladder_is_ordered_and_ends_at_max_iso(self):
        rungs = exposure.ladder(8, base_iso=400, max_iso=6400, shortest=1 / 4)
        values = [t * iso for t, iso in rungs]
        self.assertEqual(values, sorted(values))
        self.assertEqual(rungs[-1], (8.0, 6400))
        self.assertAlmostEqual(rungs[0][0], 0.25, delta=0.02)

    def test_ramp_moves_toward_the_band(self):
        rungs = exposure.ladder(8, base_iso=400, shortest=1 / 4)
        ramp = exposure.Ramp(rungs, exposure.nearest_rung(rungs, 8, 1600), exposure.NIGHT)
        self.assertEqual(ramp.current, (8.0, 1600))
        ramp.step(10)                       # far too dark: a full stop brighter
        self.assertEqual(ramp.current, (8.0, 3200))
        ramp.step(60)                       # in the band: stay
        self.assertEqual(ramp.current, (8.0, 3200))
        ramp.step(240)                      # blown out: a full stop darker
        self.assertEqual(ramp.current, (8.0, 1600))


class SkyTests(unittest.TestCase):
    def test_magnetic_latitude_and_kp_needed(self):
        # Fairbanks sits under the oval; the US Midwest needs a storm.
        self.assertGreater(sky.magnetic_latitude(64.84, -147.72), 63)
        self.assertLess(sky.kp_needed(64.84, -147.72), 1)
        self.assertGreater(sky.kp_needed(43.07, -89.40), 4)

    def test_moon_phase(self):
        full = sky.moon(0, 0, datetime(2026, 10, 26, 4, 0, tzinfo=timezone.utc))["illumination"]
        new = sky.moon(0, 0, datetime(2026, 11, 9, 7, 0, tzinfo=timezone.utc))["illumination"]
        self.assertGreater(full, 0.95)
        self.assertLess(new, 0.05)

    def test_plan_with_canned_feeds(self):
        now = datetime(2026, 10, 30, 20, 0, tzinfo=timezone.utc)
        kp = [["time_tag", "kp", "observed"]] + [
            [f"2026-10-{d:02d}T{h:02d}:00:00", "6.0", "predicted"] for d in (30, 31) for h in range(0, 24, 3)]
        hours = [f"2026-10-{d:02d}T{h:02d}:00" for d in (30, 31, 11) for h in range(24)]
        clouds = {"hourly": {"time": hours, "cloud_cover": [5] * len(hours)}}

        def fake(url, timeout=20):
            return kp if "k-index" in url else clouds
        with mock.patch.object(sky, "_fetch", side_effect=fake):
            p = sky.plan(43.07, -89.40, nights=1, now=now)
        night = p["nights"][0]
        self.assertTrue(night["hours"])
        self.assertIn(night["verdict"], ("Good", "Maybe"))
        self.assertEqual(night["kp_max"], 6.0)


class NotifyTests(unittest.TestCase):
    def test_topic_is_random_and_kept(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"NIKON_DATA": tmp}):
            first = notify.load()["topic"]
            self.assertTrue(first.startswith("nikon-d3400-") and len(first) > 20)
            self.assertEqual(notify.load()["topic"], first)
            self.assertNotEqual(notify.update({"new_topic": True})["topic"], first)
            self.assertFalse(notify.load()["enabled"])
            self.assertEqual(notify.send("t", "m"), "Alerts are off.")

    def test_headers_are_ascii(self):
        self.assertEqual(notify._ascii("Aim N 5°"), "Aim N 5 deg")


class UsbResetTests(unittest.TestCase):
    def test_finds_nikon_in_sysfs(self):
        with tempfile.TemporaryDirectory() as root:
            for name, vendor, bus, dev in (("1-1", "046d", 1, 2), ("1-1.2", "04b0", 1, 5)):
                os.makedirs(os.path.join(root, name))
                for f, v in (("idVendor", vendor), ("busnum", bus), ("devnum", dev)):
                    with open(os.path.join(root, name, f), "w") as handle:
                        handle.write(f"{v}\n")
            self.assertEqual(camera.nikon_usb_device(root), "/dev/bus/usb/001/005")

    def test_stuck_link_is_reset_and_retried_once(self):
        cam = camera.Camera(tempfile.mkdtemp())
        calls = []

        def once(args, timeout):
            calls.append(args)
            if len(calls) == 1:
                raise camera.CameraError("*** Error (-7: 'I/O problem') ***")
            return "ok"
        with mock.patch.object(cam, "_run_once", side_effect=once), \
                mock.patch.object(camera, "usb_reset", return_value="Reset /dev/bus/usb/001/005"):
            self.assertEqual(cam.run(["--summary"]), "ok")
        self.assertEqual(len(calls), 2)
        self.assertEqual(cam.resets, 1)

    def test_refusals_are_not_retried(self):
        cam = camera.Camera(tempfile.mkdtemp())
        with mock.patch.object(cam, "_run_once", side_effect=camera.CameraError("Bad value")), \
                mock.patch.object(camera, "usb_reset") as reset:
            with self.assertRaises(camera.CameraError):
                cam.run(["--set-config", "x=1"])
        reset.assert_not_called()

    def test_tether_filename_keeps_the_card_name(self):
        self.assertFalse(camera.usb_stuck("Saving file as tether-20261029-110512-DSC_0053.JPG"))


if __name__ == "__main__":
    unittest.main()
