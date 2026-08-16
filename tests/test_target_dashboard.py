from __future__ import annotations

import unittest

from hackex2.adb.ui import parse_ui_hierarchy
from hackex2.target_dashboard import (
    TargetDashboardParseError,
    parse_target_dashboard,
)

from tests.test_screen_detector import hierarchy_xml


def target_node(
    *,
    text: str,
    bounds: str,
    clickable: bool = False,
    class_name: str = "android.widget.TextView",
) -> str:
    return (
        f"<node text='{text}' resource-id='' class='{class_name}' "
        "package='net.cncapps.hackex2' content-desc='' "
        f"clickable='{'true' if clickable else 'false'}' enabled='true' "
        f"bounds='{bounds}' />"
    )


def target_dashboard_xml(*, xp_percent: int = 86) -> str:
    return hierarchy_xml(
        target_node(text="CONNECTED", bounds="[73,185][222,219]"),
        target_node(
            text="DISCONNECT",
            bounds="[810,168][1035,236]",
            clickable=True,
            class_name="android.widget.Button",
        ),
        target_node(text="&gt; nebthepleb _ [NUT5]", bounds="[45,284][644,354]"),
        target_node(text="LVL 5", bounds="[154,430][261,475]"),
        target_node(text="REP 720", bounds="[343,430][489,475]"),
        target_node(text="694 ", bounds="[866,424][967,480]"),
        target_node(text="SCORE", bounds="[964,441][1035,466]"),
        target_node(text="// XP PROGRESS", bounds="[92,615][326,649]"),
        target_node(text="2229 / 2605", bounds="[807,613][990,652]"),
        target_node(text=f"{xp_percent}%", bounds="[92,720][990,756]"),
        target_node(
            text="WALLET", bounds="[45,855][354,1049]", clickable=True,
            class_name="android.widget.Button",
        ),
        target_node(
            text="APPS", bounds="[385,855][694,1049]", clickable=True,
            class_name="android.widget.Button",
        ),
        target_node(
            text="PROCESSES", bounds="[725,855][1035,1049]", clickable=True,
            class_name="android.widget.Button",
        ),
        target_node(
            text="LOG", bounds="[45,1080][354,1274]", clickable=True,
            class_name="android.widget.Button",
        ),
        target_node(
            text="CREWS", bounds="[385,1080][694,1274]", clickable=True,
            class_name="android.widget.Button",
        ),
        target_node(text="// SYSTEM INFO", bounds="[90,1369][323,1403]"),
        target_node(text="IP", bounds="[90,1459][123,1493]"),
        target_node(
            text="51.73.134.95", bounds="[776,1456][990,1499]", clickable=True,
            class_name="android.widget.Button",
        ),
        target_node(text="DEVICE", bounds="[135,1546][227,1580]"),
        target_node(text="Raider", bounds="[888,1546][990,1586]"),
        target_node(text="NETWORK", bounds="[135,1636][244,1670]"),
        target_node(text="Cable", bounds="[905,1631][990,1673]"),
        target_node(text="FIREWALL", bounds="[135,1721][258,1755]"),
        target_node(text="Lv.1", bounds="[922,1721][990,1760]"),
        target_node(text="ENCRYPTOR", bounds="[135,1811][272,1845]"),
        target_node(text="Lv.1", bounds="[922,1808][990,1847]"),
    )


class TargetDashboardParserTest(unittest.TestCase):
    def test_parses_observed_target_dashboard(self) -> None:
        target = parse_target_dashboard(parse_ui_hierarchy(target_dashboard_xml()))

        self.assertEqual(target.username, "nebthepleb")
        self.assertEqual(target.crew_tag, "NUT5")
        self.assertEqual(target.level, 5)
        self.assertEqual(target.reputation, 720)
        self.assertEqual(target.score, 694)
        self.assertEqual((target.xp_current, target.xp_required), (2229, 2605))
        self.assertEqual(target.xp_percent, 86)
        self.assertEqual(target.ip_address, "51.73.134.95")
        self.assertEqual(target.device, "Raider")
        self.assertEqual(target.network, "Cable")
        self.assertEqual(target.firewall_level, 1)
        self.assertEqual(target.encryptor_level, 1)
        self.assertEqual(
            target.available_actions,
            ("DISCONNECT", "WALLET", "APPS", "PROCESSES", "LOG", "CREWS"),
        )

    def test_rejects_inconsistent_xp_percentage(self) -> None:
        with self.assertRaisesRegex(
            TargetDashboardParseError, "XP percentage does not agree"
        ):
            parse_target_dashboard(
                parse_ui_hierarchy(target_dashboard_xml(xp_percent=30))
            )


if __name__ == "__main__":
    unittest.main()
