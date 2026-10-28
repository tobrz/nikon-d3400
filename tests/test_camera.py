import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "payload", "app"))

from camera import (
    adopt_preview,
    bracket_plan,
    deletion_order,
    format_shutter,
    index_spec,
    jpeg_payload,
    live_view_block_reason,
    nearest_shutter_label,
    parse_configs,
    parse_files,
    preview_download_path,
    saved_thumbnail_name,
    shutter_seconds,
    thumb_cache_key,
)
from jobs import concat_script, jpeg_frames
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

    def test_index_spec_groups_a_run_of_file_numbers(self):
        self.assertEqual(index_spec([3, 1, 2, 5]), "1-3,5")
        self.assertEqual(index_spec([24]), "24")
        self.assertEqual(saved_thumbnail_name("thumb_APB_3930.JPG"), "APB_3930.JPG")

    def test_thumb_cache_key_uses_the_folder_and_the_file_name(self):
        self.assertEqual(
            thumb_cache_key("/store_00010001/DCIM/100D3400", "APB_3930.JPG"),
            "store_00010001_DCIM_100D3400_APB_3930.JPG.jpg",
        )
        with self.assertRaises(ValueError):
            thumb_cache_key("/store/../etc", "x.jpg")
        with self.assertRaises(ValueError):
            thumb_cache_key("/store", "../x.jpg")

    def test_jpeg_payload_skips_text_before_the_image(self):
        self.assertEqual(jpeg_payload(b"Saving\n\xff\xd8jpeg"), b"\xff\xd8jpeg")
        self.assertEqual(jpeg_payload(b"no image"), b"")

    def test_preview_is_saved_under_the_thumb_name(self):
        requested = "/var/lib/nikon-d3400/preview.jpg"
        self.assertEqual(preview_download_path(requested), "/var/lib/nikon-d3400/thumb_preview.jpg")
        with tempfile.TemporaryDirectory() as tmp:
            asked = os.path.join(tmp, "preview.jpg")
            written = preview_download_path(asked)
            with open(written, "wb") as handle:
                handle.write(b"\xff\xd8jpeg")
            self.assertEqual(adopt_preview(asked), asked)
            with open(asked, "rb") as handle:
                self.assertEqual(handle.read(), b"\xff\xd8jpeg")
            self.assertFalse(os.path.exists(written))

    def test_manual_mode_live_view_message_is_not_a_block(self):
        self.assertEqual(live_view_block_reason("Liveview should not be prohibited"), "")
        self.assertEqual(live_view_block_reason("No live view prohibit conditions"), "")
        blocked = live_view_block_reason("Live View prohibit conditions: Exposure Program Mode is not P/A/S/M")
        self.assertIn("P, A, S, or M", blocked)

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


SPEEDS = ["0.0100s", "1.0000s", "2.0000s", "15.0000s", "30.0000s", "Bulb", "Time"]
STOPS = ["-1", "-0.333", "0", "0.333", "1"]


class ExposureTests(unittest.TestCase):
    def test_shutter_labels_from_the_d3400(self):
        self.assertEqual(shutter_seconds("30.0000s"), 30)
        self.assertEqual(shutter_seconds("0.0100s"), 0.01)
        self.assertEqual(shutter_seconds("1/100"), 0.01)
        self.assertIsNone(shutter_seconds("Bulb"))
        self.assertIsNone(shutter_seconds("Time"))
        self.assertEqual(format_shutter(2), "2 seconds")
        self.assertEqual(format_shutter(1), "1 second")
        self.assertEqual(format_shutter(0.01), "1/100")

    def test_two_seconds_uses_a_timed_speed_and_a_minute_uses_bulb(self):
        self.assertEqual(nearest_shutter_label(2, SPEEDS), "2.0000s")
        self.assertEqual(nearest_shutter_label(30, SPEEDS), "30.0000s")
        self.assertIsNone(nearest_shutter_label(60, SPEEDS))

    def test_manual_bracket_steps_the_shutter_and_holds_the_long_frame(self):
        plan = bracket_plan("M", "30.0000s", SPEEDS, "0", STOPS, 3, 1)
        self.assertEqual(plan["control"], "shutterspeed")
        self.assertEqual(plan["restore"], "30.0000s")
        self.assertEqual(plan["frames"][0]["value"], "15.0000s")
        self.assertEqual(plan["frames"][1]["value"], "30.0000s")
        self.assertEqual(plan["frames"][2]["control"], "bulb")
        self.assertEqual(plan["frames"][2]["seconds"], 60)

    def test_aperture_bracket_steps_exposure_compensation(self):
        plan = bracket_plan("A", "0.0100s", SPEEDS, "0", STOPS, 3, "1")
        self.assertEqual(plan["control"], "exposurecompensation")
        self.assertEqual([frame["value"] for frame in plan["frames"]], ["-1", "0", "1"])
        with self.assertRaises(ValueError):
            bracket_plan("Auto", "0.0100s", SPEEDS, "0", STOPS, 3, 1)

    def test_movie_list_holds_each_jpeg_for_one_frame(self):
        script = concat_script(["/shots/a.jpg", "/shots/b.jpg"], 24)
        self.assertIn("duration 0.041667", script)
        self.assertTrue(script.strip().endswith("file '/shots/b.jpg'"))
        with tempfile.TemporaryDirectory() as tmp:
            jpeg = os.path.join(tmp, "frame.JPG")
            raw = os.path.join(tmp, "frame.NEF")
            open(jpeg, "wb").close()
            open(raw, "wb").close()
            self.assertEqual(jpeg_frames([raw, jpeg]), [jpeg])


if __name__ == "__main__":
    unittest.main()
