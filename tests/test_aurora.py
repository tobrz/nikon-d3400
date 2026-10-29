import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "payload", "app"))

import aurora


class AuroraTests(unittest.TestCase):
    def test_bearing_and_cardinal(self):
        self.assertAlmostEqual(aurora.bearing(43.0, -89.4, 50.0, -89.4), 0, delta=0.5)
        self.assertEqual(aurora.cardinal(0), "N")
        self.assertEqual(aurora.cardinal(22), "NNE")
        self.assertEqual(aurora.cardinal(350), "N")

    def test_elevation_drops_with_distance(self):
        near, far = aurora.elevation(100), aurora.elevation(900)
        self.assertGreater(near, far)
        self.assertGreater(far, 0)

    def test_sun_altitude_noon_vs_midnight(self):
        # Madison, WI: local noon (≈18:00 UTC) in June is high; local midnight is below the horizon.
        noon = aurora.sun_altitude(43.07, -89.40, datetime(2026, 6, 21, 18, 0, tzinfo=timezone.utc))
        night = aurora.sun_altitude(43.07, -89.40, datetime(2026, 6, 22, 6, 0, tzinfo=timezone.utc))
        self.assertGreater(noon, 60)
        self.assertLess(night, -12)

    def test_sky_finds_band_to_the_north(self):
        # A 40% band at 50°N; observer at 43°N (≈780 km south) should see it, aiming north.
        points = [[lon, 50, 40] for lon in range(0, 360)] + [[lon, 43, 0] for lon in range(0, 360)]
        r = aurora.sky(43.07, -89.40, points)
        self.assertEqual(r["visible"], 40)
        self.assertEqual(r["direction"], "N")
        self.assertEqual(r["overhead"], 0)

    def test_sky_ignores_far_aurora(self):
        points = [[lon, 70, 90] for lon in range(0, 360)]
        r = aurora.sky(43.07, -89.40, points)
        self.assertEqual(r["visible"], 0)
        self.assertIsNone(r["bearing"])

    def test_outlook_needs_location(self):
        with self.assertRaises(aurora.AuroraError):
            aurora.outlook(None, None)


if __name__ == "__main__":
    unittest.main()
