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


@dataclass(frozen=True)
class SwipePlan:
    start_x: int
    start_y: int
    end_x: int
    end_y: int
    duration_ms: int
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

    def plan_vertical_swipe(self, bounds: Bounds, *, upward: bool) -> SwipePlan:
        if bounds.width < 3 or bounds.height < 100:
            raise ADBError(f"swipe target is too small: {bounds}")
        center_x, _ = bounds.center
        upper_y = bounds.top + bounds.height // 4
        lower_y = bounds.top + (bounds.height * 5) // 6
        radius = self.settings.swipe_random_radius_px
        start_y_center, end_y_center = (
            (lower_y, upper_y) if upward else (upper_y, lower_y)
        )
        start_x = _distributed_coordinate(
            self.random,
            center_x,
            max(bounds.left + 1, center_x - radius),
            min(bounds.right - 1, center_x + radius),
            radius,
        )
        end_x = _distributed_coordinate(
            self.random,
            center_x,
            max(bounds.left + 1, center_x - radius),
            min(bounds.right - 1, center_x + radius),
            radius,
        )
        start_y = _distributed_coordinate(
            self.random,
            start_y_center,
            max(bounds.top + 1, start_y_center - radius),
            min(bounds.bottom - 1, start_y_center + radius),
            radius,
        )
        end_y = _distributed_coordinate(
            self.random,
            end_y_center,
            max(bounds.top + 1, end_y_center - radius),
            min(bounds.bottom - 1, end_y_center + radius),
            radius,
        )
        return SwipePlan(
            start_x=start_x,
            start_y=start_y,
            end_x=end_x,
            end_y=end_y,
            duration_ms=self.random.randint(
                self.settings.min_swipe_duration_ms,
                self.settings.max_swipe_duration_ms,
            ),
            delay_ms=self.random.randint(
                self.settings.min_action_delay_ms,
                self.settings.max_action_delay_ms,
            ),
        )

    def swipe_vertical(
        self,
        client: ADBClient,
        serial: str,
        bounds: Bounds,
        *,
        upward: bool,
    ) -> SwipePlan:
        plan = self.plan_vertical_swipe(bounds, upward=upward)
        self.sleeper(plan.delay_ms / 1000)
        client.swipe(
            serial,
            plan.start_x,
            plan.start_y,
            plan.end_x,
            plan.end_y,
            plan.duration_ms,
        )
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
