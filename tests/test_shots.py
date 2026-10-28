import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "payload", "app"))

_tmp = tempfile.mkdtemp()
os.environ["NIKON_DATA"] = _tmp
os.environ["NIKON_WIFI"] = os.path.join(_tmp, "wifi.json")
os.environ["NIKON_PASSWORD_FILE"] = os.path.join(_tmp, "password")

from server import delete_shots, password_from_cookie, shot_filename


class DeleteShotTests(unittest.TestCase):
    def test_a_named_file_is_removed_and_a_path_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            keep = os.path.join(folder, "keep.jpg")
            drop = os.path.join(folder, "drop.jpg")
            open(keep, "wb").close()
            open(drop, "wb").close()
            removed = delete_shots(folder, names=["drop.jpg"])
            self.assertEqual(removed, ["drop.jpg"])
            self.assertTrue(os.path.isfile(keep))
            self.assertFalse(os.path.isfile(drop))
            with self.assertRaises(ValueError):
                delete_shots(folder, names=["../keep.jpg"])
            self.assertTrue(os.path.isfile(keep))

    def test_all_removes_only_the_files_in_the_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            open(os.path.join(folder, "one.jpg"), "wb").close()
            open(os.path.join(folder, "one.nef"), "wb").close()
            removed = delete_shots(folder, all_files=True)
            self.assertEqual(sorted(removed), ["one.jpg", "one.nef"])
            self.assertEqual(os.listdir(folder), [])

    def test_shot_filename_rejects_a_folder(self):
        self.assertEqual(shot_filename("shot.jpg"), "shot.jpg")
        with self.assertRaises(ValueError):
            shot_filename("shots/shot.jpg")

    def test_password_cookie_is_read_for_the_download_link(self):
        self.assertEqual(password_from_cookie(""), "")
        self.assertEqual(
            password_from_cookie("other=1; nikon-password=nikon-d3400"),
            "nikon-d3400",
        )
        self.assertEqual(
            password_from_cookie("nikon-password=a%20b%3Dc"),
            "a b=c",
        )


if __name__ == "__main__":
    unittest.main()
