"""Verified navigation and actions for a connected target Log."""

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
from hackex2.target_log import (
    TargetLogParseError,
    TargetLogSnapshot,
    TargetLogVariant,
    parse_target_log,
)


class TargetLogActionError(ADBError):
    """Raised when a target Log transition cannot be verified safely."""


@dataclass(frozen=True)
class TargetLogTransitionResult:
    source: ScreenState
    destination: ScreenState
    tap: TapPlan
    observations: int
    attempts: int


class TargetLogClearStatus(str, Enum):
    CLEARED = "CLEARED"
    ALREADY_SAVED = "ALREADY_SAVED"
    SKIPPED_LOCKED = "SKIPPED_LOCKED"


@dataclass(frozen=True)
class TargetLogClearResult:
    status: TargetLogClearStatus
    initial_content_length: int
    editor_tap: TapPlan | None
    save_tap: TapPlan | None
    observations: int


@dataclass(frozen=True)
class TargetLogDisconnectResult:
    source: ScreenState
    destination: ScreenState
    tap: TapPlan
    observations: int


class TargetLogController:
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

    def open_from_dashboard(
        self, serial: str | None = None
    ) -> TargetLogTransitionResult:
        selected = self.client.select_device(serial)
        before_dump = self.client.capture_ui_hierarchy(serial=selected.serial)
        source = detect_screen(before_dump.hierarchy).state
        if source is not ScreenState.TARGET_DASHBOARD:
            raise TargetLogActionError(
                f"expected TARGET_DASHBOARD, observed {source.value}"
            )
        parse_target_dashboard(before_dump.hierarchy)
        current_hierarchy = before_dump.hierarchy
        total_attempts = self.settings.max_action_retries + 1

        for attempt in range(1, total_attempts + 1):
            log_action = _single_active_element(current_hierarchy, "LOG")
            tap = self.humanized_input.tap_element(
                self.client, selected.serial, log_action
            )
            self.event_handler(
                f"ACTION: dashboard LOG after {tap.delay_ms} ms "
                f"[attempt {attempt}/{total_attempts}]"
            )
            last_state = source
            for observation in range(1, self.settings.max_state_observations + 1):
                self.sleeper(self.settings.state_poll_interval_ms / 1000)
                after_dump = self.client.capture_ui_hierarchy(serial=selected.serial)
                state = detect_screen(after_dump.hierarchy).state
                last_state = state
                if state is ScreenState.TARGET_LOG:
                    return TargetLogTransitionResult(
                        source, state, tap, observation, attempt
                    )
                if state is ScreenState.UNKNOWN_SCREEN:
                    self.event_handler(
                        "OBSERVED transient or unrecognized screen after LOG; "
                        f"waiting without action [{observation}/"
                        f"{self.settings.max_state_observations}]"
                    )
                    continue
                if state is not source:
                    raise TargetLogActionError(
                        f"opening LOG produced {state.value}; unsafe to retry"
                    )
                current_hierarchy = after_dump.hierarchy

            if last_state is not source:
                raise TargetLogActionError(
                    "LOG transition remained unrecognized; refusing to retry without "
                    "a reconfirmed dashboard"
                )

        raise TargetLogActionError(
            f"dashboard remained open after {total_attempts} LOG attempts"
        )

    def clear_and_save(self, serial: str | None = None) -> TargetLogClearResult:
        selected = self.client.select_device(serial)
        before_dump = self.client.capture_ui_hierarchy(serial=selected.serial)
        _require_target_log(before_dump.hierarchy)
        before = parse_target_log(before_dump.hierarchy)

        if before.variant is TargetLogVariant.LOCKED:
            return TargetLogClearResult(
                TargetLogClearStatus.SKIPPED_LOCKED,
                before.content_length,
                None,
                None,
                0,
            )
        if before.variant is TargetLogVariant.SAVED:
            return TargetLogClearResult(
                TargetLogClearStatus.ALREADY_SAVED,
                0,
                None,
                None,
                0,
            )

        observations = 0
        editor_tap: TapPlan | None = None
        ready = before
        if before.has_content:
            editor_tap = self.humanized_input.tap_element(
                self.client, selected.serial, before.editor
            )
            self.event_handler(
                f"ACTION: focus Log editor after {editor_tap.delay_ms} ms"
            )
            focused = self._wait_for_log(
                selected.serial,
                lambda snapshot: snapshot.editor.focused,
                "Log editor focus",
            )
            observations += focused[1]

            self.client.key_combination(
                selected.serial, "KEYCODE_CTRL_LEFT", "KEYCODE_A"
            )
            self.event_handler("ACTION: select all Log text")
            self.sleeper(self.settings.state_poll_interval_ms / 1000)
            self.client.key_event(selected.serial, "KEYCODE_DEL")
            self.event_handler("ACTION: delete selected Log text")

            emptied = self._wait_for_log(
                selected.serial,
                lambda snapshot: not snapshot.has_content and snapshot.editor.focused,
                "empty focused Log editor",
            )
            ready = emptied[0]
            observations += emptied[1]
            if ready.variant is not TargetLogVariant.EDITABLE:
                raise TargetLogActionError(
                    "Log changed branch after deletion; refusing to save"
                )

            self.client.key_event(selected.serial, "KEYCODE_BACK")
            self.event_handler("ACTION: hide keyboard with Android BACK")
            keyboard_hidden = self._wait_for_log(
                selected.serial,
                lambda snapshot: (
                    not snapshot.has_content
                    and snapshot.save_enabled
                    and _keyboard_is_hidden(snapshot)
                ),
                "empty Log with enabled SAVE and hidden keyboard",
            )
            ready = keyboard_hidden[0]
            observations += keyboard_hidden[1]

        if ready.has_content:
            raise TargetLogActionError("refusing to save a non-empty target Log")
        if not ready.save_action.enabled or not ready.save_action.clickable:
            raise TargetLogActionError("empty Log does not expose an enabled SAVE")

        save_tap = self.humanized_input.tap_element(
            self.client, selected.serial, ready.save_action
        )
        self.event_handler(f"ACTION: SAVE empty Log after {save_tap.delay_ms} ms")
        saved = self._wait_for_log(
            selected.serial,
            lambda snapshot: snapshot.variant is TargetLogVariant.SAVED,
            "saved empty Log",
        )
        observations += saved[1]
        return TargetLogClearResult(
            TargetLogClearStatus.CLEARED,
            before.content_length,
            editor_tap,
            save_tap,
            observations,
        )

    def disconnect(self, serial: str | None = None) -> TargetLogDisconnectResult:
        selected = self.client.select_device(serial)
        before_dump = self.client.capture_ui_hierarchy(serial=selected.serial)
        _require_target_log(before_dump.hierarchy)
        before = parse_target_log(before_dump.hierarchy)
        if before.variant not in {TargetLogVariant.SAVED, TargetLogVariant.LOCKED}:
            raise TargetLogActionError(
                "refusing to disconnect before the Log is saved or confirmed locked"
            )

        tap = self.humanized_input.tap_element(
            self.client, selected.serial, before.disconnect_action
        )
        self.event_handler(
            f"ACTION: DISCONNECT once after {tap.delay_ms} ms from "
            f"{before.variant.value} Log"
        )
        for observation in range(1, self.settings.max_state_observations + 1):
            self.sleeper(self.settings.state_poll_interval_ms / 1000)
            after_dump = self.client.capture_ui_hierarchy(serial=selected.serial)
            state = detect_screen(after_dump.hierarchy).state
            if state is ScreenState.PROCESSES:
                return TargetLogDisconnectResult(
                    ScreenState.TARGET_LOG, state, tap, observation
                )
            if state not in {ScreenState.TARGET_LOG, ScreenState.UNKNOWN_SCREEN}:
                raise TargetLogActionError(
                    f"disconnect produced {state.value}; unsafe to continue"
                )

        raise TargetLogActionError(
            "DISCONNECT was tapped once but PROCESSES was not observed; "
            "refusing to retry"
        )

    def _wait_for_log(
        self,
        serial: str,
        predicate: Callable[[TargetLogSnapshot], bool],
        description: str,
    ) -> tuple[TargetLogSnapshot, int]:
        last: TargetLogSnapshot | None = None
        for observation in range(1, self.settings.max_state_observations + 1):
            self.sleeper(self.settings.state_poll_interval_ms / 1000)
            dump = self.client.capture_ui_hierarchy(serial=serial)
            _require_target_log(dump.hierarchy)
            last = parse_target_log(dump.hierarchy)
            self.event_handler(
                f"OBSERVED LOG: {last.variant.value}, content: "
                f"{'yes' if last.has_content else 'no'}, SAVE: "
                f"{'enabled' if last.save_enabled else 'disabled'} "
                f"[{observation}/{self.settings.max_state_observations}]"
            )
            if predicate(last):
                return last, observation
        last_state = last.variant.value if last is not None else "unavailable"
        raise TargetLogActionError(
            f"expected {description}, last Log state was {last_state}"
        )


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
        raise TargetLogActionError(
            f"expected exactly one active {text} action, found {len(matches)}"
        )
    return matches[0]


def _require_target_log(hierarchy) -> None:
    state = detect_screen(hierarchy).state
    if state is not ScreenState.TARGET_LOG:
        raise TargetLogActionError(f"expected TARGET_LOG, observed {state.value}")


def _keyboard_is_hidden(snapshot: TargetLogSnapshot) -> bool:
    expanded_threshold = snapshot.viewport_bottom - max(
        snapshot.viewport_bottom // 10, 1
    )
    return (
        not snapshot.external_packages
        and snapshot.editor.bounds.bottom >= expanded_threshold
    )
