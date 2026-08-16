"""Verified selection of identifiable HackEx2 process filters."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from hackex2.adb.device import ADBClient, ADBError
from hackex2.adb.input import HumanizedInput, TapPlan
from hackex2.config import NavigationSettings
from hackex2.processes import (
    ProcessFilter,
    infer_selected_process_filter,
    locate_process_filter_tabs,
    parse_process_list,
)
from hackex2.states import ScreenState, detect_screen


class ProcessFilterError(ADBError):
    """Raised when a process filter selection cannot be verified safely."""


@dataclass(frozen=True)
class ProcessFilterResult:
    source: ProcessFilter
    destination: ProcessFilter
    tap: TapPlan | None
    observations: int
    attempts: int


class ProcessFilterController:
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

    def select(
        self, destination: ProcessFilter, serial: str | None = None
    ) -> ProcessFilterResult:
        if destination not in {
            ProcessFilter.SHIELD,
            ProcessFilter.LOCK,
            ProcessFilter.ANTIVIRUS,
        }:
            raise ProcessFilterError(
                f"verified selection of {destination.value} is not supported"
            )

        selected_device = self.client.select_device(serial)
        before = self.client.capture_ui_hierarchy(serial=selected_device.serial)
        _require_processes_screen(before.hierarchy)
        source = infer_selected_process_filter(parse_process_list(before.hierarchy))
        self.event_handler(f"PROCESS FILTER: {source.value}")
        if source is destination:
            return ProcessFilterResult(source, destination, None, 0, 0)

        current_hierarchy = before.hierarchy
        total_attempts = self.settings.max_action_retries + 1
        last_filter = source
        last_tap: TapPlan | None = None
        for attempt in range(1, total_attempts + 1):
            tabs = locate_process_filter_tabs(current_hierarchy)
            last_tap = self.humanized_input.tap_element(
                self.client,
                selected_device.serial,
                tabs.element_for(destination),
            )
            self.event_handler(
                f"ACTION: tap {destination.value} filter at "
                f"({last_tap.x}, {last_tap.y}) after {last_tap.delay_ms} ms "
                f"[attempt {attempt}/{total_attempts}]"
            )

            for observation in range(1, self.settings.max_state_observations + 1):
                self.sleeper(self.settings.state_poll_interval_ms / 1000)
                after = self.client.capture_ui_hierarchy(serial=selected_device.serial)
                _require_processes_screen(after.hierarchy)
                last_filter = infer_selected_process_filter(
                    parse_process_list(after.hierarchy)
                )
                current_hierarchy = after.hierarchy
                self.event_handler(
                    f"OBSERVED PROCESS FILTER: {last_filter.value} "
                    f"[{observation}/{self.settings.max_state_observations}]"
                )
                if last_filter is destination:
                    return ProcessFilterResult(
                        source,
                        destination,
                        last_tap,
                        observation,
                        attempt,
                    )
                if last_filter not in {source, ProcessFilter.UNKNOWN}:
                    raise ProcessFilterError(
                        f"expected {destination.value}, observed {last_filter.value}; "
                        "unsafe to retry"
                    )

            if last_filter is ProcessFilter.UNKNOWN:
                raise ProcessFilterError(
                    f"expected {destination.value}, observed an empty or ambiguous filter; "
                    "unsafe to retry"
                )
            if attempt < total_attempts:
                self.event_handler(
                    f"RECOVERY: filter remains {source.value}; retrying safe selection"
                )

        raise ProcessFilterError(
            f"expected {destination.value} after {total_attempts} attempts, "
            f"last observed {last_filter.value}"
        )


def _require_processes_screen(hierarchy) -> None:
    observed = detect_screen(hierarchy).state
    if observed is not ScreenState.PROCESSES:
        raise ProcessFilterError(
            f"expected PROCESSES while selecting filter, observed {observed.value}"
        )

