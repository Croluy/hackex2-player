from __future__ import annotations

import random
import unittest

from hackex2.adb.device import ADBDevice
from hackex2.adb.input import HumanizedInput
from hackex2.adb.ui import UIHierarchyDump, parse_ui_hierarchy
from hackex2.config import InputSettings, NavigationSettings
from hackex2.process_scroller import ProcessScroller, ScrollDirection

from tests.test_processes import filter_button, process_card
from tests.test_screen_detector import hierarchy_xml, node


def process_screen_dump(card_bounds: tuple[str, str, str]) -> UIHierarchyDump:
    cards = "".join(
        process_card(
            str(2228339 + index),
            bounds,
            "Firewall Bypass ",
            "Lv.4",
            "SUCCESS",
        )
        for index, bounds in enumerate(card_bounds)
    )
    scroll_region = (
        "<node text='' resource-id='' class='android.view.View' "
        "package='net.cncapps.hackex2' content-desc='' clickable='false' "
        "enabled='true' scrollable='true' bounds='[45,452][1035,2137]'>"
        f"{cards}</node>"
    )
    hierarchy = parse_ui_hierarchy(
        hierarchy_xml(
            node(
                text="PROCESSES",
                resource_id="nav-item-processes",
                clickable=True,
            ),
            node(text="// PROCESSES"),
            node(content_description="Search", clickable=True),
            filter_button(45, 135),
            filter_button(143, 261, "ALL"),
            filter_button(270, 385),
            filter_button(393, 506),
            filter_button(514, 630),
            filter_button(635, 750),
            filter_button(759, 874),
            filter_button(945, 1035),
            scroll_region,
        )
    )
    return UIHierarchyDump(serial="R5CY235KPLP", hierarchy=hierarchy)


class FakeADBClient:
    def __init__(self, dumps: list[UIHierarchyDump]) -> None:
        self.dumps = iter(dumps)
        self.swipes: list[tuple[str, int, int, int, int, int]] = []

    def select_device(self, serial: str | None = None) -> ADBDevice:
        return ADBDevice(serial or "R5CY235KPLP", "device")

    def capture_ui_hierarchy(
        self, output_path=None, serial: str | None = None
    ) -> UIHierarchyDump:
        return next(self.dumps)

    def swipe(
        self,
        serial: str,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration_ms: int,
    ) -> None:
        self.swipes.append(
            (serial, start_x, start_y, end_x, end_y, duration_ms)
        )


class ProcessScrollerTest(unittest.TestCase):
    def test_verifies_changed_signature_and_detects_last_process(self) -> None:
        before = process_screen_dump(
            ("[45,452][1035,798]", "[45,826][1035,1423]", "[0,0][0,0]")
        )
        after = process_screen_dump(
            ("[0,0][0,0]", "[45,452][1035,1049]", "[45,1077][1035,1674]")
        )
        client = FakeADBClient([before, after])
        scroller = ProcessScroller(
            client,
            HumanizedInput(
                InputSettings(0, 0, 0),
                random_source=random.Random(2),
                sleeper=lambda _: None,
            ),
            NavigationSettings(0, 1, 0),
            sleeper=lambda _: None,
        )

        result = scroller.scroll_once(ScrollDirection.UP)

        self.assertEqual(result.before_visible_ids, ("2228339", "2228340"))
        self.assertEqual(result.after_visible_ids, ("2228340", "2228341"))
        self.assertTrue(result.reached_boundary)
        self.assertEqual(len(client.swipes), 1)

    def test_reports_top_boundary_without_swiping(self) -> None:
        before = process_screen_dump(
            ("[45,452][1035,798]", "[45,826][1035,1423]", "[0,0][0,0]")
        )
        client = FakeADBClient([before])
        scroller = ProcessScroller(
            client,
            HumanizedInput(InputSettings(0, 0, 0), sleeper=lambda _: None),
            NavigationSettings(0, 1, 0),
            sleeper=lambda _: None,
        )

        result = scroller.scroll_once(ScrollDirection.DOWN)

        self.assertTrue(result.reached_boundary)
        self.assertEqual(result.attempts, 0)
        self.assertEqual(client.swipes, [])


if __name__ == "__main__":
    unittest.main()
