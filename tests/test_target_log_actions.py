from __future__ import annotations

import random
import unittest

from hackex2.adb.device import ADBDevice
from hackex2.adb.input import HumanizedInput
from hackex2.adb.ui import UIHierarchyDump, parse_ui_hierarchy
from hackex2.config import InputSettings, NavigationSettings
from hackex2.states import ScreenState
from hackex2.target_log_actions import TargetLogController
from hackex2.target_log_actions import TargetLogClearStatus

from tests.test_screen_detector import hierarchy_xml, node
from tests.test_target_dashboard import target_dashboard_xml
from tests.test_target_log import target_log_xml
from tests.test_navigation import processes_dump


def target_log_dump() -> UIHierarchyDump:
    hierarchy = parse_ui_hierarchy(
        hierarchy_xml(
            node(text="// VICTIM LOG"),
            (
                "<node text='some log data' resource-id='' "
                "class='android.widget.EditText' package='net.cncapps.hackex2' "
                "content-desc='' clickable='true' enabled='true' "
                "bounds='[45,455][1035,2200]' />"
            ),
            node(text="SAVE"),
            node(text="DISCONNECT", clickable=True),
        )
    )
    return UIHierarchyDump(serial="R5CY235KPLP", hierarchy=hierarchy)


class FakeADBClient:
    def __init__(self, dumps: list[UIHierarchyDump]) -> None:
        self.dumps = iter(dumps)
        self.taps: list[tuple[str, int, int]] = []
        self.key_events: list[tuple[str, str]] = []
        self.key_combinations: list[tuple[str, tuple[str, ...]]] = []

    def select_device(self, serial: str | None = None) -> ADBDevice:
        return ADBDevice(serial or "R5CY235KPLP", "device")

    def capture_ui_hierarchy(
        self, output_path=None, serial: str | None = None
    ) -> UIHierarchyDump:
        return next(self.dumps)

    def tap(self, serial: str, x: int, y: int) -> None:
        self.taps.append((serial, x, y))

    def key_event(self, serial: str, keycode: str) -> None:
        self.key_events.append((serial, keycode))

    def key_combination(self, serial: str, *keycodes: str) -> None:
        self.key_combinations.append((serial, keycodes))


def log_dump(**kwargs) -> UIHierarchyDump:
    return UIHierarchyDump(
        serial="R5CY235KPLP",
        hierarchy=parse_ui_hierarchy(target_log_xml(**kwargs)),
    )


def controller(client: FakeADBClient) -> TargetLogController:
    return TargetLogController(
        client,
        HumanizedInput(
            InputSettings(0, 0, 0),
            random_source=random.Random(7),
            sleeper=lambda _: None,
        ),
        NavigationSettings(0, 2, 0),
        sleeper=lambda _: None,
    )


class TargetLogControllerTest(unittest.TestCase):
    def test_opens_verified_target_log_from_dashboard(self) -> None:
        dashboard = UIHierarchyDump(
            serial="R5CY235KPLP",
            hierarchy=parse_ui_hierarchy(target_dashboard_xml()),
        )
        client = FakeADBClient([dashboard, target_log_dump()])
        log_controller = controller(client)

        result = log_controller.open_from_dashboard()

        self.assertEqual(result.source, ScreenState.TARGET_DASHBOARD)
        self.assertEqual(result.destination, ScreenState.TARGET_LOG)
        self.assertEqual(len(client.taps), 1)

    def test_clears_saves_and_verifies_log_without_retrying_save(self) -> None:
        client = FakeADBClient(
            [
                log_dump(),
                log_dump(focused=True, keyboard_visible=True),
                log_dump(
                    content="",
                    save_enabled=True,
                    focused=True,
                    keyboard_visible=True,
                ),
                log_dump(content="", save_enabled=True, focused=False),
                log_dump(content="", save_enabled=False, focused=False),
            ]
        )

        result = controller(client).clear_and_save()

        self.assertEqual(result.status, TargetLogClearStatus.CLEARED)
        self.assertEqual(len(client.taps), 2)
        self.assertEqual(
            client.key_combinations,
            [("R5CY235KPLP", ("KEYCODE_CTRL_LEFT", "KEYCODE_A"))],
        )
        self.assertEqual(
            client.key_events,
            [("R5CY235KPLP", "KEYCODE_DEL"), ("R5CY235KPLP", "KEYCODE_BACK")],
        )

    def test_skips_locked_log_without_tapping_or_typing(self) -> None:
        client = FakeADBClient(
            [log_dump(locked=True, editor_enabled=False)]
        )

        result = controller(client).clear_and_save()

        self.assertEqual(result.status, TargetLogClearStatus.SKIPPED_LOCKED)
        self.assertEqual(client.taps, [])
        self.assertEqual(client.key_events, [])

    def test_disconnects_only_from_saved_log_and_verifies_processes(self) -> None:
        client = FakeADBClient([log_dump(content=""), processes_dump()])

        result = controller(client).disconnect()

        self.assertEqual(result.source, ScreenState.TARGET_LOG)
        self.assertEqual(result.destination, ScreenState.PROCESSES)
        self.assertEqual(len(client.taps), 1)


if __name__ == "__main__":
    unittest.main()
