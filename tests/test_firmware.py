import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "payload", "app"))

from firmware import compare, parse_camera, parse_published


class FirmwareTests(unittest.TestCase):
    def test_nikon_page_names_the_install_version(self):
        page = "update the D3400 camera &ldquo;C&rdquo; firmware to version 1.13. Before proceeding"
        self.assertEqual(parse_published(page), "1.13")

    def test_summary_device_version(self):
        self.assertEqual(parse_camera("Device Version: V1.13\nVendor Extension: Nikon"), "V1.13")

    def test_same_version_is_current(self):
        result = compare("V1.13", "1.13")
        self.assertEqual(result["relation"], "current")

    def test_older_body_is_behind(self):
        self.assertEqual(compare("V1.11", "1.13")["relation"], "behind")


if __name__ == "__main__":
    unittest.main()
