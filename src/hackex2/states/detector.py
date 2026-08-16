"""Conservative screen-state detection from Android UI hierarchy data."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from hackex2.adb.ui import UIElement, UIHierarchy


class ScreenState(str, Enum):
    HOME = "HOME"
    PROCESSES = "PROCESSES"
    TARGET_DASHBOARD = "TARGET_DASHBOARD"
    TARGET_WALLET_LOGIN = "TARGET_WALLET_LOGIN"
    TARGET_WALLET_AUTHENTICATED = "TARGET_WALLET_AUTHENTICATED"
    TARGET_LOG = "TARGET_LOG"
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
    text_contains: str | None = None
    class_name: str | None = None
    clickable: bool | None = None
    enabled: bool | None = True

    def matches(self, element: UIElement) -> bool:
        return (
            (self.text is None or element.text == self.text)
            and (self.text_contains is None or self.text_contains in element.text)
            and (self.class_name is None or element.class_name == self.class_name)
            and (self.resource_id is None or element.resource_id == self.resource_id)
            and (
                self.content_description is None
                or element.content_description == self.content_description
            )
            and (self.clickable is None or element.clickable is self.clickable)
            and (self.enabled is None or element.enabled is self.enabled)
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

_TARGET_DASHBOARD_MARKERS = (
    _Marker(name="target connection status", text="CONNECTED"),
    _Marker(name="target disconnect action", text="DISCONNECT", clickable=True),
    _Marker(name="target XP progress panel", text="// XP PROGRESS"),
    _Marker(name="target Wallet action", text="WALLET", clickable=True),
    _Marker(name="target Apps action", text="APPS", clickable=True),
    _Marker(name="target Log action", text="LOG", clickable=True),
    _Marker(name="target Crews action", text="CREWS", clickable=True),
    _Marker(name="target system information panel", text="// SYSTEM INFO"),
)

_TARGET_WALLET_LOGIN_MARKERS = (
    _Marker(name="target wallet heading", text="// CRYPTO WALLET"),
    _Marker(name="wallet Login panel", text="WALLET LOGIN"),
    _Marker(name="wallet Username label", text="USERNAME"),
    _Marker(name="wallet Password label", text="PASSWORD"),
    _Marker(name="wallet Login action", text="LOGIN >", clickable=True),
    _Marker(name="target wallet Back action", text="< back", clickable=True),
    _Marker(name="target disconnect action", text="DISCONNECT", clickable=True),
)

_TARGET_WALLET_AUTHENTICATED_MARKERS = (
    _Marker(name="target wallet heading", text="// CRYPTO WALLET"),
    _Marker(name="wallet address label", text="WALLET ADDRESS"),
    _Marker(name="hot wallet balance summary", text_contains="HOT WALLET"),
    _Marker(name="target wallet Back action", text="< back", clickable=True),
    _Marker(name="target disconnect action", text="DISCONNECT", clickable=True),
)

_TARGET_LOG_MARKERS = (
    _Marker(name="target Log heading", text="// VICTIM LOG"),
    _Marker(
        name="target Log editor",
        class_name="android.widget.EditText",
        enabled=None,
    ),
    _Marker(name="target Log Save control", text="SAVE", enabled=None),
    _Marker(name="target disconnect action", text="DISCONNECT", clickable=True),
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
        (
            ScreenState.TARGET_DASHBOARD,
            _match_markers(_TARGET_DASHBOARD_MARKERS, hierarchy),
        ),
        (
            ScreenState.TARGET_WALLET_LOGIN,
            _match_markers(_TARGET_WALLET_LOGIN_MARKERS, hierarchy),
        ),
        (
            ScreenState.TARGET_WALLET_AUTHENTICATED,
            _match_markers(_TARGET_WALLET_AUTHENTICATED_MARKERS, hierarchy),
        ),
        (ScreenState.TARGET_LOG, _match_markers(_TARGET_LOG_MARKERS, hierarchy)),
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
