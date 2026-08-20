from __future__ import annotations

import unittest

from hackex2.adb.ui import parse_ui_hierarchy
from hackex2.processes import (
    ProcessFilter,
    ProcessState,
    infer_selected_process_filter,
    locate_process_filter_tabs,
    parse_process_list,
)

from tests.test_screen_detector import hierarchy_xml, node


def process_card(
    process_id: str,
    bounds: str,
    name: str,
    level: str,
    state: str,
    *extra_nodes: str,
) -> str:
    return (
        f"<node text='' resource-id='proc-{process_id}' class='android.view.View' "
        "package='net.cncapps.hackex2' content-desc='' clickable='false' "
        f"enabled='true' bounds='{bounds}'>"
        f"{node(text=name)}{node(text=level)}{node(text=state)}"
        f"{''.join(extra_nodes)}"
        "</node>"
    )


def filter_button(left: int, right: int, text: str = "") -> str:
    return (
        f"<node text='{text}' resource-id='' class='android.widget.Button' "
        "package='net.cncapps.hackex2' content-desc='' clickable='true' "
        f"enabled='true' bounds='[{left},329][{right},421]' />"
    )


class ProcessListParserTest(unittest.TestCase):
    def test_parses_dynamic_cards_and_separates_offscreen_entries(self) -> None:
        hierarchy = parse_ui_hierarchy(
            hierarchy_xml(
                node(text="8 active tasks"),
                process_card(
                    "2241091",
                    "[45,452][1035,798]",
                    "Antivirus Scan ",
                    "Lv.8",
                    "RUNNING",
                    node(text="41.17.64.224", clickable=True),
                    node(text="74% chance"),
                    node(text="revenge"),
                    node(text="ultra rich"),
                    node(text="TRACED"),
                    node(text="35%"),
                    node(text="HACK", clickable=True),
                ),
                process_card(
                    "2236790",
                    "[0,0][0,0]",
                    "Antivirus Scan ",
                    "Lv.8",
                    "SUCCESS",
                    node(text="Completed 54m ago"),
                ),
            )
        )

        snapshot = parse_process_list(hierarchy)

        self.assertEqual(snapshot.active_task_count, 8)
        self.assertEqual(len(snapshot.processes), 2)
        self.assertEqual(len(snapshot.visible_processes), 1)
        running, completed = snapshot.processes
        self.assertEqual(running.process_id, "2241091")
        self.assertEqual(running.name, "Antivirus Scan")
        self.assertEqual(running.level, 8)
        self.assertEqual(running.state, ProcessState.IN_PROGRESS)
        self.assertEqual(running.progress_percent, 35)
        self.assertEqual(running.ip_address, "41.17.64.224")
        self.assertEqual(running.success_chance_percent, 74)
        self.assertEqual(running.game_tags, ("revenge", "ultra rich"))
        self.assertEqual(running.system_markers, ("TRACED",))
        self.assertEqual(running.available_actions, ("OPEN_TARGET", "HACK"))
        self.assertEqual(completed.state, ProcessState.COMPLETED)
        self.assertEqual(completed.completion_text, "Completed 54m ago")
        self.assertFalse(completed.visible)

    def test_infers_observed_filter_from_process_type(self) -> None:
        hierarchy = parse_ui_hierarchy(
            hierarchy_xml(
                process_card(
                    "2228339",
                    "[45,452][1035,798]",
                    "Firewall Bypass ",
                    "Lv.4",
                    "SUCCESS",
                ),
                process_card(
                    "2228342",
                    "[45,826][1035,1423]",
                    "Firewall Bypass ",
                    "Lv.4",
                    "SUCCESS",
                ),
            )
        )

        selected = infer_selected_process_filter(parse_process_list(hierarchy))

        self.assertEqual(selected, ProcessFilter.SHIELD)

    def test_locates_unlabelled_shield_and_lock_from_the_all_filter_anchor(self) -> None:
        hierarchy = parse_ui_hierarchy(
            hierarchy_xml(
                filter_button(45, 135),
                filter_button(143, 261, "ALL"),
                filter_button(270, 385),
                filter_button(393, 506),
                filter_button(514, 630),
                filter_button(635, 750),
                filter_button(759, 874),
                filter_button(945, 1035),
            )
        )

        tabs = locate_process_filter_tabs(hierarchy)

        self.assertEqual(tabs.element_for(ProcessFilter.ALL).bounds.center, (202, 375))
        self.assertEqual(
            tabs.element_for(ProcessFilter.SHIELD).bounds.center, (327, 375)
        )
        self.assertEqual(tabs.element_for(ProcessFilter.LOCK).bounds.center, (449, 375))
        self.assertEqual(
            tabs.element_for(ProcessFilter.ANTIVIRUS).bounds.center, (816, 375)
        )


if __name__ == "__main__":
    unittest.main()
