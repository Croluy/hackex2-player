from __future__ import annotations

import random
import unittest

from hackex2.adb.device import ADBDevice
from hackex2.adb.input import HumanizedInput
from hackex2.adb.ui import UIHierarchyDump, parse_ui_hierarchy
from hackex2.config import InputSettings, NavigationSettings
from hackex2.states import ScreenState
from hackex2.target_wallet_actions import (
    TargetWalletActionError,
    TargetWalletController,
    WalletTransferStatus,
)

from tests.test_target_dashboard import target_dashboard_xml
from tests.test_screen_detector import hierarchy_xml, node
from tests.test_target_wallet import authenticated_wallet_xml, wallet_login_xml


def wallet_dump(**kwargs) -> UIHierarchyDump:
    return UIHierarchyDump(
        serial="R5CY235KPLP",
        hierarchy=parse_ui_hierarchy(authenticated_wallet_xml(**kwargs)),
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


def controller(client: FakeADBClient, observations: int = 2) -> TargetWalletController:
    return TargetWalletController(
        client,
        HumanizedInput(
            InputSettings(0, 0, 0),
            random_source=random.Random(4),
            sleeper=lambda _: None,
        ),
        NavigationSettings(0, observations, 0),
        sleeper=lambda _: None,
    )


class TargetWalletControllerTest(unittest.TestCase):
    def test_transfers_exact_max_amount_once_after_intermediate_verification(self) -> None:
        client = FakeADBClient(
            [
                wallet_dump(),
                wallet_dump(amount="201", transfer_enabled=True),
                wallet_dump(
                    amount="201",
                    transfer_enabled=True,
                    confirmation="[OK] Transferred 201 Crypto to your wallet.",
                ),
            ]
        )

        result = controller(client).transfer_available_crypto()

        self.assertEqual(result.status, WalletTransferStatus.TRANSFERRED)
        self.assertEqual(result.initial_balance, 201)
        self.assertEqual(result.transferred_crypto, 201)
        self.assertIsNone(result.final_balance)
        self.assertEqual(len(client.taps), 2)

    def test_accepts_accessibility_state_transition_when_amount_is_naf(self) -> None:
        client = FakeADBClient(
            [
                wallet_dump(),
                wallet_dump(transfer_enabled=True),
                wallet_dump(
                    transfer_enabled=True,
                    confirmation="[OK] Transferred 201 Crypto to your wallet.",
                ),
            ]
        )

        result = controller(client).transfer_available_crypto()

        self.assertEqual(result.status, WalletTransferStatus.TRANSFERRED)
        self.assertEqual(len(client.taps), 2)

    def test_skips_protected_wallet_without_tapping(self) -> None:
        client = FakeADBClient([wallet_dump(protected=True)])

        result = controller(client).transfer_available_crypto()

        self.assertEqual(result.status, WalletTransferStatus.SKIPPED_PROTECTED)
        self.assertEqual(client.taps, [])

    def test_skips_balance_at_or_below_threshold_without_tapping(self) -> None:
        client = FakeADBClient([wallet_dump(hot_balance=1)])

        result = controller(client).transfer_available_crypto()

        self.assertEqual(result.status, WalletTransferStatus.SKIPPED_THRESHOLD)
        self.assertEqual(result.initial_balance, 1)
        self.assertEqual(client.taps, [])

    def test_never_retries_transfer_when_confirmation_is_missing(self) -> None:
        unchanged = wallet_dump(amount="201", transfer_enabled=True)
        client = FakeADBClient([wallet_dump(), unchanged, unchanged, unchanged])

        with self.assertRaisesRegex(TargetWalletActionError, "refusing to retry"):
            controller(client).transfer_available_crypto()

        self.assertEqual(len(client.taps), 2)

    def test_returns_to_verified_target_dashboard(self) -> None:
        dashboard = UIHierarchyDump(
            serial="R5CY235KPLP",
            hierarchy=parse_ui_hierarchy(target_dashboard_xml()),
        )
        client = FakeADBClient([wallet_dump(), dashboard])

        result = controller(client).return_to_dashboard()

        self.assertEqual(result.source, ScreenState.TARGET_WALLET_AUTHENTICATED)
        self.assertEqual(result.destination, ScreenState.TARGET_DASHBOARD)
        self.assertEqual(len(client.taps), 1)

    def test_returns_from_confirmed_post_transfer_wallet(self) -> None:
        transferred = wallet_dump(
            hot_balance=0,
            form_enabled=False,
            confirmation="[OK] Transferred 215 Crypto to your wallet.",
        )
        dashboard = UIHierarchyDump(
            serial="R5CY235KPLP",
            hierarchy=parse_ui_hierarchy(target_dashboard_xml()),
        )
        client = FakeADBClient([transferred, dashboard])

        result = controller(client).return_to_dashboard()

        self.assertEqual(result.destination, ScreenState.TARGET_DASHBOARD)
        self.assertEqual(len(client.taps), 1)

    def test_waits_through_unknown_after_back_without_extra_tap(self) -> None:
        unknown = UIHierarchyDump(
            serial="R5CY235KPLP",
            hierarchy=parse_ui_hierarchy(
                hierarchy_xml(node(text="Loading apps..."))
            ),
        )
        dashboard = UIHierarchyDump(
            serial="R5CY235KPLP",
            hierarchy=parse_ui_hierarchy(target_dashboard_xml()),
        )
        client = FakeADBClient([wallet_dump(), unknown, dashboard])

        result = controller(client, observations=2).return_to_dashboard()

        self.assertEqual(result.destination, ScreenState.TARGET_DASHBOARD)
        self.assertEqual(len(client.taps), 1)

    def test_opens_login_branch_from_verified_dashboard(self) -> None:
        dashboard = UIHierarchyDump(
            serial="R5CY235KPLP",
            hierarchy=parse_ui_hierarchy(target_dashboard_xml()),
        )
        login = UIHierarchyDump(
            serial="R5CY235KPLP",
            hierarchy=parse_ui_hierarchy(wallet_login_xml()),
        )
        client = FakeADBClient([dashboard, login])

        result = controller(client).open_from_dashboard()

        self.assertEqual(result.source, ScreenState.TARGET_DASHBOARD)
        self.assertEqual(result.destination, ScreenState.TARGET_WALLET_LOGIN)
        self.assertEqual(len(client.taps), 1)

    def test_submits_login_once_and_verifies_authenticated_wallet(self) -> None:
        login = UIHierarchyDump(
            serial="R5CY235KPLP",
            hierarchy=parse_ui_hierarchy(wallet_login_xml()),
        )
        client = FakeADBClient([login, wallet_dump()])

        result = controller(client).login()

        self.assertEqual(result.source, ScreenState.TARGET_WALLET_LOGIN)
        self.assertEqual(
            result.destination, ScreenState.TARGET_WALLET_AUTHENTICATED
        )
        self.assertEqual(len(client.taps), 1)


if __name__ == "__main__":
    unittest.main()
