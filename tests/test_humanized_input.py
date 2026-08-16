from __future__ import annotations

import random
import unittest

from hackex2.adb.input import HumanizedInput
from hackex2.adb.ui import Bounds, UIElement
from hackex2.config import InputSettings


class FakeADBClient:
    def __init__(self) -> None:
        self.taps: list[tuple[str, int, int]] = []

    def tap(self, serial: str, x: int, y: int) -> None:
        self.taps.append((serial, x, y))


class HumanizedInputTest(unittest.TestCase):
    def test_plans_center_weighted_taps_inside_radius_and_element(self) -> None:
        humanized = HumanizedInput(
            InputSettings(100, 500, 12),
            random_source=random.Random(42),
            sleeper=lambda _: None,
        )
        bounds = Bounds(371, 2148, 531, 2292)

        plans = [humanized.plan_tap(bounds) for _ in range(100)]

        center_x, center_y = bounds.center
        self.assertTrue(all(bounds.left < plan.x < bounds.right for plan in plans))
        self.assertTrue(all(bounds.top < plan.y < bounds.bottom for plan in plans))
        self.assertTrue(all(abs(plan.x - center_x) <= 12 for plan in plans))
        self.assertTrue(all(abs(plan.y - center_y) <= 12 for plan in plans))
        self.assertTrue(all(100 <= plan.delay_ms <= 500 for plan in plans))
        self.assertGreater(len({(plan.x, plan.y) for plan in plans}), 1)

    def test_waits_then_taps_detected_clickable_element(self) -> None:
        delays: list[float] = []
        client = FakeADBClient()
        humanized = HumanizedInput(
            InputSettings(250, 250, 0),
            random_source=random.Random(7),
            sleeper=delays.append,
        )
        element = UIElement(
            text="PROCESSES",
            resource_id="nav-item-processes",
            class_name="android.widget.Button",
            package="net.cncapps.hackex2",
            content_description="",
            clickable=True,
            enabled=True,
            bounds=Bounds(371, 2148, 531, 2292),
        )

        plan = humanized.tap_element(client, "R5CY235KPLP", element)

        self.assertEqual(delays, [0.25])
        self.assertEqual(client.taps, [("R5CY235KPLP", 451, 2220)])
        self.assertEqual(plan.delay_ms, 250)


if __name__ == "__main__":
    unittest.main()
