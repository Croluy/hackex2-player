"""Typed parsing for observed branches of a connected target wallet."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from hackex2.adb.ui import UIElement, UIHierarchy


class TargetWalletParseError(ValueError):
    """Raised when a known target-wallet branch is internally inconsistent."""


class TargetWalletVariant(str, Enum):
    """Wallet branches verified from real UI observations."""

    LOGIN = "LOGIN"


@dataclass(frozen=True)
class TargetWalletSnapshot:
    variant: TargetWalletVariant
    owner_username: str
    login_username: str
    masked_password_length: int
    available_actions: tuple[str, ...]


_OWNER = re.compile(r"(.+)'s wallet")
_MASKED_PASSWORD = re.compile(r"\*+")
_ACTION_LABELS = {
    "< back": "BACK",
    "DISCONNECT": "DISCONNECT",
    "LOGIN >": "LOGIN",
}


def parse_target_wallet_login(hierarchy: UIHierarchy) -> TargetWalletSnapshot:
    """Parse the known Login branch without exposing or submitting a password."""

    owners = tuple(
        match.group(1).strip()
        for element in hierarchy.elements
        if (match := _OWNER.fullmatch(element.text.strip())) is not None
    )
    if len(owners) != 1 or not owners[0]:
        raise TargetWalletParseError(
            f"expected exactly one wallet owner, found {len(owners)}"
        )
    owner = owners[0]

    username_label = _single_text_element(hierarchy, "USERNAME")
    password_label = _single_text_element(hierarchy, "PASSWORD")
    login_action = _single_clickable_element(hierarchy, "LOGIN >")
    username = _single_field_value(
        hierarchy,
        description="wallet username",
        top=username_label.bounds.bottom,
        bottom=password_label.bounds.top,
        pattern=None,
    )
    masked_password = _single_field_value(
        hierarchy,
        description="masked wallet password",
        top=password_label.bounds.bottom,
        bottom=login_action.bounds.top,
        pattern=_MASKED_PASSWORD,
    )
    if username != owner:
        raise TargetWalletParseError(
            "wallet owner and prefilled login username do not match"
        )

    actions = tuple(
        canonical
        for label, canonical in _ACTION_LABELS.items()
        if _single_clickable_element(hierarchy, label, required=False) is not None
    )
    if len(actions) != len(_ACTION_LABELS):
        missing = tuple(
            canonical
            for label, canonical in _ACTION_LABELS.items()
            if _single_clickable_element(hierarchy, label, required=False) is None
        )
        raise TargetWalletParseError(
            f"wallet Login branch is missing actions: {', '.join(missing)}"
        )

    return TargetWalletSnapshot(
        variant=TargetWalletVariant.LOGIN,
        owner_username=owner,
        login_username=username,
        masked_password_length=len(masked_password),
        available_actions=actions,
    )


def _single_field_value(
    hierarchy: UIHierarchy,
    *,
    description: str,
    top: int,
    bottom: int,
    pattern: re.Pattern[str] | None,
) -> str:
    candidates = tuple(
        text
        for element in hierarchy.elements
        if (text := element.text.strip())
        and element.bounds.top >= top
        and element.bounds.bottom <= bottom
        and (pattern is None or pattern.fullmatch(text) is not None)
    )
    if len(candidates) != 1:
        raise TargetWalletParseError(
            f"expected exactly one {description}, found {len(candidates)}"
        )
    return candidates[0]


def _single_text_element(hierarchy: UIHierarchy, text: str) -> UIElement:
    matches = tuple(
        element
        for element in hierarchy.find_all(text=text)
        if element.enabled and element.bounds.width > 0 and element.bounds.height > 0
    )
    if len(matches) != 1:
        raise TargetWalletParseError(
            f"expected exactly one {text} element, found {len(matches)}"
        )
    return matches[0]


def _single_clickable_element(
    hierarchy: UIHierarchy, text: str, *, required: bool = True
) -> UIElement | None:
    matches = tuple(
        element
        for element in hierarchy.find_all(text=text)
        if element.clickable
        and element.enabled
        and element.bounds.width > 0
        and element.bounds.height > 0
    )
    if len(matches) > 1 or (required and len(matches) != 1):
        raise TargetWalletParseError(
            f"expected exactly one clickable {text} element, found {len(matches)}"
        )
    return matches[0] if matches else None
