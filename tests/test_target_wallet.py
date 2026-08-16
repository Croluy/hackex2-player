from __future__ import annotations

import unittest

from hackex2.adb.ui import parse_ui_hierarchy
from hackex2.target_wallet import (
    TargetWalletParseError,
    TargetWalletVariant,
    parse_target_wallet_authenticated,
    parse_target_wallet_login,
    parse_wallet_transfer_confirmation,
)

from tests.test_screen_detector import hierarchy_xml


def wallet_node(
    *,
    text: str,
    bounds: str,
    clickable: bool = False,
    enabled: bool = True,
) -> str:
    return (
        f"<node text='{text}' resource-id='' class='android.widget.TextView' "
        "package='net.cncapps.hackex2' content-desc='' "
        f"clickable='{'true' if clickable else 'false'}' "
        f"enabled='{'true' if enabled else 'false'}' "
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

    def test_parses_transferable_authenticated_wallet(self) -> None:
        wallet = parse_target_wallet_authenticated(
            parse_ui_hierarchy(authenticated_wallet_xml())
        )

        self.assertEqual(wallet.variant, TargetWalletVariant.TRANSFERABLE)
        self.assertEqual(wallet.owner_username, "nebthepleb")
        self.assertEqual(wallet.wallet_address, "hx5f0972abe7b435d206f04b55759b7f")
        self.assertEqual(wallet.hot_wallet_crypto, 201)
        self.assertEqual(wallet.cold_storage_crypto, 3127)
        self.assertIsNone(wallet.transfer_amount)
        self.assertEqual(wallet.protection_evidence, ())

    def test_classifies_wallet_shield_only_when_controls_are_inactive(self) -> None:
        wallet = parse_target_wallet_authenticated(
            parse_ui_hierarchy(authenticated_wallet_xml(protected=True))
        )

        self.assertEqual(wallet.variant, TargetWalletVariant.PROTECTED)
        self.assertEqual(wallet.hot_wallet_crypto, 201)
        self.assertEqual(
            wallet.protection_evidence,
            ("WALLET SHIELD ACTIVE", "TRANSFER BLOCKED"),
        )

    def test_parses_amount_agnostic_transfer_confirmation(self) -> None:
        hierarchy = parse_ui_hierarchy(
            hierarchy_xml(
                wallet_node(
                    text="[OK] Transferred 12,345 Crypto to your wallet.",
                    bounds="[45,1510][1035,1570]",
                )
            )
        )

        self.assertEqual(parse_wallet_transfer_confirmation(hierarchy), 12345)

    def test_classifies_confirmed_zero_balance_as_transferred(self) -> None:
        wallet = parse_target_wallet_authenticated(
            parse_ui_hierarchy(
                authenticated_wallet_xml(
                    hot_balance=0,
                    form_enabled=False,
                    confirmation="[OK] Transferred 215 Crypto to your wallet.",
                )
            )
        )

        self.assertEqual(wallet.variant, TargetWalletVariant.TRANSFERRED)
        self.assertEqual(wallet.hot_wallet_crypto, 0)


def authenticated_wallet_xml(
    *,
    protected: bool = False,
    amount: str = "",
    transfer_enabled: bool = False,
    hot_balance: int = 201,
    confirmation: str | None = None,
    form_enabled: bool = True,
) -> str:
    protection = "SWALLET SHIELD ACTIVE" if protected else ""
    controls = (
        wallet_node(
            text="MAX",
            bounds="[45,1369][196,1499]",
            clickable=True,
            enabled=form_enabled and not protected,
        )
        + wallet_node(
            text="TRANSFER TO MY WALLET",
            bounds="[227,1369][1035,1499]",
            clickable=True,
            enabled=transfer_enabled and form_enabled and not protected,
        )
    )
    extra = (
        wallet_node(text="TRANSFER BLOCKED", bounds="[45,1060][1035,1100]")
        if protected
        else ""
    )
    confirmation_node = (
        wallet_node(text=confirmation, bounds="[45,1510][1035,1570]")
        if confirmation is not None
        else ""
    )
    amount_node = (
        f"<node text='{amount}' resource-id='steal-amount' "
        "class='android.widget.EditText' package='net.cncapps.hackex2' "
        f"content-desc='' clickable='true' "
        f"enabled='{'true' if form_enabled else 'false'}' "
        "bounds='[45,1203][1035,1330]' />"
    )
    return hierarchy_xml(
        wallet_node(text="&lt; back", bounds="[45,137][143,267]", clickable=True),
        wallet_node(
            text="DISCONNECT", bounds="[810,168][1035,236]", clickable=True
        ),
        wallet_node(text="// CRYPTO WALLET", bounds="[45,295][1035,340]"),
        wallet_node(text="nebthepleb&apos;s wallet", bounds="[45,348][1035,393]"),
        wallet_node(text="WALLET ADDRESS", bounds="[78,458][292,489]"),
        wallet_node(
            text="hx5f0972abe7b435d206f04b55759b7f",
            bounds="[78,497][601,537]",
        ),
        wallet_node(
            text=(
                f"HHOT WALLET{hot_balance:,} Crypto{protection}"
                "CCOLD STORAGESecured3,127 Crypto/ 8,841 max"
            ),
            bounds="[45,604][1035,1006]",
        ),
        wallet_node(text="// External Transfer", bounds="[45,1060][1035,1099]"),
        amount_node,
        controls,
        extra,
        confirmation_node,
    )


if __name__ == "__main__":
    unittest.main()
