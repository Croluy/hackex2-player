"""Verified actions for authenticated target-wallet branches."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from hackex2.adb.device import ADBClient, ADBError
from hackex2.adb.input import HumanizedInput, TapPlan
from hackex2.config import NavigationSettings
from hackex2.states import ScreenState, detect_screen
from hackex2.target_dashboard import parse_target_dashboard
from hackex2.target_wallet import (
    TargetWalletAuthenticatedSnapshot,
    TargetWalletParseError,
    TargetWalletVariant,
    parse_target_wallet_authenticated,
    parse_target_wallet_login,
    parse_wallet_transfer_confirmation,
)


class TargetWalletActionError(ADBError):
    """Raised when a Wallet action cannot be verified safely."""


class WalletTransferStatus(str, Enum):
    TRANSFERRED = "TRANSFERRED"
    SKIPPED_PROTECTED = "SKIPPED_PROTECTED"
    SKIPPED_THRESHOLD = "SKIPPED_THRESHOLD"


@dataclass(frozen=True)
class WalletTransferResult:
    status: WalletTransferStatus
    initial_balance: int
    transferred_crypto: int
    final_balance: int | None
    max_tap: TapPlan | None
    transfer_tap: TapPlan | None
    observations: int


@dataclass(frozen=True)
class WalletBackResult:
    source: ScreenState
    destination: ScreenState
    tap: TapPlan
    observations: int
    attempts: int


@dataclass(frozen=True)
class WalletTransitionResult:
    source: ScreenState
    destination: ScreenState
    tap: TapPlan
    observations: int
    attempts: int


class TargetWalletController:
    def __init__(
        self,
        client: ADBClient,
        humanized_input: HumanizedInput,
        settings: NavigationSettings,
        *,
        sleeper: Callable[[float], None] = time.sleep,
        event_handler: Callable[[str], None] = lambda _: None,
    ) -> None:
        settings.validate()
        self.client = client
        self.humanized_input = humanized_input
        self.settings = settings
        self.sleeper = sleeper
        self.event_handler = event_handler

    def transfer_available_crypto(
        self, serial: str | None = None
    ) -> WalletTransferResult:
        selected = self.client.select_device(serial)
        before_dump = self.client.capture_ui_hierarchy(serial=selected.serial)
        _require_authenticated_wallet(before_dump.hierarchy)
        before = parse_target_wallet_authenticated(before_dump.hierarchy)

        if before.variant is TargetWalletVariant.PROTECTED:
            return WalletTransferResult(
                WalletTransferStatus.SKIPPED_PROTECTED,
                before.hot_wallet_crypto,
                0,
                before.hot_wallet_crypto,
                None,
                None,
                0,
            )
        if before.hot_wallet_crypto <= 1:
            return WalletTransferResult(
                WalletTransferStatus.SKIPPED_THRESHOLD,
                before.hot_wallet_crypto,
                0,
                before.hot_wallet_crypto,
                None,
                None,
                0,
            )
        if before.max_action is None:
            raise TargetWalletActionError("verified transferable Wallet has no MAX action")

        max_tap = self.humanized_input.tap_element(
            self.client, selected.serial, before.max_action
        )
        self.event_handler(
            f"ACTION: MAX after {max_tap.delay_ms} ms for "
            f"{before.hot_wallet_crypto} Crypto"
        )

        observations = 0
        ready: TargetWalletAuthenticatedSnapshot | None = None
        for observation in range(1, self.settings.max_state_observations + 1):
            observations += 1
            self.sleeper(self.settings.state_poll_interval_ms / 1000)
            ready_dump = self.client.capture_ui_hierarchy(serial=selected.serial)
            _require_authenticated_wallet(ready_dump.hierarchy)
            candidate = parse_target_wallet_authenticated(ready_dump.hierarchy)
            _require_same_wallet(before, candidate)
            if candidate.variant is not TargetWalletVariant.TRANSFERABLE:
                raise TargetWalletActionError(
                    "Wallet branch changed after MAX; refusing to transfer"
                )
            transfer_ready = (
                candidate.transfer_action is not None
                and candidate.transfer_action.enabled
                and candidate.transfer_action.clickable
            )
            self.event_handler(
                f"OBSERVED WALLET AMOUNT: {candidate.transfer_amount} | "
                f"transfer ready: {'yes' if transfer_ready else 'no'} "
                f"[{observation}/{self.settings.max_state_observations}]"
            )
            exact_amount = candidate.transfer_amount == before.hot_wallet_crypto
            accessibility_transition = (
                before.transfer_amount is None
                and candidate.transfer_amount is None
                and not _is_active(before.transfer_action)
                and transfer_ready
            )
            if (exact_amount or accessibility_transition) and transfer_ready:
                ready = candidate
                break

        if ready is None or ready.transfer_action is None:
            raise TargetWalletActionError(
                "MAX did not produce the exact balance or a verified disabled-to-enabled "
                "transfer transition"
            )

        transfer_tap = self.humanized_input.tap_element(
            self.client, selected.serial, ready.transfer_action
        )
        self.event_handler(
            "ACTION: TRANSFER TO MY WALLET once after "
            f"{transfer_tap.delay_ms} ms"
        )

        for observation in range(1, self.settings.max_state_observations + 1):
            observations += 1
            self.sleeper(self.settings.state_poll_interval_ms / 1000)
            result_dump = self.client.capture_ui_hierarchy(serial=selected.serial)
            confirmation = parse_wallet_transfer_confirmation(result_dump.hierarchy)
            if confirmation is not None:
                if confirmation != before.hot_wallet_crypto:
                    raise TargetWalletActionError(
                        f"confirmed transfer amount {confirmation} does not match "
                        f"initial balance {before.hot_wallet_crypto}"
                    )
                return WalletTransferResult(
                    WalletTransferStatus.TRANSFERRED,
                    before.hot_wallet_crypto,
                    confirmation,
                    None,
                    max_tap,
                    transfer_tap,
                    observations,
                )

            observed = detect_screen(result_dump.hierarchy).state
            if observed is ScreenState.TARGET_WALLET_AUTHENTICATED:
                after = parse_target_wallet_authenticated(result_dump.hierarchy)
                _require_same_wallet(before, after)
                if after.hot_wallet_crypto == 0:
                    return WalletTransferResult(
                        WalletTransferStatus.TRANSFERRED,
                        before.hot_wallet_crypto,
                        before.hot_wallet_crypto,
                        0,
                        max_tap,
                        transfer_tap,
                        observations,
                    )

        raise TargetWalletActionError(
            "transfer was tapped once but no matching confirmation or zero balance "
            "was observed; refusing to retry"
        )

    def open_from_dashboard(
        self, serial: str | None = None
    ) -> WalletTransitionResult:
        selected = self.client.select_device(serial)
        before_dump = self.client.capture_ui_hierarchy(serial=selected.serial)
        source = detect_screen(before_dump.hierarchy).state
        if source is not ScreenState.TARGET_DASHBOARD:
            raise TargetWalletActionError(
                f"expected TARGET_DASHBOARD, observed {source.value}"
            )
        parse_target_dashboard(before_dump.hierarchy)
        current_hierarchy = before_dump.hierarchy
        total_attempts = self.settings.max_action_retries + 1

        for attempt in range(1, total_attempts + 1):
            wallet_action = _single_active_element(current_hierarchy, "WALLET")
            tap = self.humanized_input.tap_element(
                self.client, selected.serial, wallet_action
            )
            self.event_handler(
                f"ACTION: dashboard WALLET after {tap.delay_ms} ms "
                f"[attempt {attempt}/{total_attempts}]"
            )
            for observation in range(1, self.settings.max_state_observations + 1):
                self.sleeper(self.settings.state_poll_interval_ms / 1000)
                after_dump = self.client.capture_ui_hierarchy(serial=selected.serial)
                state = detect_screen(after_dump.hierarchy).state
                if state in {
                    ScreenState.TARGET_WALLET_LOGIN,
                    ScreenState.TARGET_WALLET_AUTHENTICATED,
                }:
                    return WalletTransitionResult(
                        source, state, tap, observation, attempt
                    )
                if state is not source:
                    raise TargetWalletActionError(
                        f"opening Wallet produced {state.value}; unsafe to retry"
                    )
                current_hierarchy = after_dump.hierarchy

        raise TargetWalletActionError(
            f"dashboard remained open after {total_attempts} WALLET attempts"
        )

    def login(self, serial: str | None = None) -> WalletTransitionResult:
        selected = self.client.select_device(serial)
        before_dump = self.client.capture_ui_hierarchy(serial=selected.serial)
        source = detect_screen(before_dump.hierarchy).state
        if source is not ScreenState.TARGET_WALLET_LOGIN:
            raise TargetWalletActionError(
                f"expected TARGET_WALLET_LOGIN, observed {source.value}"
            )
        parse_target_wallet_login(before_dump.hierarchy)
        login_action = _single_active_element(before_dump.hierarchy, "LOGIN >")
        tap = self.humanized_input.tap_element(
            self.client, selected.serial, login_action
        )
        self.event_handler(f"ACTION: wallet LOGIN once after {tap.delay_ms} ms")

        for observation in range(1, self.settings.max_state_observations + 1):
            self.sleeper(self.settings.state_poll_interval_ms / 1000)
            after_dump = self.client.capture_ui_hierarchy(serial=selected.serial)
            state = detect_screen(after_dump.hierarchy).state
            if state is ScreenState.TARGET_WALLET_AUTHENTICATED:
                parse_target_wallet_authenticated(after_dump.hierarchy)
                return WalletTransitionResult(source, state, tap, observation, 1)
            if state is not source:
                raise TargetWalletActionError(
                    f"wallet Login produced {state.value}; unsafe to continue"
                )

        raise TargetWalletActionError(
            "Wallet remained on Login after one submission; refusing to retry"
        )

    def return_to_dashboard(self, serial: str | None = None) -> WalletBackResult:
        selected = self.client.select_device(serial)
        before_dump = self.client.capture_ui_hierarchy(serial=selected.serial)
        source = detect_screen(before_dump.hierarchy).state
        if source is not ScreenState.TARGET_WALLET_AUTHENTICATED:
            raise TargetWalletActionError(
                f"expected TARGET_WALLET_AUTHENTICATED, observed {source.value}"
            )
        wallet = parse_target_wallet_authenticated(before_dump.hierarchy)
        current_hierarchy = before_dump.hierarchy
        total_attempts = self.settings.max_action_retries + 1

        for attempt in range(1, total_attempts + 1):
            if attempt > 1:
                wallet = parse_target_wallet_authenticated(current_hierarchy)
            tap = self.humanized_input.tap_element(
                self.client, selected.serial, wallet.back_action
            )
            self.event_handler(
                f"ACTION: wallet BACK after {tap.delay_ms} ms "
                f"[attempt {attempt}/{total_attempts}]"
            )
            last_state = source
            for observation in range(1, self.settings.max_state_observations + 1):
                self.sleeper(self.settings.state_poll_interval_ms / 1000)
                after_dump = self.client.capture_ui_hierarchy(serial=selected.serial)
                state = detect_screen(after_dump.hierarchy).state
                last_state = state
                if state is ScreenState.TARGET_DASHBOARD:
                    return WalletBackResult(
                        source,
                        ScreenState.TARGET_DASHBOARD,
                        tap,
                        observation,
                        attempt,
                    )
                if state is ScreenState.UNKNOWN_SCREEN:
                    self.event_handler(
                        "OBSERVED transient UNKNOWN_SCREEN after BACK; "
                        f"waiting without action [{observation}/"
                        f"{self.settings.max_state_observations}]"
                    )
                    continue
                if state is not source:
                    raise TargetWalletActionError(
                        f"expected TARGET_DASHBOARD, observed {state.value}; "
                        "unsafe to retry"
                    )
                current_hierarchy = after_dump.hierarchy

            if last_state is not source:
                raise TargetWalletActionError(
                    "BACK transition remained unresolved; refusing to retry without "
                    "a reconfirmed Wallet source state"
                )

        raise TargetWalletActionError(
            f"wallet remained open after {total_attempts} BACK attempts"
        )


def _require_authenticated_wallet(hierarchy) -> None:
    state = detect_screen(hierarchy).state
    if state is not ScreenState.TARGET_WALLET_AUTHENTICATED:
        raise TargetWalletActionError(
            f"expected TARGET_WALLET_AUTHENTICATED, observed {state.value}"
        )


def _require_same_wallet(
    before: TargetWalletAuthenticatedSnapshot,
    after: TargetWalletAuthenticatedSnapshot,
) -> None:
    if (
        after.owner_username != before.owner_username
        or after.wallet_address != before.wallet_address
    ):
        raise TargetWalletActionError(
            "Wallet identity changed during the action; refusing to continue"
        )


def _is_active(element) -> bool:
    return element is not None and element.enabled and element.clickable


def _single_active_element(hierarchy, text: str):
    matches = tuple(
        element
        for element in hierarchy.find_all(text=text)
        if element.enabled
        and element.clickable
        and element.bounds.width > 0
        and element.bounds.height > 0
    )
    if len(matches) != 1:
        raise TargetWalletActionError(
            f"expected exactly one active {text} action, found {len(matches)}"
        )
    return matches[0]
