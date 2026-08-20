from __future__ import annotations

import random
import unittest

from hackex2.adb.input import HumanizedInput
from hackex2.adb.ui import Bounds, UIElement
from hackex2.config import InputSettings


class FakeADBClient:
    def __init__(self) -> None:
        self.taps: list[tuple[str, int, int]] = []
        self.swipes: list[tuple[str, int, int, int, int, int]] = []

    def tap(self, serial: str, x: int, y: int) -> None:
        self.taps.append((serial, x, y))

    def swipe(
        self,
        serial: str,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration_ms: int,
    ) -> None:
        self.swipes.append(
            (serial, start_x, start_y, end_x, end_y, duration_ms)
        )


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

    def test_plans_upward_swipe_inside_detected_scroll_region(self) -> None:
        delays: list[float] = []
        client = FakeADBClient()
        humanized = HumanizedInput(
            InputSettings(
                min_action_delay_ms=200,
                max_action_delay_ms=200,
                tap_random_radius_px=12,
                min_swipe_duration_ms=400,
                max_swipe_duration_ms=400,
                swipe_random_radius_px=10,
            ),
            random_source=random.Random(3),
            sleeper=delays.append,
        )
        bounds = Bounds(45, 452, 1035, 2137)

        plan = humanized.swipe_vertical(
            client, "R5CY235KPLP", bounds, upward=True
        )

        self.assertTrue(bounds.left < plan.start_x < bounds.right)
        self.assertTrue(bounds.left < plan.end_x < bounds.right)
        self.assertTrue(bounds.top < plan.end_y < plan.start_y < bounds.bottom)
        self.assertEqual(plan.duration_ms, 400)
        self.assertEqual(delays, [0.2])
        self.assertEqual(len(client.swipes), 1)


if __name__ == "__main__":
    unittest.main()
