from __future__ import annotations

import unittest

from hackex2.adb.ui import parse_ui_hierarchy
from hackex2.target_wallet import (
    TargetWalletParseError,
    TargetWalletVariant,
    parse_target_wallet_login,
)

from tests.test_screen_detector import hierarchy_xml


def wallet_node(
    *, text: str, bounds: str, clickable: bool = False
) -> str:
    return (
        f"<node text='{text}' resource-id='' class='android.widget.TextView' "
        "package='net.cncapps.hackex2' content-desc='' "
        f"clickable='{'true' if clickable else 'false'}' enabled='true' "
        f"bounds='{bounds}' />"
    )


def wallet_login_xml(*, login_username: str = "nebthepleb") -> str:
    return hierarchy_xml(
        wallet_node(text="&lt; back", bounds="[45,137][143,267]", clickable=True),
        wallet_node(
            text="DISCONNECT", bounds="[810,168][1035,236]", clickable=True
        ),
        wallet_node(text="// CRYPTO WALLET", bounds="[45,295][1035,340]"),
        wallet_node(text="nebthepleb&apos;s wallet", bounds="[45,348][1035,393]"),
        wallet_node(text="WALLET LOGIN", bounds="[191,511][438,556]"),
        wallet_node(text="USERNAME", bounds="[90,618][202,646]"),
        wallet_node(text=login_username, bounds="[90,655][990,756]"),
        wallet_node(text="PASSWORD", bounds="[90,798][202,826]"),
        wallet_node(text="*********", bounds="[90,835][990,936]"),
        wallet_node(text="LOGIN &gt;", bounds="[90,975][990,1116]", clickable=True),
    )


class TargetWalletParserTest(unittest.TestCase):
    def test_parses_login_branch_without_exposing_password(self) -> None:
        wallet = parse_target_wallet_login(
            parse_ui_hierarchy(wallet_login_xml())
        )

        self.assertEqual(wallet.variant, TargetWalletVariant.LOGIN)
        self.assertEqual(wallet.owner_username, "nebthepleb")
        self.assertEqual(wallet.login_username, "nebthepleb")
        self.assertEqual(wallet.masked_password_length, 9)
        self.assertEqual(
            wallet.available_actions, ("BACK", "DISCONNECT", "LOGIN")
        )

    def test_rejects_mismatched_prefilled_username(self) -> None:
        with self.assertRaisesRegex(
            TargetWalletParseError, "owner and prefilled login username do not match"
        ):
            parse_target_wallet_login(
                parse_ui_hierarchy(wallet_login_xml(login_username="other-user"))
            )


if __name__ == "__main__":
    unittest.main()
