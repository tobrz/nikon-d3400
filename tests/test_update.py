import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "payload", "app"))

from update import UpdateError, copy_payload, has_default_route


class UpdateTests(unittest.TestCase):
    def test_route_text(self):
        self.assertTrue(has_default_route("default via 192.168.1.1 dev eth0\n"))
        self.assertFalse(has_default_route("192.168.50.0/24 dev wlan0 proto kernel scope link\n"))

    def test_copy_replaces_the_app_and_skips_bytecode(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = os.path.join(tmp, "payload")
            app = os.path.join(payload, "app")
            os.makedirs(os.path.join(app, "__pycache__"))
            with open(os.path.join(app, "server.py"), "w") as handle:
                handle.write("new\n")
            with open(os.path.join(app, "__pycache__", "server.pyc"), "w") as handle:
                handle.write("nope")
            with open(os.path.join(payload, "bootstrap.sh"), "w") as handle:
                handle.write("#!/bin/bash\n")
            install = os.path.join(tmp, "install")
            os.makedirs(os.path.join(install, "app"))
            with open(os.path.join(install, "app", "server.py"), "w") as handle:
                handle.write("old\n")
            with open(os.path.join(install, "app", "gone.py"), "w") as handle:
                handle.write("old extra\n")
            with open(os.path.join(install, "keep-me"), "w") as handle:
                handle.write("stay\n")
            copy_payload(payload, install)
            with open(os.path.join(install, "app", "server.py")) as handle:
                self.assertEqual(handle.read(), "new\n")
            self.assertFalse(os.path.exists(os.path.join(install, "app", "gone.py")))
            self.assertFalse(os.path.exists(os.path.join(install, "app", "__pycache__")))
            with open(os.path.join(install, "keep-me")) as handle:
                self.assertEqual(handle.read(), "stay\n")
            mode = os.stat(os.path.join(install, "bootstrap.sh")).st_mode
            self.assertTrue(mode & stat.S_IXUSR)

    def test_copy_refuses_a_checkout_with_no_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UpdateError):
                copy_payload(tmp, os.path.join(tmp, "install"))


if __name__ == "__main__":
    unittest.main()
