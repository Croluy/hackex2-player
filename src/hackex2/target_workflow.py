"""Complete, persisted servicing of one already connected target."""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import AddressValueError, IPv4Address

from hackex2.adb.device import ADBClient, ADBError
from hackex2.database import TargetDatabase, TargetEventType
from hackex2.states import ScreenState, detect_screen
from hackex2.target_dashboard import TargetDashboard, parse_target_dashboard
from hackex2.target_log_actions import (
    TargetLogClearStatus,
    TargetLogController,
)
from hackex2.target_wallet import (
    TargetWalletVariant,
    parse_target_wallet_authenticated,
    parse_target_wallet_login,
    parse_target_wallet_password_required,
)
from hackex2.target_wallet_actions import (
    TargetWalletController,
    WalletTransferStatus,
)


class TargetWorkflowError(ADBError):
    """Raised when a full target workflow cannot continue from verified state."""


@dataclass(frozen=True)
class TargetWorkflowResult:
    target: TargetDashboard
    initial_wallet_variant: TargetWalletVariant
    wallet_status: str
    initial_hot_wallet_crypto: int | None
    transferred_crypto: int
    log_status: TargetLogClearStatus
    disconnected: bool


class TargetWorkflow:
    def __init__(
        self,
        client: ADBClient,
        wallet: TargetWalletController,
        log: TargetLogController,
        database: TargetDatabase,
        *,
        event_handler=print,
    ) -> None:
        self.client = client
        self.wallet = wallet
        self.log = log
        self.database = database
        self.event_handler = event_handler

    def service_current_target(
        self,
        serial: str | None = None,
        *,
        expected_ip_address: str | None = None,
    ) -> TargetWorkflowResult:
        selected = self.client.select_device(serial)
        dashboard_dump = self.client.capture_ui_hierarchy(serial=selected.serial)
        state = detect_screen(dashboard_dump.hierarchy).state
        if state is not ScreenState.TARGET_DASHBOARD:
            raise TargetWorkflowError(
                f"expected TARGET_DASHBOARD, observed {state.value}"
            )
        target = parse_target_dashboard(
            dashboard_dump.hierarchy,
            expected_ip_address=expected_ip_address,
        )
        self.database.observe_dashboard(target)
        try:
            IPv4Address(target.ip_address)
        except AddressValueError as exc:
            raise TargetWorkflowError(
                "the target address is masked; provide the full IP observed on "
                "the matching process card before servicing this target"
            ) from exc
        self.event_handler(
            f"WORKFLOW TARGET: {target.ip_address} ({target.username})"
        )

        transition = self.wallet.open_from_dashboard(
            selected.serial, expected_ip_address=target.ip_address
        )
        wallet_dump = self.client.capture_ui_hierarchy(serial=selected.serial)
        wallet_state = detect_screen(wallet_dump.hierarchy).state
        if wallet_state is not transition.destination:
            raise TargetWorkflowError(
                "Wallet state changed between verified transition and inspection"
            )

        hot_wallet: int | None = None
        transferred = 0
        if wallet_state is ScreenState.TARGET_WALLET_PASSWORD_REQUIRED:
            snapshot = parse_target_wallet_password_required(wallet_dump.hierarchy)
            initial_variant = snapshot.variant
            self.database.record_wallet_observation(
                target.ip_address,
                password_known=False,
                protected=None,
                variant=snapshot.variant.value,
            )
            crack = self.wallet.start_password_crack(selected.serial)
            self.database.record_event(
                target.ip_address,
                TargetEventType.PASSWORD_CRACK_REQUESTED,
                metadata={"status": crack.status.value},
            )
            wallet_status = f"PASSWORD_CRACK_{crack.status.value}"
            self.wallet.return_to_dashboard(selected.serial)
        else:
            if wallet_state is ScreenState.TARGET_WALLET_LOGIN:
                login = parse_target_wallet_login(wallet_dump.hierarchy)
                initial_variant = login.variant
                self.wallet.login(selected.serial)
                authenticated_dump = self.client.capture_ui_hierarchy(
                    serial=selected.serial
                )
                if (
                    detect_screen(authenticated_dump.hierarchy).state
                    is not ScreenState.TARGET_WALLET_AUTHENTICATED
                ):
                    raise TargetWorkflowError(
                        "Wallet left the authenticated state before inspection"
                    )
                authenticated = parse_target_wallet_authenticated(
                    authenticated_dump.hierarchy
                )
            elif wallet_state is ScreenState.TARGET_WALLET_AUTHENTICATED:
                authenticated = parse_target_wallet_authenticated(
                    wallet_dump.hierarchy
                )
                initial_variant = authenticated.variant
            else:
                raise TargetWorkflowError(
                    f"unsupported Wallet destination {wallet_state.value}"
                )

            hot_wallet = authenticated.hot_wallet_crypto
            protected = authenticated.variant is TargetWalletVariant.PROTECTED
            self.database.record_wallet_observation(
                target.ip_address,
                password_known=True,
                protected=protected,
                variant=authenticated.variant.value,
            )
            transfer = self.wallet.transfer_available_crypto(selected.serial)
            wallet_status = transfer.status.value
            transferred = transfer.transferred_crypto
            if transfer.status is WalletTransferStatus.TRANSFERRED:
                self.database.record_crypto_transferred(
                    target.ip_address, transfer.transferred_crypto
                )
            self.wallet.return_to_dashboard(selected.serial)

        self.log.open_from_dashboard(
            selected.serial, expected_ip_address=target.ip_address
        )
        log_result = self.log.clear_and_save(selected.serial)
        self.database.record_log_observation(
            target.ip_address,
            protected=log_result.status is TargetLogClearStatus.SKIPPED_LOCKED,
            cleared=log_result.status is TargetLogClearStatus.CLEARED,
        )
        disconnect = self.log.disconnect(selected.serial)
        if disconnect.destination is not ScreenState.PROCESSES:
            raise TargetWorkflowError(
                f"disconnect produced {disconnect.destination.value}"
            )
        self.database.record_event(
            target.ip_address, TargetEventType.DISCONNECTED
        )
        return TargetWorkflowResult(
            target=target,
            initial_wallet_variant=initial_variant,
            wallet_status=wallet_status,
            initial_hot_wallet_crypto=hot_wallet,
            transferred_crypto=transferred,
            log_status=log_result.status,
            disconnected=True,
        )
