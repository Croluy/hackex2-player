"""Bounded, signature-verified traversal of the current process list."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from hackex2.adb.device import ADBClient, ADBError
from hackex2.adb.input import HumanizedInput, SwipePlan
from hackex2.config import NavigationSettings
from hackex2.processes import (
    ProcessFilter,
    ProcessListSnapshot,
    infer_selected_process_filter,
    locate_process_scroll_region,
    parse_process_list,
)
from hackex2.states import ScreenState, detect_screen


class ScrollDirection(str, Enum):
    UP = "UP"
    DOWN = "DOWN"


class ProcessScrollError(ADBError):
    """Raised when a process-list scroll cannot be verified safely."""


@dataclass(frozen=True)
class ProcessScrollResult:
    direction: ScrollDirection
    filter: ProcessFilter
    before_visible_ids: tuple[str, ...]
    after_visible_ids: tuple[str, ...]
    swipe: SwipePlan | None
    reached_boundary: bool
    attempts: int


class ProcessScroller:
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

    def scroll_once(
        self, direction: ScrollDirection, serial: str | None = None
    ) -> ProcessScrollResult:
        selected = self.client.select_device(serial)
        before_dump = self.client.capture_ui_hierarchy(serial=selected.serial)
        _require_processes(before_dump.hierarchy)
        before = parse_process_list(before_dump.hierarchy)
        selected_filter = infer_selected_process_filter(before)
        if selected_filter is ProcessFilter.UNKNOWN:
            raise ProcessScrollError("cannot scroll an empty or ambiguous process filter")
        before_ids = _visible_ids(before)
        if _at_boundary(before, direction):
            return ProcessScrollResult(
                direction,
                selected_filter,
                before_ids,
                before_ids,
                None,
                True,
                0,
            )

        current_hierarchy = before_dump.hierarchy
        total_attempts = self.settings.max_action_retries + 1
        for attempt in range(1, total_attempts + 1):
            region = locate_process_scroll_region(current_hierarchy)
            swipe = self.humanized_input.swipe_vertical(
                self.client,
                selected.serial,
                region.bounds,
                upward=direction is ScrollDirection.UP,
            )
            self.event_handler(
                f"ACTION: swipe {direction.value} from "
                f"({swipe.start_x}, {swipe.start_y}) to "
                f"({swipe.end_x}, {swipe.end_y}) over {swipe.duration_ms} ms "
                f"after {swipe.delay_ms} ms [attempt {attempt}/{total_attempts}]"
            )

            for observation in range(1, self.settings.max_state_observations + 1):
                self.sleeper(self.settings.state_poll_interval_ms / 1000)
                after_dump = self.client.capture_ui_hierarchy(serial=selected.serial)
                _require_processes(after_dump.hierarchy)
                after = parse_process_list(after_dump.hierarchy)
                after_filter = infer_selected_process_filter(after)
                if after_filter is not selected_filter:
                    raise ProcessScrollError(
                        f"process filter changed from {selected_filter.value} to "
                        f"{after_filter.value}; unsafe to continue"
                    )
                after_ids = _visible_ids(after)
                current_hierarchy = after_dump.hierarchy
                self.event_handler(
                    f"OBSERVED VISIBLE PROCESSES: {', '.join(after_ids) or 'none'} "
                    f"[{observation}/{self.settings.max_state_observations}]"
                )
                if _visible_signature(after) != _visible_signature(before):
                    return ProcessScrollResult(
                        direction,
                        selected_filter,
                        before_ids,
                        after_ids,
                        swipe,
                        _at_boundary(after, direction),
                        attempt,
                    )

            if attempt < total_attempts:
                self.event_handler("RECOVERY: process signature unchanged; retrying swipe")

        raise ProcessScrollError(
            f"process signature did not change after {total_attempts} swipe attempts"
        )


def _require_processes(hierarchy) -> None:
    state = detect_screen(hierarchy).state
    if state is not ScreenState.PROCESSES:
        raise ProcessScrollError(f"expected PROCESSES, observed {state.value}")


def _visible_ids(snapshot: ProcessListSnapshot) -> tuple[str, ...]:
    return tuple(process.process_id for process in snapshot.visible_processes)


def _visible_signature(snapshot: ProcessListSnapshot):
    return tuple(
        (process.process_id, process.bounds.top, process.bounds.bottom)
        for process in snapshot.visible_processes
    )


def _at_boundary(snapshot: ProcessListSnapshot, direction: ScrollDirection) -> bool:
    if not snapshot.processes:
        return True
    boundary_process = (
        snapshot.processes[-1]
        if direction is ScrollDirection.UP
        else snapshot.processes[0]
    )
    return boundary_process.visible

