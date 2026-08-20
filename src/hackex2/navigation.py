"""Verified navigation between known HackEx2 screen states."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from hackex2.adb.device import ADBClient, ADBError
from hackex2.adb.input import HumanizedInput, TapPlan
from hackex2.adb.ui import UIElement, UIHierarchy
from hackex2.config import NavigationSettings
from hackex2.states import ScreenState, detect_screen


class NavigationError(ADBError):
    """Raised when a safe state transition cannot be verified."""


@dataclass(frozen=True)
class NavigationResult:
    source: ScreenState
    destination: ScreenState
    tap: TapPlan | None
    observations: int
    attempts: int


_NAVIGATION_RESOURCE_IDS = {
    ScreenState.HOME: "nav-item-dashboard",
    ScreenState.PROCESSES: "nav-item-processes",
}


class Navigator:
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

    def navigate_to(
        self, destination: ScreenState, serial: str | None = None
    ) -> NavigationResult:
        if destination not in _NAVIGATION_RESOURCE_IDS:
            raise NavigationError(f"navigation to {destination.value} is not supported")

        selected = self.client.select_device(serial)
        before = self.client.capture_ui_hierarchy(serial=selected.serial)
        source_detection = detect_screen(before.hierarchy)
        self.event_handler(f"STATE: {source_detection.state.value}")
        if source_detection.state is ScreenState.UNKNOWN_SCREEN:
            raise NavigationError("refusing to navigate from UNKNOWN_SCREEN")
        if source_detection.state is destination:
            return NavigationResult(
                source=source_detection.state,
                destination=destination,
                tap=None,
                observations=0,
                attempts=0,
            )

        resource_id = _NAVIGATION_RESOURCE_IDS[destination]
        current_hierarchy = before.hierarchy
        last_observed = source_detection.state
        last_tap: TapPlan | None = None
        total_attempts = self.settings.max_action_retries + 1
        for attempt in range(1, total_attempts + 1):
            safe_target = _find_safe_target(current_hierarchy, resource_id)
            last_tap = self.humanized_input.tap_element(
                self.client, selected.serial, safe_target
            )
            self.event_handler(
                f"ACTION: tap {resource_id} at ({last_tap.x}, {last_tap.y}) "
                f"after {last_tap.delay_ms} ms [attempt {attempt}/{total_attempts}]"
            )

            for observation in range(1, self.settings.max_state_observations + 1):
                self.sleeper(self.settings.state_poll_interval_ms / 1000)
                after = self.client.capture_ui_hierarchy(serial=selected.serial)
                after_detection = detect_screen(after.hierarchy)
                last_observed = after_detection.state
                current_hierarchy = after.hierarchy
                self.event_handler(
                    f"OBSERVED: {last_observed.value} "
                    f"[{observation}/{self.settings.max_state_observations}]"
                )
                if after_detection.state is destination:
                    return NavigationResult(
                        source=source_detection.state,
                        destination=destination,
                        tap=last_tap,
                        observations=observation,
                        attempts=attempt,
                    )
                if after_detection.state is ScreenState.UNKNOWN_SCREEN:
                    raise NavigationError(
                        f"expected {destination.value}, observed UNKNOWN_SCREEN; "
                        "unsafe to retry"
                    )

            if last_observed is not source_detection.state:
                raise NavigationError(
                    f"expected {destination.value}, observed {last_observed.value}; "
                    "unsafe to retry"
                )
            if attempt < total_attempts:
                self.event_handler(
                    f"RECOVERY: state remains {source_detection.state.value}; "
                    "retrying the safe navigation action"
                )

        tap_detail = (
            f"last tap ({last_tap.x}, {last_tap.y}) after {last_tap.delay_ms} ms"
            if last_tap is not None
            else "no tap sent"
        )
        raise NavigationError(
            f"expected {destination.value} after {total_attempts} attempts, "
            f"last observed {last_observed.value}; {tap_detail}"
        )


def _find_safe_target(hierarchy: UIHierarchy, resource_id: str) -> UIElement:
    targets = hierarchy.find_all(resource_id=resource_id)
    safe_targets = tuple(
        element for element in targets if element.clickable and element.enabled
    )
    if len(safe_targets) != 1:
        raise NavigationError(
            f"expected exactly one safe {resource_id!r} target, "
            f"found {len(safe_targets)}"
        )
    return safe_targets[0]
