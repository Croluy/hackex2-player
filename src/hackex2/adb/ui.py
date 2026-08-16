"""Typed parsing for Android UIAutomator hierarchy dumps."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


class UIHierarchyError(ValueError):
    """Raised when UIAutomator output cannot be parsed safely."""


@dataclass(frozen=True)
class Bounds:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def center(self) -> tuple[int, int]:
        return ((self.left + self.right) // 2, (self.top + self.bottom) // 2)


@dataclass(frozen=True)
class UIElement:
    text: str
    resource_id: str
    class_name: str
    package: str
    content_description: str
    clickable: bool
    enabled: bool
    bounds: Bounds
    path: tuple[int, ...] = ()
    scrollable: bool = False
    focused: bool = False


@dataclass(frozen=True)
class UIHierarchy:
    raw_xml: str
    elements: tuple[UIElement, ...]

    @property
    def packages(self) -> tuple[str, ...]:
        return tuple(sorted({element.package for element in self.elements if element.package}))

    @property
    def clickable_elements(self) -> tuple[UIElement, ...]:
        return tuple(
            element
            for element in self.elements
            if element.clickable and element.enabled and element.bounds.width > 0
            and element.bounds.height > 0
        )

    def find_all(
        self,
        *,
        text: str | None = None,
        resource_id: str | None = None,
        content_description: str | None = None,
    ) -> tuple[UIElement, ...]:
        return tuple(
            element
            for element in self.elements
            if (text is None or element.text == text)
            and (resource_id is None or element.resource_id == resource_id)
            and (
                content_description is None
                or element.content_description == content_description
            )
        )

    def descendants_of(self, parent: UIElement) -> tuple[UIElement, ...]:
        if not parent.path:
            return ()
        prefix_length = len(parent.path)
        return tuple(
            element
            for element in self.elements
            if len(element.path) > prefix_length
            and element.path[:prefix_length] == parent.path
        )


@dataclass(frozen=True)
class UIHierarchyDump:
    serial: str
    hierarchy: UIHierarchy
    path: Path | None = None


def extract_hierarchy_xml(output: str) -> str:
    start = output.find("<?xml")
    closing_tag = "</hierarchy>"
    end = output.rfind(closing_tag)
    if start < 0 or end < 0:
        raise UIHierarchyError("UIAutomator output does not contain a hierarchy XML document")
    return output[start : end + len(closing_tag)]


def parse_ui_hierarchy(raw_xml: str) -> UIHierarchy:
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as exc:
        raise UIHierarchyError(f"invalid UI hierarchy XML: {exc}") from exc
    if root.tag != "hierarchy":
        raise UIHierarchyError(f"unexpected UI hierarchy root element: {root.tag!r}")

    elements = tuple(_walk_elements(root))
    if not elements:
        raise UIHierarchyError("UI hierarchy contains no UI elements")
    return UIHierarchy(raw_xml=raw_xml, elements=elements)


def _walk_elements(
    parent: ET.Element, parent_path: tuple[int, ...] = ()
):
    for child_index, child in enumerate(parent):
        child_path = (*parent_path, child_index)
        if child.tag == "node":
            yield _parse_element(child, child_path)
        yield from _walk_elements(child, child_path)


def _parse_element(node: ET.Element, path: tuple[int, ...]) -> UIElement:
    return UIElement(
        text=node.get("text", ""),
        resource_id=node.get("resource-id", ""),
        class_name=node.get("class", ""),
        package=node.get("package", ""),
        content_description=node.get("content-desc", ""),
        clickable=_parse_bool(node.get("clickable")),
        enabled=_parse_bool(node.get("enabled")),
        bounds=_parse_bounds(node.get("bounds", "")),
        path=path,
        scrollable=_parse_bool(node.get("scrollable")),
        focused=_parse_bool(node.get("focused")),
    )


def _parse_bool(value: str | None) -> bool:
    return value == "true"


def _parse_bounds(value: str) -> Bounds:
    match = re.fullmatch(r"\[(-?\d+),(-?\d+)]\[(-?\d+),(-?\d+)]", value)
    if not match:
        raise UIHierarchyError(f"invalid UI element bounds: {value!r}")
    left, top, right, bottom = (int(part) for part in match.groups())
    if right < left or bottom < top:
        raise UIHierarchyError(f"inverted UI element bounds: {value!r}")
    return Bounds(left, top, right, bottom)
