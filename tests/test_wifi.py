import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "payload", "app"))

from wifi import parse_wifi_list


class WifiParseTests(unittest.TestCase):
    def test_scan_rows_keep_the_strongest_ssid(self):
        text = "\n".join([
            r"House:80:WPA2",
            r"House:40:WPA2",
            r"Net\:work:55:WPA1 WPA2",
            r":20:WPA2",
            r"OpenCafe:30:",
        ])
        rows = parse_wifi_list(text)
        self.assertEqual([item["ssid"] for item in rows], ["House", "Net:work", "OpenCafe"])
        self.assertEqual(rows[0]["signal"], 80)
        self.assertEqual(rows[1]["security"], "WPA1 WPA2")
        self.assertEqual(rows[2]["security"], "open")


if __name__ == "__main__":
    unittest.main()
