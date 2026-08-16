"""Typed parsing of editable, locked, and saved target Log branches."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from hackex2.adb.ui import UIElement, UIHierarchy


class TargetLogParseError(ValueError):
    """Raised when a recognized target Log is internally inconsistent."""


class TargetLogVariant(str, Enum):
    EDITABLE = "EDITABLE"
    LOCKED = "LOCKED"
    SAVED = "SAVED"


@dataclass(frozen=True)
class TargetLogSnapshot:
    variant: TargetLogVariant
    has_content: bool
    content_length: int
    save_enabled: bool
    editor: UIElement
    save_action: UIElement
    back_action: UIElement
    disconnect_action: UIElement
    lock_evidence: tuple[str, ...]
    external_packages: tuple[str, ...]
    viewport_bottom: int


def parse_target_log(hierarchy: UIHierarchy) -> TargetLogSnapshot:
    editor = _single_visible_element(
        hierarchy, class_name="android.widget.EditText", description="Log editor"
    )
    save_action = _single_visible_element(
        hierarchy, text="SAVE", description="Log Save control"
    )
    back_action = _single_active_element(hierarchy, "< back")
    disconnect_action = _single_active_element(hierarchy, "DISCONNECT")
    content = editor.text
    lock_evidence = tuple(
        text
        for element in hierarchy.elements
        if (text := element.text.strip())
        if "[LOCKED]" in text.upper() and "LOG" in text.upper()
    )

    if lock_evidence:
        if save_action.enabled:
            raise TargetLogParseError("locked Log unexpectedly has enabled SAVE")
        variant = TargetLogVariant.LOCKED
    elif not content.strip() and not save_action.enabled:
        variant = TargetLogVariant.SAVED
    else:
        if not editor.enabled or not editor.clickable:
            raise TargetLogParseError(
                "Log editor is unavailable without a recognized lock marker"
            )
        variant = TargetLogVariant.EDITABLE

    return TargetLogSnapshot(
        variant=variant,
        has_content=bool(content.strip()),
        content_length=len(content),
        save_enabled=save_action.enabled,
        editor=editor,
        save_action=save_action,
        back_action=back_action,
        disconnect_action=disconnect_action,
        lock_evidence=lock_evidence,
        external_packages=tuple(
            package
            for package in hierarchy.packages
            if package != "net.cncapps.hackex2"
        ),
        viewport_bottom=max(element.bounds.bottom for element in hierarchy.elements),
    )


def _single_visible_element(
    hierarchy: UIHierarchy,
    *,
    text: str | None = None,
    class_name: str | None = None,
    description: str,
) -> UIElement:
    matches = tuple(
        element
        for element in hierarchy.elements
        if (text is None or element.text == text)
        and (class_name is None or element.class_name == class_name)
        and element.bounds.width > 0
        and element.bounds.height > 0
    )
    if len(matches) != 1:
        raise TargetLogParseError(
            f"expected exactly one {description}, found {len(matches)}"
        )
    return matches[0]


def _single_active_element(hierarchy: UIHierarchy, text: str) -> UIElement:
    matches = tuple(
        element
        for element in hierarchy.find_all(text=text)
        if element.enabled
        and element.clickable
        and element.bounds.width > 0
        and element.bounds.height > 0
    )
    if len(matches) != 1:
        raise TargetLogParseError(
            f"expected exactly one active {text} action, found {len(matches)}"
        )
    return matches[0]
