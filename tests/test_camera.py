import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "payload", "app"))

from camera import deletion_order, parse_configs, parse_files
from guide import classify, plan


SAMPLE = """
/main/imgsettings/iso
Label: ISO Speed
Readonly: 0
Type: RADIO
Current: 400
Choice: 0 100
Choice: 1 400
Choice: 2 1600
END
/main/status/batterylevel
Label: Battery Level
Readonly: 1
Type: TEXT
Current: 80%
END
/main/capturesettings/focallength
Label: Focal Length
Readonly: 1
Type: TEXT
Current: 18 mm
END
"""


class ParseTests(unittest.TestCase):
    def test_configs(self):
        blocks = parse_configs(SAMPLE)
        self.assertEqual(len(blocks), 3)
        iso = blocks[0]
        self.assertEqual(iso["key"], "iso")
        self.assertFalse(iso["readonly"])
        self.assertEqual(iso["choices"][2]["label"], "1600")
        self.assertTrue(blocks[1]["readonly"])

    def test_files(self):
        text = "There is 1 file in folder '/store_00010001/DCIM/100D3400'.\n#1     DSC_0001.JPG rd 100 KB\n"
        rows = parse_files(text)
        self.assertEqual(rows[0]["name"], "DSC_0001.JPG")
        self.assertEqual(rows[0]["index"], 1)

    def test_deletion_order_is_highest_index_first_in_each_folder(self):
        files = [
            {"folder": "/a", "index": 1, "name": "one.jpg"},
            {"folder": "/a", "index": 3, "name": "three.jpg"},
            {"folder": "/b", "index": 2, "name": "two.jpg"},
            {"folder": "/a", "index": 2, "name": "two-a.jpg"},
        ]
        ordered = [(item["folder"], item["index"]) for item in deletion_order(files)]
        self.assertEqual(ordered, [("/a", 3), ("/a", 2), ("/a", 1), ("/b", 2)])

    def test_milky_way_plan(self):
        self.assertEqual(classify("I want a night shot of the Milky Way"), "milky")
        built = plan("milky way please", parse_configs(SAMPLE))
        self.assertEqual(built["kind"], "milky")
        self.assertEqual(built["settings"]["iso"], "1600")
        self.assertEqual(built["settings"]["shutterspeed"], "11")
        text = " ".join(step["title"] + " " + step["body"] for step in built["steps"]).lower()
        self.assertIn("manual focus", text)
        self.assertIn("focus ring", text)


if __name__ == "__main__":
    unittest.main()
