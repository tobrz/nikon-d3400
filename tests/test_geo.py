import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "payload", "app"))

import geo


class GeoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["NIKON_DATA"] = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("NIKON_DATA", None)

    def test_exif_args_use_hemisphere_refs(self):
        args = geo.exif_args(43.07, -89.40, 266)
        self.assertIn("-GPSLatitudeRef=N", args)
        self.assertIn("-GPSLongitudeRef=W", args)
        self.assertIn("-GPSAltitudeRef=0", args)
        south = geo.exif_args(-33.8, 151.2, -2)
        self.assertIn("-GPSLatitudeRef=S", south)
        self.assertIn("-GPSLongitudeRef=E", south)
        self.assertIn("-GPSAltitudeRef=1", south)

    def test_snapbridge_skips_the_stamp(self):
        geo.update({"snapbridge": True, "lat": 43.0, "lon": -89.0})
        result = geo.stamp("/tmp/DSC_0001.JPG", runner=lambda cmd: None)
        self.assertEqual(result["skipped"], "snapbridge")

    def test_stamp_runs_exiftool_args(self):
        geo.update({"snapbridge": False, "lat": 43.0, "lon": -89.0, "alt": 10})
        seen = []
        result = geo.stamp("/tmp/DSC_0001.JPG", runner=seen.append)
        self.assertTrue(result["stamped"])
        self.assertIn("-GPSLatitude=43.0", seen[0])
        self.assertEqual(seen[0][-1], "/tmp/DSC_0001.JPG")

    def test_rejects_a_latitude_past_the_pole(self):
        with self.assertRaises(ValueError):
            geo.update({"lat": 91, "lon": 0})


if __name__ == "__main__":
    unittest.main()
