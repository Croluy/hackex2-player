from __future__ import annotations

import random
import unittest

from hackex2.adb.device import ADBDevice
from hackex2.adb.input import HumanizedInput
from hackex2.adb.ui import UIHierarchyDump, parse_ui_hierarchy
from hackex2.config import InputSettings, NavigationSettings
from hackex2.process_target_actions import (
    ProcessTargetActionError,
    ProcessTargetController,
    ProcessTargetStatus,
)

from tests.test_processes import process_card
from tests.test_screen_detector import hierarchy_xml, node
from tests.test_target_dashboard import target_dashboard_xml


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


def process_screen_dump(
    *, state: str = "SUCCESS", include_hack: bool = True
) -> UIHierarchyDump:
    extras = [
        node(text="88.55.27.70", clickable=True),
        node(text="66% chance"),
        node(text="rich"),
    ]
    if include_hack:
        extras.append(node(text="HACK", clickable=True))
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
            process_card(
                "1992580",
                "[45,452][1035,798]",
                "Password Crack ",
                "Lv.1",
                state,
                *extras,
            ),
        )
    )
    return UIHierarchyDump(serial="R5CY235KPLP", hierarchy=hierarchy)


def target_dump(ip_address: str = "88.55.27.70") -> UIHierarchyDump:
    return UIHierarchyDump(
        serial="R5CY235KPLP",
        hierarchy=parse_ui_hierarchy(target_dashboard_xml(ip_address=ip_address)),
    )


def controller(client: FakeADBClient, observations: int = 2) -> ProcessTargetController:
    return ProcessTargetController(
        client,
        HumanizedInput(
            InputSettings(0, 0, 0),
            random_source=random.Random(11),
            sleeper=lambda _: None,
        ),
        NavigationSettings(0, observations, 0),
        sleeper=lambda _: None,
    )


class ProcessTargetControllerTest(unittest.TestCase):
    def test_opens_completed_process_once_and_verifies_target_ip(self) -> None:
        client = FakeADBClient([process_screen_dump(), target_dump()])

        result = controller(client).open_completed_target(process_id="1992580")

        self.assertEqual(result.process.process_id, "1992580")
        self.assertEqual(result.status, ProcessTargetStatus.OPENED_TARGET)
        assert result.target is not None
        self.assertEqual(result.target.ip_address, "88.55.27.70")
        self.assertEqual(len(client.taps), 1)

    def test_waits_through_unknown_without_retrying_hack(self) -> None:
        unknown = UIHierarchyDump(
            serial="R5CY235KPLP",
            hierarchy=parse_ui_hierarchy(hierarchy_xml(node(text="CONNECTING"))),
        )
        client = FakeADBClient([process_screen_dump(), unknown, target_dump()])

        result = controller(client).open_completed_target(ip_address="88.55.27.70")

        self.assertEqual(result.observations, 2)
        self.assertEqual(len(client.taps), 1)

    def test_resolves_proxy_masked_dashboard_from_selected_process_ip(self) -> None:
        client = FakeADBClient(
            [
                process_screen_dump(),
                target_dump(ip_address="88.55.xxx.xxx"),
            ]
        )

        result = controller(client).open_completed_target(process_id="1992580")

        self.assertEqual(result.status, ProcessTargetStatus.OPENED_TARGET)
        assert result.target is not None
        self.assertEqual(result.target.ip_address, "88.55.27.70")
        self.assertEqual(result.target.displayed_ip_address, "88.55.xxx.xxx")

    def test_reports_verified_return_to_home_without_retrying(self) -> None:
        home = UIHierarchyDump(
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
                )
            ),
        )
        client = FakeADBClient([process_screen_dump(), home])

        result = controller(client).open_completed_target(process_id="1992580")

        self.assertEqual(result.status, ProcessTargetStatus.RETURNED_HOME)
        self.assertIsNone(result.target)
        self.assertEqual(len(client.taps), 1)

    def test_rejects_target_ip_mismatch_after_single_hack(self) -> None:
        client = FakeADBClient(
            [process_screen_dump(), target_dump(ip_address="88.205.81.140")]
        )

        with self.assertRaisesRegex(ProcessTargetActionError, "does not match"):
            controller(client).open_completed_target(process_id="1992580")

        self.assertEqual(len(client.taps), 1)

    def test_rejects_non_completed_process_without_tapping(self) -> None:
        client = FakeADBClient([process_screen_dump(state="RUNNING")])

        with self.assertRaisesRegex(ProcessTargetActionError, "not COMPLETED"):
            controller(client).open_completed_target(process_id="1992580")

        self.assertEqual(client.taps, [])

    def test_never_retries_hack_when_processes_remains_open(self) -> None:
        screen = process_screen_dump()
        client = FakeADBClient([screen, screen, screen])

        with self.assertRaisesRegex(ProcessTargetActionError, "refusing to retry"):
            controller(client).open_completed_target(process_id="1992580")

        self.assertEqual(len(client.taps), 1)


if __name__ == "__main__":
    unittest.main()
