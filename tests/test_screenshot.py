from __future__ import annotations

import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hackex2.adb.device import ADBClient


class ScreenshotCaptureTest(unittest.TestCase):
    @patch("hackex2.adb.device.subprocess.run")
    def test_captures_verified_png_for_authorized_device(self, run) -> None:
        png = (
            b"\x89PNG\r\n\x1a\n"
            + struct.pack(">I", 13)
            + b"IHDR"
            + struct.pack(">II", 1080, 2340)
            + b"\x08\x06\x00\x00\x00"
        )
        run.side_effect = [
            subprocess.CompletedProcess(
                args=["adb", "devices", "-l"],
                returncode=0,
                stdout=(
                    "List of devices attached\n"
                    "R5CY235KPLP device model:SM_S938B transport_id:1\n"
                ),
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=[
                    "adb",
                    "-s",
                    "R5CY235KPLP",
                    "exec-out",
                    "screencap",
                    "-p",
                ],
                returncode=0,
                stdout=png,
                stderr=b"",
            ),
        ]

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory, "screen.png")
            screenshot = ADBClient().capture_screenshot(output)

            self.assertEqual(output.read_bytes(), png)
            self.assertEqual(screenshot.serial, "R5CY235KPLP")
            self.assertEqual((screenshot.width, screenshot.height), (1080, 2340))
            self.assertEqual(screenshot.byte_count, len(png))


if __name__ == "__main__":
    unittest.main()
