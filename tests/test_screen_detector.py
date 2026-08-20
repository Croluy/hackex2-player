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

    def test_detects_observed_target_wallet_login_branch(self) -> None:
        hierarchy = parse_ui_hierarchy(
            hierarchy_xml(
                node(text="// CRYPTO WALLET"),
                node(text="WALLET LOGIN"),
                node(text="USERNAME"),
                node(text="PASSWORD"),
                node(text="LOGIN &gt;", clickable=True),
                node(text="&lt; back", clickable=True),
                node(text="DISCONNECT", clickable=True),
            )
        )

        detection = detect_screen(hierarchy)

        self.assertEqual(detection.state, ScreenState.TARGET_WALLET_LOGIN)
        self.assertEqual(detection.confidence, 1.0)
        self.assertEqual(len(detection.evidence), 7)

    def test_unknown_wallet_variant_is_not_assumed_to_be_login(self) -> None:
        hierarchy = parse_ui_hierarchy(
            hierarchy_xml(
                node(text="// CRYPTO WALLET"),
                node(text="WALLET SECURITY"),
                node(text="&lt; back", clickable=True),
                node(text="DISCONNECT", clickable=True),
            )
        )

        detection = detect_screen(hierarchy)

        self.assertEqual(detection.state, ScreenState.UNKNOWN_SCREEN)
        self.assertIn("wallet Login panel", detection.missing_evidence)

    def test_detects_encrypted_password_wallet_branch_from_accessible_text(self) -> None:
        hierarchy = parse_ui_hierarchy(
            hierarchy_xml(
                node(text="// CRYPTO WALLET"),
                node(text="WALLET LOGIN"),
                node(text="USERNAME"),
                node(text="PASSWORD"),
                node(text="Password encrypted at Lv.6"),
                node(text="* USE EXPLOIT KIT (x3)", clickable=True),
                node(text="* CRACK PASSWORD", clickable=True),
                node(text="&lt; back", clickable=True),
                node(text="DISCONNECT", clickable=True),
            )
        )

        detection = detect_screen(hierarchy)

        self.assertEqual(
            detection.state, ScreenState.TARGET_WALLET_PASSWORD_REQUIRED
        )
        self.assertEqual(detection.confidence, 1.0)
        self.assertEqual(len(detection.evidence), 9)

    def test_detects_authenticated_wallet_independent_of_transfer_branch(self) -> None:
        hierarchy = parse_ui_hierarchy(
            hierarchy_xml(
                node(text="// CRYPTO WALLET"),
                node(text="WALLET ADDRESS"),
                node(text="HHOT WALLET38 CryptoSWALLET SHIELD ACTIVE"),
                node(text="&lt; back", clickable=True),
                node(text="DISCONNECT", clickable=True),
            )
        )

        detection = detect_screen(hierarchy)

        self.assertEqual(detection.state, ScreenState.TARGET_WALLET_AUTHENTICATED)
        self.assertEqual(detection.confidence, 1.0)
        self.assertEqual(len(detection.evidence), 5)

    def test_detects_target_log_even_when_editor_and_save_are_disabled(self) -> None:
        hierarchy = parse_ui_hierarchy(
            hierarchy_xml(
                node(text="// VICTIM LOG"),
                (
                    "<node text='existing log data' resource-id='' "
                    "class='android.widget.EditText' "
                    "package='net.cncapps.hackex2' content-desc='' "
                    "clickable='true' enabled='false' bounds='[45,455][1035,2200]' />"
                ),
                (
                    "<node text='SAVE' resource-id='' class='android.widget.Button' "
                    "package='net.cncapps.hackex2' content-desc='' "
                    "clickable='true' enabled='false' bounds='[869,233][1035,340]' />"
                ),
                node(text="DISCONNECT", clickable=True),
            )
        )

        detection = detect_screen(hierarchy)

        self.assertEqual(detection.state, ScreenState.TARGET_LOG)
        self.assertEqual(detection.confidence, 1.0)
        self.assertEqual(len(detection.evidence), 4)


if __name__ == "__main__":
    unittest.main()
