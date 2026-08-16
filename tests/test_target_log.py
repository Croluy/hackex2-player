from __future__ import annotations

import unittest

from hackex2.adb.ui import parse_ui_hierarchy
from hackex2.target_log import TargetLogVariant, parse_target_log

from tests.test_screen_detector import hierarchy_xml, node


def target_log_xml(
    *,
    content: str = "some log data",
    save_enabled: bool = False,
    editor_enabled: bool = True,
    focused: bool = False,
    locked: bool = False,
    keyboard_visible: bool = False,
) -> str:
    lock_node = (
        node(text="[LOCKED] This device LOG is locked") if locked else ""
    )
    editor_bottom = 1400 if keyboard_visible else 2250
    editor = (
        f"<node text='{content}' resource-id='' class='android.widget.EditText' "
        "package='net.cncapps.hackex2' content-desc='' clickable='true' "
        f"enabled='{'true' if editor_enabled else 'false'}' "
        f"focused='{'true' if focused else 'false'}' "
        f"bounds='[45,455][1080,{editor_bottom}]' />"
    )
    save = (
        "<node text='SAVE' resource-id='' class='android.widget.Button' "
        "package='net.cncapps.hackex2' content-desc='' clickable='true' "
        f"enabled='{'true' if save_enabled else 'false'}' "
        "bounds='[869,233][1035,340]' />"
    )
    keyboard = (
        "<node text='' resource-id='' class='android.inputmethodservice.Keyboard' "
        "package='com.samsung.android.honeyboard' content-desc='' "
        "clickable='false' enabled='true' bounds='[0,1400][1080,2340]' />"
        if keyboard_visible
        else ""
    )
    return hierarchy_xml(
        node(text="&lt; back", clickable=True),
        node(text="// VICTIM LOG"),
        node(text="DISCONNECT", clickable=True),
        save,
        editor,
        lock_node,
        keyboard,
    )


class TargetLogParserTest(unittest.TestCase):
    def test_parses_editable_log_without_exposing_its_content(self) -> None:
        log = parse_target_log(parse_ui_hierarchy(target_log_xml()))

        self.assertEqual(log.variant, TargetLogVariant.EDITABLE)
        self.assertTrue(log.has_content)
        self.assertEqual(log.content_length, len("some log data"))
        self.assertFalse(log.save_enabled)

    def test_parses_locked_log_with_disabled_controls(self) -> None:
        log = parse_target_log(
            parse_ui_hierarchy(
                target_log_xml(locked=True, editor_enabled=False)
            )
        )

        self.assertEqual(log.variant, TargetLogVariant.LOCKED)
        self.assertTrue(log.lock_evidence)

    def test_parses_empty_saved_log(self) -> None:
        log = parse_target_log(parse_ui_hierarchy(target_log_xml(content="")))

        self.assertEqual(log.variant, TargetLogVariant.SAVED)
        self.assertFalse(log.has_content)


if __name__ == "__main__":
    unittest.main()
