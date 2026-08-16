"""Conservative screen-state detection from Android UI hierarchy data."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from hackex2.adb.ui import UIElement, UIHierarchy


class ScreenState(str, Enum):
    HOME = "HOME"
    PROCESSES = "PROCESSES"
    UNKNOWN_SCREEN = "UNKNOWN_SCREEN"


@dataclass(frozen=True)
class ScreenDetection:
    state: ScreenState
    confidence: float
    evidence: tuple[str, ...]
    missing_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Marker:
    name: str
    text: str | None = None
    resource_id: str | None = None
    content_description: str | None = None
    clickable: bool | None = None

    def matches(self, element: UIElement) -> bool:
        return (
            (self.text is None or element.text == self.text)
            and (self.resource_id is None or element.resource_id == self.resource_id)
            and (
                self.content_description is None
                or element.content_description == self.content_description
            )
            and (self.clickable is None or element.clickable is self.clickable)
            and element.enabled
            and element.bounds.width > 0
            and element.bounds.height > 0
        )


_HOME_MARKERS = (
    _Marker(
        name="home navigation button",
        text="HOME",
        resource_id="nav-item-dashboard",
        clickable=True,
    ),
    _Marker(name="XP progress panel", text="// XP PROGRESS"),
    _Marker(name="My Device action", content_description="MY DEVICE", clickable=True),
    _Marker(
        name="dashboard Scan action",
        resource_id="onboard-scan-btn",
        content_description="SCAN",
        clickable=True,
    ),
)

_PROCESSES_MARKERS = (
    _Marker(
        name="Processes navigation button",
        text="PROCESSES",
        resource_id="nav-item-processes",
        clickable=True,
    ),
    _Marker(name="Processes heading", text="// PROCESSES"),
    _Marker(name="process search action", content_description="Search", clickable=True),
    _Marker(name="all-processes filter", text="ALL", clickable=True),
)


def detect_screen(hierarchy: UIHierarchy) -> ScreenDetection:
    if "net.cncapps.hackex2" not in hierarchy.packages:
        return ScreenDetection(
            state=ScreenState.UNKNOWN_SCREEN,
            confidence=0.0,
            evidence=(),
            missing_evidence=("HackEx2 application package",),
        )

    candidates = (
        (ScreenState.HOME, _match_markers(_HOME_MARKERS, hierarchy)),
        (ScreenState.PROCESSES, _match_markers(_PROCESSES_MARKERS, hierarchy)),
    )
    complete = tuple(
        (state, matched, missing)
        for state, (matched, missing) in candidates
        if not missing
    )
    if len(complete) == 1:
        state, matched, _ = complete[0]
        return ScreenDetection(
            state=state,
            confidence=1.0,
            evidence=matched,
        )

    if len(complete) > 1:
        return ScreenDetection(
            state=ScreenState.UNKNOWN_SCREEN,
            confidence=0.0,
            evidence=tuple(state.value for state, _, _ in complete),
            missing_evidence=("unambiguous screen state",),
        )

    _, (matched, missing) = max(candidates, key=lambda item: len(item[1][0]))

    return ScreenDetection(
        state=ScreenState.UNKNOWN_SCREEN,
        confidence=0.0,
        evidence=matched,
        missing_evidence=missing,
    )


def _match_markers(
    markers: tuple[_Marker, ...], hierarchy: UIHierarchy
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    matched = tuple(
        marker.name
        for marker in markers
        if any(marker.matches(element) for element in hierarchy.elements)
    )
    missing = tuple(marker.name for marker in markers if marker.name not in matched)
    return matched, missing
