"""Conservative screen-state detection from Android UI hierarchy data."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from hackex2.adb.ui import UIElement, UIHierarchy


class ScreenState(str, Enum):
    HOME = "HOME"
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


def detect_screen(hierarchy: UIHierarchy) -> ScreenDetection:
    if "net.cncapps.hackex2" not in hierarchy.packages:
        return ScreenDetection(
            state=ScreenState.UNKNOWN_SCREEN,
            confidence=0.0,
            evidence=(),
            missing_evidence=("HackEx2 application package",),
        )

    matched = tuple(
        marker.name
        for marker in _HOME_MARKERS
        if any(marker.matches(element) for element in hierarchy.elements)
    )
    missing = tuple(
        marker.name for marker in _HOME_MARKERS if marker.name not in matched
    )
    if not missing:
        return ScreenDetection(
            state=ScreenState.HOME,
            confidence=1.0,
            evidence=matched,
        )

    return ScreenDetection(
        state=ScreenState.UNKNOWN_SCREEN,
        confidence=0.0,
        evidence=matched,
        missing_evidence=missing,
    )

