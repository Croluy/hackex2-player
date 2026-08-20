from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from hackex2.adb.device import ADBDevice
from hackex2.adb.ui import UIHierarchyDump, parse_ui_hierarchy
from hackex2.database import TargetDatabase, TargetEventType
from hackex2.states import ScreenState
from hackex2.target_log_actions import TargetLogClearStatus
from hackex2.target_wallet_actions import (
    WalletPasswordCrackStatus,
    WalletTransferStatus,
)
from hackex2.target_workflow import TargetWorkflow, TargetWorkflowError

from tests.test_target_dashboard import target_dashboard_xml
from tests.test_target_wallet import (
    authenticated_wallet_xml,
    wallet_login_xml,
    wallet_password_required_xml,
)


class FakeADBClient:
    def __init__(self, dumps: list[UIHierarchyDump]) -> None:
        self.dumps = iter(dumps)

    def select_device(self, serial: str | None = None) -> ADBDevice:
        return ADBDevice(serial or "R5CY235KPLP", "device")

    def capture_ui_hierarchy(
        self, output_path=None, serial: str | None = None
    ) -> UIHierarchyDump:
        return next(self.dumps)


def dump(xml: str) -> UIHierarchyDump:
    return UIHierarchyDump(
        serial="R5CY235KPLP", hierarchy=parse_ui_hierarchy(xml)
    )


class FakeWalletController:
    def __init__(self, destination: ScreenState) -> None:
        self.destination = destination
        self.calls: list[str] = []

    def open_from_dashboard(self, serial=None, *, expected_ip_address=None):
        self.calls.append(f"open:{expected_ip_address}")
        return SimpleNamespace(destination=self.destination)

    def login(self, serial=None):
        self.calls.append("login")

    def transfer_available_crypto(self, serial=None):
        self.calls.append("transfer")
        return SimpleNamespace(
            status=WalletTransferStatus.TRANSFERRED,
            transferred_crypto=174,
        )

    def start_password_crack(self, serial=None):
        self.calls.append("crack")
        return SimpleNamespace(status=WalletPasswordCrackStatus.SCREEN_UNCHANGED)

    def return_to_dashboard(self, serial=None):
        self.calls.append("back")


class FakeLogController:
    def __init__(self, status: TargetLogClearStatus) -> None:
        self.status = status
        self.calls: list[str] = []

    def open_from_dashboard(self, serial=None, *, expected_ip_address=None):
        self.calls.append(f"open:{expected_ip_address}")

    def clear_and_save(self, serial=None):
        self.calls.append("clear")
        return SimpleNamespace(status=self.status)

    def disconnect(self, serial=None):
        self.calls.append("disconnect")
        return SimpleNamespace(destination=ScreenState.PROCESSES)


class TargetWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = TargetDatabase(
            Path(self.temporary.name, "workflow.sqlite3")
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_services_login_transfer_log_and_disconnect(self) -> None:
        client = FakeADBClient(
            [
                dump(target_dashboard_xml(ip_address="88.55.27.70")),
                dump(wallet_login_xml(login_username="nebthepleb")),
                dump(authenticated_wallet_xml()),
            ]
        )
        wallet = FakeWalletController(ScreenState.TARGET_WALLET_LOGIN)
        log = FakeLogController(TargetLogClearStatus.CLEARED)
        workflow = TargetWorkflow(client, wallet, log, self.database)

        result = workflow.service_current_target()

        self.assertEqual(result.wallet_status, WalletTransferStatus.TRANSFERRED.value)
        self.assertEqual(result.transferred_crypto, 174)
        self.assertEqual(result.log_status, TargetLogClearStatus.CLEARED)
        self.assertTrue(result.disconnected)
        target = self.database.get_target("88.55.27.70")
        assert target is not None
        self.assertEqual(target.total_crypto_transferred, 174)
        events = tuple(
            event.event_type for event in self.database.list_history(target.ip_address)
        )
        self.assertIn(TargetEventType.LOG_CLEARED, events)
        self.assertEqual(events[-1], TargetEventType.DISCONNECTED)
        self.assertEqual(wallet.calls, ["open:88.55.27.70", "login", "transfer", "back"])
        self.assertEqual(log.calls, ["open:88.55.27.70", "clear", "disconnect"])

    def test_queues_password_crack_then_clears_locked_log_and_disconnects(self) -> None:
        client = FakeADBClient(
            [
                dump(target_dashboard_xml(ip_address="85.83.90.194")),
                dump(wallet_password_required_xml()),
            ]
        )
        wallet = FakeWalletController(
            ScreenState.TARGET_WALLET_PASSWORD_REQUIRED
        )
        log = FakeLogController(TargetLogClearStatus.SKIPPED_LOCKED)
        workflow = TargetWorkflow(client, wallet, log, self.database)

        result = workflow.service_current_target()

        self.assertEqual(
            result.wallet_status,
            "PASSWORD_CRACK_SCREEN_UNCHANGED",
        )
        self.assertEqual(result.transferred_crypto, 0)
        self.assertEqual(result.log_status, TargetLogClearStatus.SKIPPED_LOCKED)
        self.assertEqual(wallet.calls, ["open:85.83.90.194", "crack", "back"])
        target = self.database.get_target("85.83.90.194")
        assert target is not None
        self.assertFalse(target.wallet_password_known)
        self.assertTrue(target.log_protected)

    def test_stores_masked_target_but_stops_before_wallet_without_expected_ip(self) -> None:
        client = FakeADBClient(
            [dump(target_dashboard_xml(ip_address="85.83.xxx.xxx"))]
        )
        wallet = FakeWalletController(ScreenState.TARGET_WALLET_LOGIN)
        log = FakeLogController(TargetLogClearStatus.CLEARED)
        workflow = TargetWorkflow(client, wallet, log, self.database)

        with self.assertRaisesRegex(TargetWorkflowError, "address is masked"):
            workflow.service_current_target()

        target = self.database.get_target_by_identity(
            "masked:85.83.*.*|username:nebthepleb"
        )
        self.assertIsNotNone(target)
        self.assertEqual(wallet.calls, [])
        self.assertEqual(log.calls, [])


if __name__ == "__main__":
    unittest.main()
