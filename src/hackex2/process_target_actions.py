"""Verified transition from a completed process card to its target dashboard."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from hackex2.adb.device import ADBClient, ADBError
from hackex2.adb.input import HumanizedInput, TapPlan
from hackex2.config import NavigationSettings
from hackex2.processes import (
    ProcessCard,
    ProcessState,
    locate_process_action,
    parse_process_list,
)
from hackex2.states import ScreenState, detect_screen
from hackex2.target_dashboard import TargetDashboard, parse_target_dashboard


class ProcessTargetActionError(ADBError):
    """Raised when a completed process cannot be opened and verified safely."""


class ProcessTargetStatus(str, Enum):
    OPENED_TARGET = "OPENED_TARGET"
    RETURNED_HOME = "RETURNED_HOME"


@dataclass(frozen=True)
class ProcessTargetResult:
    status: ProcessTargetStatus
    process: ProcessCard
    target: TargetDashboard | None
    tap: TapPlan
    observations: int
    attempts: int = 1


class ProcessTargetController:
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

    def open_completed_target(
        self,
        *,
        process_id: str | None = None,
        ip_address: str | None = None,
        serial: str | None = None,
    ) -> ProcessTargetResult:
        if (process_id is None) == (ip_address is None):
            raise ProcessTargetActionError(
                "provide exactly one of process_id or ip_address"
            )

        selected = self.client.select_device(serial)
        before_dump = self.client.capture_ui_hierarchy(serial=selected.serial)
        state = detect_screen(before_dump.hierarchy).state
        if state is not ScreenState.PROCESSES:
            raise ProcessTargetActionError(
                f"expected PROCESSES, observed {state.value}"
            )
        snapshot = parse_process_list(before_dump.hierarchy)
        candidates = tuple(
            process
            for process in snapshot.visible_processes
            if (process_id is None or process.process_id == process_id)
            and (ip_address is None or process.ip_address == ip_address)
        )
        if len(candidates) != 1:
            selector = process_id or ip_address
            raise ProcessTargetActionError(
                f"expected exactly one visible process matching {selector}, "
                f"found {len(candidates)}"
            )
        process = candidates[0]
        if process.state is not ProcessState.COMPLETED:
            raise ProcessTargetActionError(
                f"process {process.process_id} is {process.state.value}, not COMPLETED"
            )
        if process.ip_address is None:
            raise ProcessTargetActionError(
                f"completed process {process.process_id} has no target IP"
            )
        if "HACK" not in process.available_actions:
            raise ProcessTargetActionError(
                f"completed process {process.process_id} has no HACK action"
            )

        hack_action = locate_process_action(
            before_dump.hierarchy, process.process_id, "HACK"
        )
        tap = self.humanized_input.tap_element(
            self.client, selected.serial, hack_action
        )
        self.event_handler(
            f"ACTION: HACK process {process.process_id} for {process.ip_address} "
            f"once after {tap.delay_ms} ms"
        )

        for observation in range(1, self.settings.max_state_observations + 1):
            self.sleeper(self.settings.state_poll_interval_ms / 1000)
            after_dump = self.client.capture_ui_hierarchy(serial=selected.serial)
            observed = detect_screen(after_dump.hierarchy).state
            if observed is ScreenState.UNKNOWN_SCREEN:
                self.event_handler(
                    "OBSERVED transient UNKNOWN_SCREEN after HACK; "
                    f"waiting without action [{observation}/"
                    f"{self.settings.max_state_observations}]"
                )
                continue
            if observed is ScreenState.TARGET_DASHBOARD:
                target = parse_target_dashboard(
                    after_dump.hierarchy,
                    expected_ip_address=process.ip_address,
                )
                if target.ip_address != process.ip_address:
                    raise ProcessTargetActionError(
                        f"opened target IP {target.ip_address} does not match "
                        f"process IP {process.ip_address}"
                    )
                return ProcessTargetResult(
                    ProcessTargetStatus.OPENED_TARGET,
                    process,
                    target,
                    tap,
                    observation,
                )
            if observed is ScreenState.HOME:
                return ProcessTargetResult(
                    ProcessTargetStatus.RETURNED_HOME,
                    process,
                    None,
                    tap,
                    observation,
                )
            if observed is ScreenState.PROCESSES:
                self.event_handler(
                    "OBSERVED PROCESSES after the single HACK tap; "
                    f"waiting without retry [{observation}/"
                    f"{self.settings.max_state_observations}]"
                )
                continue
            raise ProcessTargetActionError(
                f"HACK produced {observed.value}; refusing to continue"
            )

        raise ProcessTargetActionError(
            "HACK was tapped once but no matching target dashboard appeared; "
            "refusing to retry"
        )
