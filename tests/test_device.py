from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from hackex2.adb.device import ADBClient


class DeviceInspectionTest(unittest.TestCase):
    @patch("hackex2.adb.device.subprocess.run")
    def test_inspects_authorized_device_and_effective_resolution(self, run) -> None:
        run.side_effect = [
            subprocess.CompletedProcess(
                args=["adb", "devices", "-l"],
                returncode=0,
                stdout=(
                    "List of devices attached\n"
                    "R3CT000000 device product:e3qxxx model:SM-S928B "
                    "device:e3q transport_id:1\n"
                ),
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["adb", "-s", "R3CT000000", "shell", "wm", "size"],
                returncode=0,
                stdout="Physical size: 1440x3120\nOverride size: 1080x2340\n",
                stderr="",
            ),
        ]

        device = ADBClient().inspect_device()

        self.assertEqual(device.serial, "R3CT000000")
        self.assertEqual(device.model, "SM-S928B")
        self.assertEqual((device.width, device.height), (1080, 2340))
        self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()

