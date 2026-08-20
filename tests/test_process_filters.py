from __future__ import annotations

import random
import unittest

from hackex2.adb.device import ADBDevice
from hackex2.adb.input import HumanizedInput
from hackex2.adb.ui import UIHierarchyDump, parse_ui_hierarchy
from hackex2.config import InputSettings, NavigationSettings
from hackex2.process_filters import ProcessFilterController, ProcessFilterError
from hackex2.processes import ProcessFilter

from tests.test_processes import filter_button, process_card
from tests.test_screen_detector import hierarchy_xml, node


def filter_dump(process_name: str | None) -> UIHierarchyDump:
    nodes = [
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
    ]
    if process_name is not None:
        nodes.append(
            process_card(
                "2228339",
                "[45,452][1035,798]",
                process_name,
                "Lv.4",
                "SUCCESS",
            )
        )
    return UIHierarchyDump(
        serial="R5CY235KPLP",
        hierarchy=parse_ui_hierarchy(hierarchy_xml(*nodes)),
    )


class FakeADBClient:
    def __init__(self, dumps: list[UIHierarchyDump]) -> None:
        self.dumps = iter(dumps)
        self.taps: list[tuple[str, int, int]] = []

    def select_device(self, serial: str | None = None) -> ADBDevice:
        return ADBDevice(serial or "R5CY235KPLP", "device")

    def capture_ui_hierarchy(
        self, output_path=None, serial: str | None = None
    ) -> UIHierarchyDump:
        return next(self.dumps)

    def tap(self, serial: str, x: int, y: int) -> None:
        self.taps.append((serial, x, y))


class ProcessFilterControllerTest(unittest.TestCase):
    def test_selects_lock_and_verifies_password_crack_processes(self) -> None:
        client = FakeADBClient(
            [filter_dump("Firewall Bypass "), filter_dump("Password Crack ")]
        )
        controller = ProcessFilterController(
            client,
            HumanizedInput(
                InputSettings(0, 0, 0),
                random_source=random.Random(1),
                sleeper=lambda _: None,
            ),
            NavigationSettings(0, 2, 0),
            sleeper=lambda _: None,
        )

        result = controller.select(ProcessFilter.LOCK)

        self.assertEqual(result.source, ProcessFilter.SHIELD)
        self.assertEqual(result.destination, ProcessFilter.LOCK)
        self.assertEqual(result.observations, 1)
        self.assertEqual(len(client.taps), 1)

    def test_stops_when_selected_filter_is_empty_and_ambiguous(self) -> None:
        client = FakeADBClient([filter_dump("Firewall Bypass "), filter_dump(None)])
        controller = ProcessFilterController(
            client,
            HumanizedInput(InputSettings(0, 0, 0), sleeper=lambda _: None),
            NavigationSettings(0, 1, 2),
            sleeper=lambda _: None,
        )

        with self.assertRaisesRegex(ProcessFilterError, "unsafe to retry"):
            controller.select(ProcessFilter.LOCK)

        self.assertEqual(len(client.taps), 1)


if __name__ == "__main__":
    unittest.main()
