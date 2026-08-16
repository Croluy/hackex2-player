from __future__ import annotations

import unittest

from hackex2.adb.ui import parse_ui_hierarchy
from hackex2.states import ScreenState, detect_screen


def hierarchy_xml(*nodes: str, package: str = "net.cncapps.hackex2") -> str:
    return (
        "<?xml version='1.0' encoding='UTF-8' ?>"
        "<hierarchy rotation='0'>"
        f"<node text='' resource-id='' class='android.webkit.WebView' "
        f"package='{package}' content-desc='' clickable='false' enabled='true' "
        "bounds='[0,0][1080,2340]'>"
        f"{''.join(nodes)}"
        "</node></hierarchy>"
    )


def node(
    *,
    text: str = "",
    resource_id: str = "",
    content_description: str = "",
    clickable: bool = False,
) -> str:
    return (
        f"<node text='{text}' resource-id='{resource_id}' "
        "class='android.view.View' package='net.cncapps.hackex2' "
        f"content-desc='{content_description}' clickable='{'true' if clickable else 'false'}' "
        "enabled='true' bounds='[10,10][200,100]' />"
    )


class ScreenDetectorTest(unittest.TestCase):
    def test_detects_home_only_with_all_independent_markers(self) -> None:
        hierarchy = parse_ui_hierarchy(
            hierarchy_xml(
                node(
                    text="HOME",
                    resource_id="nav-item-dashboard",
                    clickable=True,
                ),
                node(text="// XP PROGRESS"),
                node(content_description="MY DEVICE", clickable=True),
                node(
                    resource_id="onboard-scan-btn",
                    content_description="SCAN",
                    clickable=True,
                ),
            )
        )

        detection = detect_screen(hierarchy)

        self.assertEqual(detection.state, ScreenState.HOME)
        self.assertEqual(detection.confidence, 1.0)
        self.assertEqual(len(detection.evidence), 4)
        self.assertEqual(detection.missing_evidence, ())

    def test_reports_unknown_when_a_home_marker_is_missing(self) -> None:
        hierarchy = parse_ui_hierarchy(
            hierarchy_xml(
                node(
                    text="HOME",
                    resource_id="nav-item-dashboard",
                    clickable=True,
                ),
                node(content_description="MY DEVICE", clickable=True),
                node(
                    resource_id="onboard-scan-btn",
                    content_description="SCAN",
                    clickable=True,
                ),
            )
        )

        detection = detect_screen(hierarchy)

        self.assertEqual(detection.state, ScreenState.UNKNOWN_SCREEN)
        self.assertEqual(detection.confidence, 0.0)
        self.assertEqual(detection.missing_evidence, ("XP progress panel",))

    def test_detects_processes_without_assuming_a_process_count(self) -> None:
        hierarchy = parse_ui_hierarchy(
            hierarchy_xml(
                node(
                    text="PROCESSES",
                    resource_id="nav-item-processes",
                    clickable=True,
                ),
                node(text="// PROCESSES"),
                node(content_description="Search", clickable=True),
                node(text="ALL", clickable=True),
                node(text="0 active tasks"),
            )
        )

        detection = detect_screen(hierarchy)

        self.assertEqual(detection.state, ScreenState.PROCESSES)
        self.assertEqual(detection.confidence, 1.0)
        self.assertEqual(len(detection.evidence), 4)

    def test_detects_target_dashboard_only_with_all_independent_markers(self) -> None:
        hierarchy = parse_ui_hierarchy(
            hierarchy_xml(
                node(text="CONNECTED"),
                node(text="DISCONNECT", clickable=True),
                node(text="// XP PROGRESS"),
                node(text="WALLET", clickable=True),
                node(text="APPS", clickable=True),
                node(text="LOG", clickable=True),
                node(text="CREWS", clickable=True),
                node(text="// SYSTEM INFO"),
            )
        )

        detection = detect_screen(hierarchy)

        self.assertEqual(detection.state, ScreenState.TARGET_DASHBOARD)
        self.assertEqual(detection.confidence, 1.0)
        self.assertEqual(len(detection.evidence), 8)

    def test_does_not_confuse_partial_target_dashboard_with_home(self) -> None:
        hierarchy = parse_ui_hierarchy(
            hierarchy_xml(
                node(text="CONNECTED"),
                node(text="DISCONNECT", clickable=True),
                node(text="// XP PROGRESS"),
                node(text="WALLET", clickable=True),
                node(text="APPS", clickable=True),
                node(text="LOG", clickable=True),
                node(text="// SYSTEM INFO"),
            )
        )

        detection = detect_screen(hierarchy)

        self.assertEqual(detection.state, ScreenState.UNKNOWN_SCREEN)
        self.assertIn("target Crews action", detection.missing_evidence)


if __name__ == "__main__":
    unittest.main()
