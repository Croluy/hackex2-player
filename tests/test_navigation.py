from __future__ import annotations

import random
import unittest

from hackex2.adb.device import ADBDevice
from hackex2.adb.input import HumanizedInput
from hackex2.adb.ui import UIHierarchyDump, parse_ui_hierarchy
from hackex2.config import InputSettings, NavigationSettings
from hackex2.navigation import NavigationError, Navigator
from hackex2.states import ScreenState

from tests.test_screen_detector import hierarchy_xml, node


def home_dump() -> UIHierarchyDump:
    return UIHierarchyDump(
        serial="R5CY235KPLP",
        hierarchy=parse_ui_hierarchy(
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
                node(
                    text="PROCESSES",
                    resource_id="nav-item-processes",
                    clickable=True,
                ),
            )
        ),
    )


def processes_dump() -> UIHierarchyDump:
    return UIHierarchyDump(
        serial="R5CY235KPLP",
        hierarchy=parse_ui_hierarchy(
            hierarchy_xml(
                node(
                    text="PROCESSES",
                    resource_id="nav-item-processes",
                    clickable=True,
                ),
                node(text="// PROCESSES"),
                node(content_description="Search", clickable=True),
                node(text="ALL", clickable=True),
            )
        ),
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


class NavigatorTest(unittest.TestCase):
    def test_taps_once_and_verifies_destination_after_observations(self) -> None:
        client = FakeADBClient([home_dump(), home_dump(), processes_dump()])
        humanized = HumanizedInput(
            InputSettings(200, 200, 0),
            random_source=random.Random(1),
            sleeper=lambda _: None,
        )
        navigator = Navigator(
            client,
            humanized,
            NavigationSettings(0, 3, 0),
            sleeper=lambda _: None,
        )

        result = navigator.navigate_to(ScreenState.PROCESSES)

        self.assertEqual(result.source, ScreenState.HOME)
        self.assertEqual(result.destination, ScreenState.PROCESSES)
        self.assertEqual(result.observations, 2)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(len(client.taps), 1)

    def test_stops_after_bounded_failed_observations(self) -> None:
        client = FakeADBClient([home_dump()] + [home_dump() for _ in range(4)])
        navigator = Navigator(
            client,
            HumanizedInput(InputSettings(0, 0, 0), sleeper=lambda _: None),
            NavigationSettings(0, 2, 1),
            sleeper=lambda _: None,
        )

        with self.assertRaisesRegex(NavigationError, "last observed HOME"):
            navigator.navigate_to(ScreenState.PROCESSES)

        self.assertEqual(len(client.taps), 2)

    def test_does_not_retry_an_unknown_observation(self) -> None:
        unknown = UIHierarchyDump(
            serial="R5CY235KPLP",
            hierarchy=parse_ui_hierarchy(
                hierarchy_xml(node(text="UNEXPECTED POPUP"))
            ),
        )
        client = FakeADBClient([home_dump(), unknown])
        navigator = Navigator(
            client,
            HumanizedInput(InputSettings(0, 0, 0), sleeper=lambda _: None),
            NavigationSettings(0, 3, 2),
            sleeper=lambda _: None,
        )

        with self.assertRaisesRegex(NavigationError, "unsafe to retry"):
            navigator.navigate_to(ScreenState.PROCESSES)

        self.assertEqual(len(client.taps), 1)


if __name__ == "__main__":
    unittest.main()
