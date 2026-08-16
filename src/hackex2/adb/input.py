"""Humanized Android input planned within detected UI element bounds."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from hackex2.adb.device import ADBClient, ADBError
from hackex2.adb.ui import Bounds, UIElement
from hackex2.config import InputSettings


@dataclass(frozen=True)
class TapPlan:
    x: int
    y: int
    delay_ms: int


class HumanizedInput:
    def __init__(
        self,
        settings: InputSettings,
        *,
        random_source: random.Random | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        settings.validate()
        self.settings = settings
        self.random = random_source or random.Random()
        self.sleeper = sleeper

    def plan_tap(self, bounds: Bounds) -> TapPlan:
        if bounds.width < 3 or bounds.height < 3:
            raise ADBError(f"tap target is too small: {bounds}")

        center_x, center_y = bounds.center
        radius = self.settings.tap_random_radius_px
        min_x = max(bounds.left + 1, center_x - radius)
        max_x = min(bounds.right - 1, center_x + radius)
        min_y = max(bounds.top + 1, center_y - radius)
        max_y = min(bounds.bottom - 1, center_y + radius)

        x = _distributed_coordinate(self.random, center_x, min_x, max_x, radius)
        y = _distributed_coordinate(self.random, center_y, min_y, max_y, radius)
        delay_ms = self.random.randint(
            self.settings.min_action_delay_ms,
            self.settings.max_action_delay_ms,
        )
        return TapPlan(x=x, y=y, delay_ms=delay_ms)

    def tap_element(
        self, client: ADBClient, serial: str, element: UIElement
    ) -> TapPlan:
        if not element.clickable or not element.enabled:
            raise ADBError("refusing to tap an element that is not clickable and enabled")
        plan = self.plan_tap(element.bounds)
        self.sleeper(plan.delay_ms / 1000)
        client.tap(serial, plan.x, plan.y)
        return plan


def _distributed_coordinate(
    random_source: random.Random,
    center: int,
    minimum: int,
    maximum: int,
    radius: int,
) -> int:
    if minimum > maximum:
        raise ADBError("tap target has no safe interior area")
    if radius == 0:
        return min(max(center, minimum), maximum)
    standard_deviation = max(radius / 2, 1)
    sampled = round(random_source.gauss(center, standard_deviation))
    return min(max(sampled, minimum), maximum)

