"""Machine-readable parsing of HackEx2 process cards exposed by the UI."""

from __future__ import annotations

import re
from ipaddress import IPv4Address, AddressValueError
from dataclasses import dataclass
from enum import Enum

from hackex2.adb.ui import Bounds, UIElement, UIHierarchy


class ProcessParseError(ValueError):
    """Raised when visible process information is internally inconsistent."""


class ProcessState(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    IN_PROGRESS = "IN_PROGRESS"
    INVALIDATED = "INVALIDATED"
    PAUSED = "PAUSED"
    UNKNOWN = "UNKNOWN"


class ProcessFilter(str, Enum):
    ALL = "ALL"
    SHIELD = "SHIELD"
    LOCK = "LOCK"
    ANTIVIRUS = "ANTIVIRUS"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ProcessCard:
    process_id: str
    name: str | None
    level: int | None
    state: ProcessState
    progress_percent: int | None
    completion_text: str | None
    ip_address: str | None
    success_chance_percent: int | None
    game_tags: tuple[str, ...]
    system_markers: tuple[str, ...]
    available_actions: tuple[str, ...]
    bounds: Bounds
    viewport_bounds: Bounds | None = None

    @property
    def visible(self) -> bool:
        if self.bounds.width <= 0 or self.bounds.height <= 0:
            return False
        if self.viewport_bounds is None:
            return True
        visible_width = min(self.bounds.right, self.viewport_bounds.right) - max(
            self.bounds.left, self.viewport_bounds.left
        )
        visible_height = min(self.bounds.bottom, self.viewport_bounds.bottom) - max(
            self.bounds.top, self.viewport_bounds.top
        )
        return visible_width > 0 and visible_height > 0


@dataclass(frozen=True)
class ProcessListSnapshot:
    active_task_count: int | None
    processes: tuple[ProcessCard, ...]

    @property
    def visible_processes(self) -> tuple[ProcessCard, ...]:
        return tuple(process for process in self.processes if process.visible)


@dataclass(frozen=True)
class ProcessFilterTabs:
    all: UIElement
    shield: UIElement
    lock: UIElement
    antivirus: UIElement

    def element_for(self, process_filter: ProcessFilter) -> UIElement:
        elements = {
            ProcessFilter.ALL: self.all,
            ProcessFilter.SHIELD: self.shield,
            ProcessFilter.LOCK: self.lock,
            ProcessFilter.ANTIVIRUS: self.antivirus,
        }
        try:
            return elements[process_filter]
        except KeyError as exc:
            raise ProcessParseError(
                f"cannot locate an element for filter {process_filter.value}"
            ) from exc


_PROCESS_ID = re.compile(r"proc-(\d+)")
_LEVEL = re.compile(r"Lv\.(\d+)")
_PROGRESS = re.compile(r"(\d+)%")
_CHANCE = re.compile(r"(\d+)% chance")
_ACTIVE_TASKS = re.compile(r"(\d+) active tasks?")
_GAME_TAG = re.compile(r"[a-z][a-z0-9 _-]{0,40}")
_STATE_LABELS = {
    "SUCCESS": ProcessState.COMPLETED,
    "FAILED": ProcessState.FAILED,
    "RUNNING": ProcessState.IN_PROGRESS,
    "INVALIDATED": ProcessState.INVALIDATED,
    "PAUSED": ProcessState.PAUSED,
}
_SYSTEM_MARKERS = {"TRACED", "BACKDOOR"}


def parse_process_list(hierarchy: UIHierarchy) -> ProcessListSnapshot:
    cards = tuple(
        element
        for element in hierarchy.elements
        if _PROCESS_ID.fullmatch(element.resource_id)
    )
    ids = [element.resource_id for element in cards]
    if len(ids) != len(set(ids)):
        raise ProcessParseError("UI hierarchy contains duplicate process identifiers")

    task_counts = {
        int(match.group(1))
        for element in hierarchy.elements
        if (match := _ACTIVE_TASKS.fullmatch(element.text.strip())) is not None
    }
    if len(task_counts) > 1:
        raise ProcessParseError("UI hierarchy contains conflicting active task counts")
    active_task_count = next(iter(task_counts), None)
    scroll_regions = _process_scroll_candidates(hierarchy)
    viewport = scroll_regions[0].bounds if len(scroll_regions) == 1 else None

    return ProcessListSnapshot(
        active_task_count=active_task_count,
        processes=tuple(
            _parse_process_card(hierarchy, card, viewport) for card in cards
        ),
    )


def locate_process_filter_tabs(hierarchy: UIHierarchy) -> ProcessFilterTabs:
    all_matches = tuple(
        element
        for element in hierarchy.find_all(text="ALL")
        if element.clickable
        and element.enabled
        and element.class_name == "android.widget.Button"
    )
    if len(all_matches) != 1:
        raise ProcessParseError(
            f"expected exactly one clickable ALL filter, found {len(all_matches)}"
        )
    all_filter = all_matches[0]
    row = tuple(
        sorted(
            (
                element
                for element in hierarchy.clickable_elements
                if element.class_name == "android.widget.Button"
                and element.bounds.top == all_filter.bounds.top
                and element.bounds.bottom == all_filter.bounds.bottom
            ),
            key=lambda element: element.bounds.left,
        )
    )
    if len(row) != 8:
        raise ProcessParseError(
            f"expected 8 process filter controls in the ALL row, found {len(row)}"
        )
    if row[1] != all_filter:
        raise ProcessParseError("ALL is not the second process filter control")

    return ProcessFilterTabs(
        all=all_filter,
        shield=row[2],
        lock=row[3],
        antivirus=row[6],
    )


def locate_process_scroll_region(hierarchy: UIHierarchy) -> UIElement:
    candidates = _process_scroll_candidates(hierarchy)
    if len(candidates) != 1:
        raise ProcessParseError(
            f"expected exactly one scrollable process region, found {len(candidates)}"
        )
    return candidates[0]


def _process_scroll_candidates(hierarchy: UIHierarchy) -> tuple[UIElement, ...]:
    return tuple(
        element
        for element in hierarchy.elements
        if element.scrollable
        and element.bounds.width > 0
        and element.bounds.height > 0
        and any(
            _PROCESS_ID.fullmatch(descendant.resource_id)
            for descendant in hierarchy.descendants_of(element)
        )
    )


def infer_selected_process_filter(snapshot: ProcessListSnapshot) -> ProcessFilter:
    names = {process.name for process in snapshot.processes if process.name is not None}
    return {
        frozenset({"Firewall Bypass"}): ProcessFilter.SHIELD,
        frozenset({"Password Crack"}): ProcessFilter.LOCK,
        frozenset({"Antivirus Scan"}): ProcessFilter.ANTIVIRUS,
    }.get(frozenset(names), ProcessFilter.UNKNOWN)


def _parse_process_card(
    hierarchy: UIHierarchy, card: UIElement, viewport: Bounds | None
) -> ProcessCard:
    process_match = _PROCESS_ID.fullmatch(card.resource_id)
    if process_match is None:
        raise ProcessParseError(f"invalid process identifier: {card.resource_id!r}")

    descendants = hierarchy.descendants_of(card)
    texts = tuple(
        text for element in descendants if (text := element.text.strip())
    )
    level = _first_integer_match(texts, _LEVEL)
    progress = _first_integer_match(texts, _PROGRESS)
    chance = _first_integer_match(texts, _CHANCE)
    if chance is not None and not 0 <= chance <= 100:
        raise ProcessParseError(f"invalid process success chance: {chance}")
    state_labels = tuple(label for label in _STATE_LABELS if label in texts)
    state = _STATE_LABELS[state_labels[0]] if len(state_labels) == 1 else ProcessState.UNKNOWN
    completion_text = next(
        (text for text in texts if text.startswith("Completed ")), None
    )
    name = next(
        (
            text
            for text in texts
            if _LEVEL.fullmatch(text) is None and text not in _STATE_LABELS
        ),
        None,
    )
    ip_address = next((text for text in texts if _is_ipv4(text)), None)
    game_tags = tuple(text for text in texts if _GAME_TAG.fullmatch(text))
    system_markers = tuple(text for text in texts if text in _SYSTEM_MARKERS)
    available_actions = tuple(
        action
        for element in descendants
        if element.clickable and element.enabled
        if (action := _action_name(element)) is not None
    )

    return ProcessCard(
        process_id=process_match.group(1),
        name=name,
        level=level,
        state=state,
        progress_percent=progress,
        completion_text=completion_text,
        ip_address=ip_address,
        success_chance_percent=chance,
        game_tags=game_tags,
        system_markers=system_markers,
        available_actions=available_actions,
        bounds=card.bounds,
        viewport_bounds=viewport,
    )


def _first_integer_match(values: tuple[str, ...], pattern: re.Pattern[str]) -> int | None:
    for value in values:
        match = pattern.fullmatch(value)
        if match is not None:
            return int(match.group(1))
    return None


def _is_ipv4(value: str) -> bool:
    try:
        IPv4Address(value)
    except AddressValueError:
        return False
    return True


def _action_name(element: UIElement) -> str | None:
    text = element.text.strip()
    if _is_ipv4(text):
        return "OPEN_TARGET"
    if text in {"HACK", "RESUME"}:
        return text
    if text.startswith("AD ("):
        return "WATCH_AD"
    if text.startswith("OC ("):
        return "SPEND_OC"
    if element.content_description == "Edit tag and color":
        return "EDIT_TAG"
    return None
