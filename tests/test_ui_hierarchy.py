from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hackex2.adb.device import ADBClient


HOME_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="" resource-id="" class="android.webkit.WebView"
        package="net.cncapps.hackex2" content-desc="" clickable="false"
        enabled="true" bounds="[0,0][1080,2340]">
    <node text="HOME" resource-id="nav-item-dashboard"
          class="android.widget.Button" package="net.cncapps.hackex2"
          content-desc="" clickable="true" enabled="true"
          bounds="[14,2148][163,2292]" />
    <node text="" resource-id="onboard-scan-btn" class="android.view.View"
          package="net.cncapps.hackex2" content-desc="SCAN" clickable="true"
          enabled="true" bounds="[45,905][354,1102]" />
  </node>
</hierarchy>"""


class UIHierarchyCaptureTest(unittest.TestCase):
    @patch("hackex2.adb.device.subprocess.run")
    def test_captures_and_parses_ui_hierarchy(self, run) -> None:
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
                    "uiautomator",
                    "dump",
                    "/dev/tty",
                ],
                returncode=0,
                stdout=f"{HOME_XML}UI hierchary dumped to: /dev/tty\n",
                stderr="",
            ),
        ]

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory, "home.xml")
            dump = ADBClient().capture_ui_hierarchy(output)

            self.assertEqual(dump.serial, "R5CY235KPLP")
            self.assertEqual(dump.hierarchy.packages, ("net.cncapps.hackex2",))
            self.assertEqual(len(dump.hierarchy.elements), 3)
            self.assertEqual(len(dump.hierarchy.clickable_elements), 2)
            home = dump.hierarchy.find_all(resource_id="nav-item-dashboard")[0]
            self.assertEqual(home.text, "HOME")
            self.assertEqual(home.bounds.center, (88, 2220))
            self.assertEqual(output.read_text(encoding="utf-8"), HOME_XML)


if __name__ == "__main__":
    unittest.main()
