"""Typed parsing of a connected HackEx2 target dashboard."""

from __future__ import annotations

import re
from dataclasses import dataclass
from ipaddress import AddressValueError, IPv4Address

from hackex2.adb.ui import UIElement, UIHierarchy


class TargetDashboardParseError(ValueError):
    """Raised when target dashboard data is missing or internally inconsistent."""


@dataclass(frozen=True)
class TargetDashboard:
    username: str
    crew_tag: str | None
    level: int
    reputation: int
    score: int
    xp_current: int
    xp_required: int
    xp_percent: int
    ip_address: str
    device: str
    network: str
    firewall_level: int
    encryptor_level: int
    available_actions: tuple[str, ...]


_LEVEL = re.compile(r"LVL\s+(\d+)")
_REPUTATION = re.compile(r"REP\s+(\d+)")
_XP = re.compile(r"(\d+)\s*/\s*(\d+)")
_PERCENT = re.compile(r"(\d+)%")
_SYSTEM_LEVEL = re.compile(r"Lv\.(\d+)")
_CREW_SUFFIX = re.compile(r"\s+\[([^\[\]]+)]\s*$")
_CURSOR_SUFFIX = re.compile(r"\s+_\s*$")
_ACTIONS = ("DISCONNECT", "WALLET", "APPS", "PROCESSES", "LOG", "CREWS")


def parse_target_dashboard(hierarchy: UIHierarchy) -> TargetDashboard:
    """Parse one already verified target dashboard without interacting with it."""

    username, crew_tag = _parse_identity(hierarchy)
    level = _single_pattern_integer(hierarchy, _LEVEL, "target level")
    reputation = _single_pattern_integer(hierarchy, _REPUTATION, "target reputation")
    score = _parse_score(hierarchy)
    xp_current, xp_required = _parse_xp(hierarchy)
    xp_percent = _single_pattern_integer(hierarchy, _PERCENT, "target XP percentage")
    if not 0 <= xp_percent <= 100:
        raise TargetDashboardParseError(
            f"target XP percentage is outside 0..100: {xp_percent}"
        )
    calculated_percent = xp_current * 100 / xp_required
    if abs(calculated_percent - xp_percent) > 1:
        raise TargetDashboardParseError(
            "target XP percentage does not agree with current and required XP"
        )

    ip_address = _row_value(hierarchy, "IP")
    try:
        IPv4Address(ip_address)
    except AddressValueError as exc:
        raise TargetDashboardParseError(
            f"target IP is not a valid IPv4 address: {ip_address!r}"
        ) from exc

    actions = tuple(
        action
        for action in _ACTIONS
        if _single_clickable_action(hierarchy, action) is not None
    )
    missing_actions = tuple(action for action in _ACTIONS if action not in actions)
    if missing_actions:
        raise TargetDashboardParseError(
            f"target dashboard is missing actions: {', '.join(missing_actions)}"
        )

    return TargetDashboard(
        username=username,
        crew_tag=crew_tag,
        level=level,
        reputation=reputation,
        score=score,
        xp_current=xp_current,
        xp_required=xp_required,
        xp_percent=xp_percent,
        ip_address=ip_address,
        device=_row_value(hierarchy, "DEVICE"),
        network=_row_value(hierarchy, "NETWORK"),
        firewall_level=_row_level(hierarchy, "FIREWALL"),
        encryptor_level=_row_level(hierarchy, "ENCRYPTOR"),
        available_actions=actions,
    )


def _parse_identity(hierarchy: UIHierarchy) -> tuple[str, str | None]:
    identities = tuple(
        element.text.strip()
        for element in hierarchy.elements
        if element.text.strip().startswith(">")
    )
    if len(identities) != 1:
        raise TargetDashboardParseError(
            f"expected exactly one target identity, found {len(identities)}"
        )

    identity = identities[0][1:].strip()
    crew_match = _CREW_SUFFIX.search(identity)
    crew_tag = None
    if crew_match is not None:
        crew_tag = crew_match.group(1).strip()
        identity = identity[: crew_match.start()].rstrip()
    username = _CURSOR_SUFFIX.sub("", identity).strip()
    if not username:
        raise TargetDashboardParseError("target username is empty")
    return username, crew_tag or None


def _single_pattern_integer(
    hierarchy: UIHierarchy, pattern: re.Pattern[str], description: str
) -> int:
    values = tuple(
        int(match.group(1))
        for element in hierarchy.elements
        if (match := pattern.fullmatch(element.text.strip())) is not None
    )
    if len(values) != 1:
        raise TargetDashboardParseError(
            f"expected exactly one {description}, found {len(values)}"
        )
    return values[0]


def _parse_score(hierarchy: UIHierarchy) -> int:
    score_label = _single_text_element(hierarchy, "SCORE")
    candidates = tuple(
        int(text)
        for element in hierarchy.elements
        if (text := element.text.strip()).isdigit()
        and element.bounds.left < score_label.bounds.left
        and _vertical_overlap(element, score_label) > 0
    )
    if len(candidates) != 1:
        raise TargetDashboardParseError(
            f"expected exactly one target score beside SCORE, found {len(candidates)}"
        )
    return candidates[0]


def _parse_xp(hierarchy: UIHierarchy) -> tuple[int, int]:
    pairs = tuple(
        (int(match.group(1)), int(match.group(2)))
        for element in hierarchy.elements
        if (match := _XP.fullmatch(element.text.strip())) is not None
    )
    if len(pairs) != 1:
        raise TargetDashboardParseError(
            f"expected exactly one target XP pair, found {len(pairs)}"
        )
    current, required = pairs[0]
    if required <= 0 or not 0 <= current <= required:
        raise TargetDashboardParseError(
            f"invalid target XP values: {current} / {required}"
        )
    return current, required


def _row_level(hierarchy: UIHierarchy, label: str) -> int:
    value = _row_value(hierarchy, label)
    match = _SYSTEM_LEVEL.fullmatch(value)
    if match is None:
        raise TargetDashboardParseError(
            f"invalid {label.lower()} level: {value!r}"
        )
    return int(match.group(1))


def _row_value(hierarchy: UIHierarchy, label: str) -> str:
    label_element = _single_text_element(hierarchy, label)
    candidates = tuple(
        element.text.strip()
        for element in hierarchy.elements
        if element.text.strip()
        and element.bounds.left > label_element.bounds.right
        and _vertical_overlap(element, label_element) > 0
    )
    if len(candidates) != 1:
        raise TargetDashboardParseError(
            f"expected exactly one value beside {label}, found {len(candidates)}"
        )
    return candidates[0]


def _single_text_element(hierarchy: UIHierarchy, text: str) -> UIElement:
    matches = tuple(
        element
        for element in hierarchy.find_all(text=text)
        if element.enabled and element.bounds.width > 0 and element.bounds.height > 0
    )
    if len(matches) != 1:
        raise TargetDashboardParseError(
            f"expected exactly one {text} label, found {len(matches)}"
        )
    return matches[0]


def _single_clickable_action(
    hierarchy: UIHierarchy, action: str
) -> UIElement | None:
    matches = tuple(
        element
        for element in hierarchy.find_all(text=action)
        if element.clickable
        and element.enabled
        and element.bounds.width > 0
        and element.bounds.height > 0
    )
    if len(matches) > 1:
        raise TargetDashboardParseError(
            f"expected no more than one {action} action, found {len(matches)}"
        )
    return matches[0] if matches else None


def _vertical_overlap(first: UIElement, second: UIElement) -> int:
    return min(first.bounds.bottom, second.bounds.bottom) - max(
        first.bounds.top, second.bounds.top
    )
