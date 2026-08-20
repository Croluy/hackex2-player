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

    PASSWORD_REQUIRED = "PASSWORD_REQUIRED"
    LOGIN = "LOGIN"
    TRANSFERABLE = "TRANSFERABLE"
    PROTECTED = "PROTECTED"
    TRANSFERRED = "TRANSFERRED"


@dataclass(frozen=True)
class TargetWalletSnapshot:
    variant: TargetWalletVariant
    owner_username: str
    login_username: str
    masked_password_length: int
    available_actions: tuple[str, ...]


@dataclass(frozen=True)
class TargetWalletPasswordRequiredSnapshot:
    variant: TargetWalletVariant
    owner_username: str
    login_username: str
    masked_password_length: int
    encryptor_level: int
    exploit_kit_count: int
    crack_action: UIElement
    exploit_kit_action: UIElement
    back_action: UIElement
    available_actions: tuple[str, ...]


@dataclass(frozen=True)
class TargetWalletAuthenticatedSnapshot:
    variant: TargetWalletVariant
    owner_username: str
    wallet_address: str
    hot_wallet_crypto: int
    cold_storage_crypto: int | None
    transfer_amount: int | None
    amount_field: UIElement | None
    max_action: UIElement | None
    transfer_action: UIElement | None
    back_action: UIElement
    protection_evidence: tuple[str, ...]


_OWNER = re.compile(r"(.+)'s wallet")
_MASKED_PASSWORD = re.compile(r"\*+")
_MASKED_OR_HIDDEN_PASSWORD = re.compile(r"[*.]+")
_ENCRYPTED_PASSWORD = re.compile(r"Password encrypted at Lv\.(\d+)")
_EXPLOIT_KIT = re.compile(r"\*?\s*USE EXPLOIT KIT \(x(\d+)\)")
_CRACK_PASSWORD = re.compile(r"\*?\s*CRACK PASSWORD")
_ACTION_LABELS = {
    "< back": "BACK",
    "DISCONNECT": "DISCONNECT",
    "LOGIN >": "LOGIN",
}
_WALLET_ADDRESS = re.compile(r"hx[0-9a-z]+", re.IGNORECASE)
_HOT_WALLET = re.compile(r"HOT WALLET\s*([\d,]+)\s*Crypto", re.IGNORECASE)
_COLD_STORAGE = re.compile(
    r"COLD STORAGE(?:\s*Secured)?\s*([\d,]+)\s*Crypto", re.IGNORECASE
)
_TRANSFER_CONFIRMATION = re.compile(
    r"\[OK]\s+Transferred\s+([\d,]+)\s+Crypto\s+to\s+your\s+wallet\.",
    re.IGNORECASE,
)
_PROTECTION_MARKERS = ("WALLET SHIELD ACTIVE", "TRANSFER BLOCKED")


def parse_target_wallet_password_required(
    hierarchy: UIHierarchy,
) -> TargetWalletPasswordRequiredSnapshot:
    """Parse an observed encrypted-password branch without consuming a kit."""

    owner = _parse_owner(hierarchy)
    username_label = _single_text_element(hierarchy, "USERNAME")
    password_label = _single_text_element(hierarchy, "PASSWORD")
    encryption_notice, encryption_match = _single_pattern_element(
        hierarchy, _ENCRYPTED_PASSWORD, "encrypted-password level"
    )
    exploit_kit_action, exploit_match = _single_pattern_clickable_element(
        hierarchy, _EXPLOIT_KIT, "Exploit Kit action"
    )
    crack_action, _ = _single_pattern_clickable_element(
        hierarchy, _CRACK_PASSWORD, "Crack Password action"
    )
    back_action = _single_clickable_element(hierarchy, "< back")
    _single_clickable_element(hierarchy, "DISCONNECT")

    username = _single_field_value(
        hierarchy,
        description="wallet username",
        top=username_label.bounds.bottom,
        bottom=password_label.bounds.top,
        pattern=None,
    )
    masked_password = _single_field_value(
        hierarchy,
        description="hidden wallet password",
        top=password_label.bounds.bottom,
        bottom=encryption_notice.bounds.top,
        pattern=_MASKED_OR_HIDDEN_PASSWORD,
    )
    if username != owner:
        raise TargetWalletParseError(
            "wallet owner and encrypted-login username do not match"
        )

    actions = (
        "BACK",
        "DISCONNECT",
        "USE_EXPLOIT_KIT",
        "CRACK_PASSWORD",
    )
    return TargetWalletPasswordRequiredSnapshot(
        variant=TargetWalletVariant.PASSWORD_REQUIRED,
        owner_username=owner,
        login_username=username,
        masked_password_length=len(masked_password),
        encryptor_level=int(encryption_match.group(1)),
        exploit_kit_count=int(exploit_match.group(1)),
        crack_action=crack_action,
        exploit_kit_action=exploit_kit_action,
        back_action=back_action,
        available_actions=actions,
    )


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


def parse_target_wallet_authenticated(
    hierarchy: UIHierarchy,
) -> TargetWalletAuthenticatedSnapshot:
    """Parse a logged-in Wallet and classify only verified functional branches."""

    owner = _parse_owner(hierarchy)
    address = _single_pattern_value(
        hierarchy, _WALLET_ADDRESS, "target wallet address"
    )
    hot_wallet_crypto = _single_pattern_integer(
        hierarchy, _HOT_WALLET, "hot wallet balance"
    )
    cold_values = _pattern_integers(hierarchy, _COLD_STORAGE)
    if len(cold_values) > 1:
        raise TargetWalletParseError(
            f"expected at most one cold storage balance, found {len(cold_values)}"
        )
    cold_storage_crypto = cold_values[0] if cold_values else None

    protection_evidence = tuple(
        marker
        for marker in _PROTECTION_MARKERS
        if any(marker in element.text.upper() for element in hierarchy.elements)
    )
    amount_field = _optional_visible_element(hierarchy, resource_id="steal-amount")
    max_action = _optional_visible_element(hierarchy, text="MAX")
    transfer_action = _optional_visible_element(
        hierarchy, text="TRANSFER TO MY WALLET"
    )
    back_action = _single_clickable_element(hierarchy, "< back")
    transfer_confirmation = parse_wallet_transfer_confirmation(hierarchy)

    if protection_evidence:
        active_controls = tuple(
            name
            for name, element in (
                ("MAX", max_action),
                ("TRANSFER TO MY WALLET", transfer_action),
            )
            if element is not None and element.enabled and element.clickable
        )
        if active_controls:
            raise TargetWalletParseError(
                "wallet reports protection but transfer controls are active: "
                f"{', '.join(active_controls)}"
            )
        variant = TargetWalletVariant.PROTECTED
    elif transfer_confirmation is not None and hot_wallet_crypto == 0:
        active_form_elements = tuple(
            name
            for name, element in (
                ("amount", amount_field),
                ("MAX", max_action),
                ("TRANSFER TO MY WALLET", transfer_action),
            )
            if element is not None and element.enabled
        )
        if active_form_elements:
            raise TargetWalletParseError(
                "wallet reports a completed transfer but form elements remain active: "
                f"{', '.join(active_form_elements)}"
            )
        variant = TargetWalletVariant.TRANSFERRED
    else:
        if amount_field is None or max_action is None or transfer_action is None:
            raise TargetWalletParseError(
                "wallet has no protection marker and an incomplete transfer form"
            )
        if not amount_field.enabled or not amount_field.clickable:
            raise TargetWalletParseError("wallet transfer amount field is unavailable")
        if not max_action.enabled or not max_action.clickable:
            raise TargetWalletParseError(
                "MAX is unavailable without a recognized protection marker"
            )
        variant = TargetWalletVariant.TRANSFERABLE

    transfer_amount = _parse_optional_crypto_amount(
        amount_field.text if amount_field is not None else ""
    )
    return TargetWalletAuthenticatedSnapshot(
        variant=variant,
        owner_username=owner,
        wallet_address=address,
        hot_wallet_crypto=hot_wallet_crypto,
        cold_storage_crypto=cold_storage_crypto,
        transfer_amount=transfer_amount,
        amount_field=amount_field,
        max_action=max_action,
        transfer_action=transfer_action,
        back_action=back_action,
        protection_evidence=protection_evidence,
    )


def parse_wallet_transfer_confirmation(hierarchy: UIHierarchy) -> int | None:
    """Return the confirmed transferred amount, rejecting conflicting messages."""

    amounts = tuple(
        int(match.group(1).replace(",", ""))
        for element in hierarchy.elements
        if (match := _TRANSFER_CONFIRMATION.fullmatch(element.text.strip())) is not None
    )
    if len(set(amounts)) > 1:
        raise TargetWalletParseError("wallet shows conflicting transfer confirmations")
    return amounts[0] if amounts else None


def _parse_owner(hierarchy: UIHierarchy) -> str:
    owners = tuple(
        match.group(1).strip()
        for element in hierarchy.elements
        if (match := _OWNER.fullmatch(element.text.strip())) is not None
    )
    if len(owners) != 1 or not owners[0]:
        raise TargetWalletParseError(
            f"expected exactly one wallet owner, found {len(owners)}"
        )
    return owners[0]


def _pattern_integers(
    hierarchy: UIHierarchy, pattern: re.Pattern[str]
) -> tuple[int, ...]:
    return tuple(
        int(match.group(1).replace(",", ""))
        for element in hierarchy.elements
        if (match := pattern.search(element.text.strip())) is not None
    )


def _single_pattern_integer(
    hierarchy: UIHierarchy, pattern: re.Pattern[str], description: str
) -> int:
    values = _pattern_integers(hierarchy, pattern)
    if len(values) != 1:
        raise TargetWalletParseError(
            f"expected exactly one {description}, found {len(values)}"
        )
    return values[0]


def _single_pattern_value(
    hierarchy: UIHierarchy, pattern: re.Pattern[str], description: str
) -> str:
    values = tuple(
        element.text.strip()
        for element in hierarchy.elements
        if pattern.fullmatch(element.text.strip()) is not None
    )
    if len(values) != 1:
        raise TargetWalletParseError(
            f"expected exactly one {description}, found {len(values)}"
        )
    return values[0]


def _single_pattern_element(
    hierarchy: UIHierarchy,
    pattern: re.Pattern[str],
    description: str,
) -> tuple[UIElement, re.Match[str]]:
    matches = tuple(
        (element, match)
        for element in hierarchy.elements
        if element.enabled
        and element.bounds.width > 0
        and element.bounds.height > 0
        and (match := pattern.fullmatch(element.text.strip())) is not None
    )
    if len(matches) != 1:
        raise TargetWalletParseError(
            f"expected exactly one {description}, found {len(matches)}"
        )
    return matches[0]


def _single_pattern_clickable_element(
    hierarchy: UIHierarchy,
    pattern: re.Pattern[str],
    description: str,
) -> tuple[UIElement, re.Match[str]]:
    matches = tuple(
        (element, match)
        for element in hierarchy.elements
        if element.enabled
        and element.clickable
        and element.bounds.width > 0
        and element.bounds.height > 0
        and (match := pattern.fullmatch(element.text.strip())) is not None
    )
    if len(matches) != 1:
        raise TargetWalletParseError(
            f"expected exactly one clickable {description}, found {len(matches)}"
        )
    return matches[0]


def _parse_optional_crypto_amount(value: str) -> int | None:
    normalized = value.strip().replace(",", "")
    if not normalized:
        return None
    if not normalized.isdigit():
        raise TargetWalletParseError(
            f"wallet transfer amount is not an integer: {value!r}"
        )
    return int(normalized)


def _optional_visible_element(
    hierarchy: UIHierarchy,
    *,
    text: str | None = None,
    resource_id: str | None = None,
) -> UIElement | None:
    matches = tuple(
        element
        for element in hierarchy.find_all(text=text, resource_id=resource_id)
        if element.bounds.width > 0 and element.bounds.height > 0
    )
    if len(matches) > 1:
        description = text or resource_id or "wallet element"
        raise TargetWalletParseError(
            f"expected at most one {description} element, found {len(matches)}"
        )
    return matches[0] if matches else None


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
