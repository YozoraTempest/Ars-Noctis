import os
import unittest

import settings


class SettingsTests(unittest.TestCase):
    def test_current_mode_tracks_environment(self) -> None:
        os.environ["APP_MODE"] = "test"
        self.assertEqual(settings.current_mode(), "test")


if __name__ == "__main__":
    unittest.main()
