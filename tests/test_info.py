import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import stcc  # noqa: E402


class InfoTest(unittest.TestCase):
    def test_gather_info_returns_expected_keys(self):
        info = stcc.gather_info()
        for key in ("version", "python", "system", "cpu", "logical_cores",
                    "ram_total_gb", "ram_available_gb", "gpu", "components"):
            self.assertIn(key, info)
        self.assertEqual(info["version"], stcc.VERSION)
        self.assertEqual(
            set(info["components"]), {"parakeet_cpp", "fluid_speech_mini", "silero_vad"}
        )

    def test_component_presence_flag_is_bool(self):
        info = stcc.gather_info()
        for entry in info["components"].values():
            self.assertIsInstance(entry["present"], bool)

    def test_ram_gb_shape(self):
        mem = stcc.ram_gb()
        self.assertIn("total", mem)
        self.assertIn("available", mem)
        if mem["total"] is not None:
            self.assertGreater(mem["total"], 0.5)


if __name__ == "__main__":
    unittest.main()
