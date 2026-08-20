"""Command-line interface for small, verifiable automation milestones."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from hackex2.adb.device import ADBClient, ADBError
from hackex2.adb.input import HumanizedInput
from hackex2.config import (
    ConfigurationError,
    InputSettings,
    NavigationSettings,
    load_env_file,
)
from hackex2.database import (
    DatabaseError,
    TargetDatabase,
    TargetEventType,
)
from hackex2.navigation import NavigationError, Navigator
from hackex2.processes import (
    ProcessFilter,
    ProcessParseError,
    infer_selected_process_filter,
    parse_process_list,
)
from hackex2.process_filters import ProcessFilterController, ProcessFilterError
from hackex2.process_target_actions import (
    ProcessTargetActionError,
    ProcessTargetController,
    ProcessTargetStatus,
)
from hackex2.process_scroller import (
    ProcessScrollError,
    ProcessScroller,
    ScrollDirection,
)
from hackex2.states import ScreenState, detect_screen
from hackex2.target_dashboard import (
    TargetDashboardParseError,
    parse_target_dashboard,
)
from hackex2.target_log_actions import TargetLogActionError, TargetLogController
from hackex2.target_log import TargetLogParseError, parse_target_log
from hackex2.target_wallet import (
    TargetWalletParseError,
    parse_target_wallet_authenticated,
    parse_target_wallet_login,
    parse_target_wallet_password_required,
)
from hackex2.target_wallet_actions import (
    TargetWalletActionError,
    TargetWalletController,
)
from hackex2.target_workflow import TargetWorkflow, TargetWorkflowError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hackex2")
    subparsers = parser.add_subparsers(dest="command", required=True)

    device_parser = subparsers.add_parser(
        "device", help="inspect the connected Android device"
    )
    add_adb_arguments(device_parser)

    database_parser = subparsers.add_parser(
        "database-status", help="initialize and inspect the local target database"
    )
    add_database_argument(database_parser)

    screenshot_parser = subparsers.add_parser(
        "screenshot", help="capture and verify a device screenshot"
    )
    add_adb_arguments(screenshot_parser)
    screenshot_parser.add_argument(
        "--output",
        type=Path,
        help="PNG destination; defaults to diagnostics with a timestamp",
    )

    ui_parser = subparsers.add_parser(
        "ui-dump", help="capture and parse the Android UI hierarchy"
    )
    add_adb_arguments(ui_parser)
    ui_parser.add_argument(
        "--output",
        type=Path,
        help="XML destination; defaults to diagnostics with a timestamp",
    )

    detect_parser = subparsers.add_parser(
        "detect-screen", help="identify the current HackEx2 screen conservatively"
    )
    add_adb_arguments(detect_parser)
    detect_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("diagnostics"),
        help="directory for diagnostic UI data and unknown-screen screenshots",
    )

    navigate_parser = subparsers.add_parser(
        "navigate", help="navigate between known screens and verify the destination"
    )
    add_adb_arguments(navigate_parser)
    navigate_parser.add_argument(
        "destination",
        choices=("home", "processes"),
        help="known screen to open",
    )

    processes_parser = subparsers.add_parser(
        "inspect-processes", help="parse process cards from the current screen"
    )
    add_adb_arguments(processes_parser)
    processes_parser.add_argument(
        "--all-exposed",
        action="store_true",
        help="include zero-sized process cards exposed outside the viewport",
    )

    target_parser = subparsers.add_parser(
        "inspect-target", help="parse the currently connected target dashboard"
    )
    add_adb_arguments(target_parser)
    target_parser.add_argument(
        "--expected-ip",
        help="full process IP used only to resolve a matching masked dashboard IP",
    )

    process_target_parser = subparsers.add_parser(
        "open-process-target",
        help="open one completed process and verify the target dashboard IP",
    )
    add_adb_arguments(process_target_parser)
    add_database_argument(process_target_parser)
    selector = process_target_parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--process-id", help="exact visible process identifier")
    selector.add_argument("--ip", dest="ip_address", help="exact visible target IPv4")

    service_target_parser = subparsers.add_parser(
        "service-target",
        help="service Wallet and Log for the currently connected target",
    )
    add_adb_arguments(service_target_parser)
    add_database_argument(service_target_parser)
    service_target_parser.add_argument(
        "--expected-ip",
        help="full process IP used to resolve a matching masked dashboard IP",
    )

    service_process_parser = subparsers.add_parser(
        "service-process-target",
        help="open and fully service one exact completed process target",
    )
    add_adb_arguments(service_process_parser)
    add_database_argument(service_process_parser)
    service_selector = service_process_parser.add_mutually_exclusive_group(
        required=True
    )
    service_selector.add_argument("--process-id")
    service_selector.add_argument("--ip", dest="ip_address")

    wallet_parser = subparsers.add_parser(
        "inspect-target-wallet",
        help="classify and parse the currently open target-wallet branch",
    )
    add_adb_arguments(wallet_parser)

    transfer_parser = subparsers.add_parser(
        "transfer-target-wallet",
        help="conditionally transfer a verified target hot-wallet balance",
    )
    add_adb_arguments(transfer_parser)

    wallet_back_parser = subparsers.add_parser(
        "target-wallet-back",
        help="return from a verified target Wallet to its dashboard",
    )
    add_adb_arguments(wallet_back_parser)

    open_wallet_parser = subparsers.add_parser(
        "open-target-wallet",
        help="open Wallet from a verified target dashboard",
    )
    add_adb_arguments(open_wallet_parser)
    open_wallet_parser.add_argument("--expected-ip")

    login_wallet_parser = subparsers.add_parser(
        "login-target-wallet",
        help="submit a verified prefilled target-wallet Login once",
    )
    add_adb_arguments(login_wallet_parser)

    crack_wallet_parser = subparsers.add_parser(
        "crack-target-wallet-password",
        help="start a verified normal password crack without consuming an Exploit Kit",
    )
    add_adb_arguments(crack_wallet_parser)

    open_log_parser = subparsers.add_parser(
        "open-target-log",
        help="open Log from a verified target dashboard",
    )
    add_adb_arguments(open_log_parser)
    open_log_parser.add_argument("--expected-ip")

    inspect_log_parser = subparsers.add_parser(
        "inspect-target-log",
        help="classify the currently open target Log",
    )
    add_adb_arguments(inspect_log_parser)

    clear_log_parser = subparsers.add_parser(
        "clear-target-log",
        help="clear and save an editable target Log",
    )
    add_adb_arguments(clear_log_parser)

    disconnect_log_parser = subparsers.add_parser(
        "disconnect-target-log",
        help="disconnect only from a saved or locked target Log",
    )
    add_adb_arguments(disconnect_log_parser)

    filter_parser = subparsers.add_parser(
        "process-filter", help="select and verify a typed process filter"
    )
    add_adb_arguments(filter_parser)
    filter_parser.add_argument(
        "filter",
        choices=("shield", "lock", "antivirus"),
        help="identifiable process filter to select",
    )

    scroll_parser = subparsers.add_parser(
        "scroll-processes", help="perform one verified process-list scroll"
    )
    add_adb_arguments(scroll_parser)
    scroll_parser.add_argument(
        "direction",
        choices=("up", "down"),
        help="up reveals later cards; down returns toward earlier cards",
    )
    return parser


def add_adb_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--serial",
        default=os.getenv("ANDROID_SERIAL") or None,
        help="ADB device serial; defaults to ANDROID_SERIAL",
    )
    parser.add_argument(
        "--adb-path",
        default="adb",
        help="path to the adb executable",
    )


def add_database_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--database",
        type=Path,
        help="local SQLite path; defaults to HACKEX2_DB_PATH or data/hackex2.sqlite3",
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        load_env_file()
    except ConfigurationError as exc:
        print(f"Configuration failed: {exc}", file=sys.stderr)
        return 1
    args = build_parser().parse_args(argv)

    if args.command == "database-status":
        database = TargetDatabase(args.database)
        try:
            version, targets, events = database.status()
        except (DatabaseError, OSError, ValueError) as exc:
            print(f"Database check failed: {exc}", file=sys.stderr)
            return 1
        print(f"Database: {database.path}")
        print(f"Schema version: {version}")
        print(f"Known targets: {targets}")
        print(f"History events: {events}")
        return 0

    if args.command == "device":
        try:
            device = ADBClient(adb_path=args.adb_path).inspect_device(args.serial)
        except (ADBError, OSError) as exc:
            print(f"Device check failed: {exc}", file=sys.stderr)
            return 1

        print(f"Device connected: {device.serial}")
        print(f"Model: {device.model}")
        print(f"Resolution: {device.width}x{device.height}")
        return 0


    if args.command == "screenshot":
        output = args.output or Path(
            "diagnostics", f"screenshot-{datetime.now():%Y%m%d-%H%M%S}.png"
        )
        try:
            screenshot = ADBClient(adb_path=args.adb_path).capture_screenshot(
                output, args.serial
            )
        except (ADBError, OSError) as exc:
            print(f"Screenshot failed: {exc}", file=sys.stderr)
            return 1

        print(f"Screenshot saved: {screenshot.path}")
        print(f"Device: {screenshot.serial}")
        print(f"Resolution: {screenshot.width}x{screenshot.height}")
        print(f"Bytes: {screenshot.byte_count}")
        return 0

    if args.command == "ui-dump":
        output = args.output or Path(
            "diagnostics", f"ui-hierarchy-{datetime.now():%Y%m%d-%H%M%S}.xml"
        )
        try:
            dump = ADBClient(adb_path=args.adb_path).capture_ui_hierarchy(
                output, args.serial
            )
        except (ADBError, OSError, ValueError) as exc:
            print(f"UI hierarchy capture failed: {exc}", file=sys.stderr)
            return 1

        packages = ", ".join(dump.hierarchy.packages) or "unknown"
        print(f"UI hierarchy saved: {dump.path}")
        print(f"Device: {dump.serial}")
        print(f"Packages: {packages}")
        print(f"Elements: {len(dump.hierarchy.elements)}")
        print(f"Clickable elements: {len(dump.hierarchy.clickable_elements)}")
        return 0

    if args.command == "detect-screen":
        timestamp = f"{datetime.now():%Y%m%d-%H%M%S}"
        ui_path = args.output_dir / f"screen-{timestamp}.xml"
        client = ADBClient(adb_path=args.adb_path)
        try:
            dump = client.capture_ui_hierarchy(ui_path, args.serial)
            detection = detect_screen(dump.hierarchy)
        except (ADBError, OSError, ValueError) as exc:
            print(f"Screen detection failed: {exc}", file=sys.stderr)
            return 1

        print(f"STATE: {detection.state.value}")
        print(f"Confidence: {detection.confidence:.2f}")
        print(f"Evidence: {', '.join(detection.evidence) or 'none'}")
        print(f"UI hierarchy: {dump.path}")

        if detection.state is ScreenState.UNKNOWN_SCREEN:
            screenshot_path = args.output_dir / f"unknown-{timestamp}.png"
            try:
                screenshot = client.capture_screenshot(screenshot_path, args.serial)
            except (ADBError, OSError) as exc:
                print(f"Unknown-screen screenshot failed: {exc}", file=sys.stderr)
                return 1
            print(
                "Missing evidence: "
                f"{', '.join(detection.missing_evidence) or 'not classified'}"
            )
            print(f"Diagnostic screenshot: {screenshot.path}")
            return 2
        return 0

    if args.command == "navigate":
        destination = {
            "home": ScreenState.HOME,
            "processes": ScreenState.PROCESSES,
        }[args.destination]
        client = ADBClient(adb_path=args.adb_path)
        try:
            navigator = Navigator(
                client,
                HumanizedInput(InputSettings.from_environment()),
                NavigationSettings.from_environment(),
                event_handler=print,
            )
            result = navigator.navigate_to(destination, args.serial)
        except (ADBError, ConfigurationError, NavigationError, OSError, ValueError) as exc:
            print(f"Navigation failed: {exc}", file=sys.stderr)
            _save_navigation_failure_diagnostics(client, args.serial)
            return 1

        print(f"STATE: {result.source.value}")
        if result.tap is None:
            print(f"Already at destination: {result.destination.value}")
        else:
            print(
                f"Tap: ({result.tap.x}, {result.tap.y}) after "
                f"{result.tap.delay_ms} ms"
            )
            print(f"Verified after observations: {result.observations}")
            print(f"Action attempts: {result.attempts}")
        print(f"STATE: {result.destination.value}")
        return 0

    if args.command == "inspect-processes":
        timestamp = f"{datetime.now():%Y%m%d-%H%M%S}"
        client = ADBClient(adb_path=args.adb_path)
        try:
            dump = client.capture_ui_hierarchy(
                Path("diagnostics", f"processes-{timestamp}.xml"), args.serial
            )
            detection = detect_screen(dump.hierarchy)
            if detection.state is not ScreenState.PROCESSES:
                raise ProcessParseError(
                    f"expected PROCESSES, observed {detection.state.value}"
                )
            snapshot = parse_process_list(dump.hierarchy)
        except (ADBError, OSError, ProcessParseError, ValueError) as exc:
            print(f"Process inspection failed: {exc}", file=sys.stderr)
            return 1

        processes = (
            snapshot.processes if args.all_exposed else snapshot.visible_processes
        )
        active_count = (
            str(snapshot.active_task_count)
            if snapshot.active_task_count is not None
            else "unknown"
        )
        print("STATE: PROCESSES")
        print(f"Inferred filter: {infer_selected_process_filter(snapshot).value}")
        print(f"Active tasks: {active_count}")
        print(f"Process cards exposed: {len(snapshot.processes)}")
        print(f"Process cards visible: {len(snapshot.visible_processes)}")
        for process in processes:
            level = f"Lv.{process.level}" if process.level is not None else "level unknown"
            progress = (
                f"{process.progress_percent}%"
                if process.progress_percent is not None
                else "progress unknown"
            )
            visibility = "visible" if process.visible else "outside viewport"
            print(
                f"Process {process.process_id}: {process.name or 'unknown'} | "
                f"{level} | {process.state.value} | {progress} | {visibility}"
            )
            details = []
            if process.ip_address is not None:
                details.append(f"IP {process.ip_address}")
            if process.success_chance_percent is not None:
                details.append(f"chance {process.success_chance_percent}%")
            if process.game_tags:
                details.append(f"tags {', '.join(process.game_tags)}")
            if process.system_markers:
                details.append(f"markers {', '.join(process.system_markers)}")
            if process.available_actions:
                details.append(f"actions {', '.join(process.available_actions)}")
            if details:
                print(f"  {' | '.join(details)}")
        print(f"UI hierarchy: {dump.path}")
        return 0

    if args.command == "inspect-target":
        timestamp = f"{datetime.now():%Y%m%d-%H%M%S}"
        client = ADBClient(adb_path=args.adb_path)
        try:
            dump = client.capture_ui_hierarchy(
                Path("diagnostics", f"target-dashboard-{timestamp}.xml"), args.serial
            )
            detection = detect_screen(dump.hierarchy)
            if detection.state is not ScreenState.TARGET_DASHBOARD:
                raise TargetDashboardParseError(
                    f"expected TARGET_DASHBOARD, observed {detection.state.value}"
                )
            target = parse_target_dashboard(
                dump.hierarchy, expected_ip_address=args.expected_ip
            )
        except (ADBError, OSError, TargetDashboardParseError, ValueError) as exc:
            print(f"Target inspection failed: {exc}", file=sys.stderr)
            return 1

        crew = f" [{target.crew_tag}]" if target.crew_tag is not None else ""
        print("STATE: TARGET_DASHBOARD")
        print(f"Identity: {target.username}{crew}")
        print(
            f"Level: {target.level} | Reputation: {target.reputation} | "
            f"Score: {target.score}"
        )
        print(
            f"XP: {target.xp_current} / {target.xp_required} "
            f"({target.xp_percent}%)"
        )
        print(f"IP: {target.ip_address}")
        print(f"Device: {target.device} | Network: {target.network}")
        print(
            f"Firewall: Lv.{target.firewall_level} | "
            f"Encryptor: Lv.{target.encryptor_level}"
        )
        print(f"Available actions: {', '.join(target.available_actions)}")
        print(f"UI hierarchy: {dump.path}")
        return 0

    if args.command == "open-process-target":
        client = ADBClient(adb_path=args.adb_path)
        try:
            controller = ProcessTargetController(
                client,
                HumanizedInput(InputSettings.from_environment()),
                NavigationSettings.from_environment(),
                event_handler=print,
            )
            result = controller.open_completed_target(
                process_id=args.process_id,
                ip_address=args.ip_address,
                serial=args.serial,
            )
            database = TargetDatabase(args.database)
            database.observe_process_target(result.process)
            database.record_event(
                result.process.ip_address,
                TargetEventType.HACK_ATTEMPTED,
                metadata={"process_id": result.process.process_id},
            )
            if result.status is ProcessTargetStatus.OPENED_TARGET:
                if result.target is None:
                    raise ProcessTargetActionError(
                        "opened-target result is missing dashboard data"
                    )
                database.observe_dashboard(
                    result.target, game_tags=result.process.game_tags
                )
                database.record_hack_verified(result.target.ip_address)
            else:
                database.record_event(
                    result.process.ip_address,
                    TargetEventType.HACK_RETURNED_HOME,
                    metadata={"process_id": result.process.process_id},
                )
        except (
            ADBError,
            ConfigurationError,
            DatabaseError,
            OSError,
            ProcessParseError,
            ProcessTargetActionError,
            TargetDashboardParseError,
            ValueError,
        ) as exc:
            print(f"Process target action failed: {exc}", file=sys.stderr)
            return 1
        print(f"Process: {result.process.process_id}")
        print(f"Process target result: {result.status.value}")
        print(f"Target IP: {result.process.ip_address}")
        if result.target is not None:
            print(f"Target username: {result.target.username}")
        print(f"Verified after observations: {result.observations}")
        state = (
            ScreenState.TARGET_DASHBOARD
            if result.status is ProcessTargetStatus.OPENED_TARGET
            else ScreenState.HOME
        )
        print(f"STATE: {state.value}")
        print(f"Database: {database.path}")
        return 0

    if args.command in {"service-target", "service-process-target"}:
        client = ADBClient(adb_path=args.adb_path)
        inputs = HumanizedInput(InputSettings.from_environment())
        settings = NavigationSettings.from_environment()
        database = TargetDatabase(args.database)
        expected_ip = getattr(args, "expected_ip", None)
        try:
            if args.command == "service-process-target":
                process_controller = ProcessTargetController(
                    client, inputs, settings, event_handler=print
                )
                process_result = process_controller.open_completed_target(
                    process_id=args.process_id,
                    ip_address=args.ip_address,
                    serial=args.serial,
                )
                process_ip = process_result.process.ip_address
                if process_ip is None:
                    raise ProcessTargetActionError(
                        "verified process result has no target IP"
                    )
                database.observe_process_target(process_result.process)
                database.record_event(
                    process_ip,
                    TargetEventType.HACK_ATTEMPTED,
                    metadata={"process_id": process_result.process.process_id},
                )
                if process_result.status is ProcessTargetStatus.RETURNED_HOME:
                    database.record_event(
                        process_ip,
                        TargetEventType.HACK_RETURNED_HOME,
                        metadata={"process_id": process_result.process.process_id},
                    )
                    print("Process target result: RETURNED_HOME")
                    print(f"Target IP: {process_ip}")
                    print("No retry performed")
                    print(f"Database: {database.path}")
                    return 0
                if process_result.target is None:
                    raise ProcessTargetActionError(
                        "opened process target has no parsed dashboard"
                    )
                database.observe_dashboard(
                    process_result.target,
                    game_tags=process_result.process.game_tags,
                )
                database.record_hack_verified(process_ip)
                expected_ip = process_ip

            wallet = TargetWalletController(
                client, inputs, settings, event_handler=print
            )
            log = TargetLogController(
                client, inputs, settings, event_handler=print
            )
            workflow = TargetWorkflow(
                client, wallet, log, database, event_handler=print
            )
            result = workflow.service_current_target(
                args.serial, expected_ip_address=expected_ip
            )
        except (
            ADBError,
            ConfigurationError,
            DatabaseError,
            OSError,
            ProcessParseError,
            ProcessTargetActionError,
            TargetDashboardParseError,
            TargetLogActionError,
            TargetLogParseError,
            TargetWalletActionError,
            TargetWalletParseError,
            TargetWorkflowError,
            ValueError,
        ) as exc:
            print(f"Target workflow failed: {exc}", file=sys.stderr)
            return 1
        print(f"Target: {result.target.username} ({result.target.ip_address})")
        print(f"Initial Wallet branch: {result.initial_wallet_variant.value}")
        print(f"Wallet result: {result.wallet_status}")
        if result.initial_hot_wallet_crypto is not None:
            print(
                f"Initial hot wallet: {result.initial_hot_wallet_crypto} Crypto"
            )
        print(f"Transferred: {result.transferred_crypto} Crypto")
        print(f"Log result: {result.log_status.value}")
        print(f"Disconnected: {'yes' if result.disconnected else 'no'}")
        print(f"Database: {database.path}")
        print("STATE: PROCESSES")
        return 0

    if args.command == "inspect-target-wallet":
        timestamp = f"{datetime.now():%Y%m%d-%H%M%S}"
        client = ADBClient(adb_path=args.adb_path)
        try:
            dump = client.capture_ui_hierarchy(
                Path("diagnostics", f"target-wallet-{timestamp}.xml"), args.serial
            )
            detection = detect_screen(dump.hierarchy)
            if detection.state is ScreenState.TARGET_WALLET_PASSWORD_REQUIRED:
                wallet = parse_target_wallet_password_required(dump.hierarchy)
            elif detection.state is ScreenState.TARGET_WALLET_LOGIN:
                wallet = parse_target_wallet_login(dump.hierarchy)
            elif detection.state is ScreenState.TARGET_WALLET_AUTHENTICATED:
                wallet = parse_target_wallet_authenticated(dump.hierarchy)
            else:
                raise TargetWalletParseError(
                    "wallet branch is not recognized: "
                    f"observed {detection.state.value}"
                )
        except (ADBError, OSError, TargetWalletParseError, ValueError) as exc:
            print(f"Target wallet inspection failed: {exc}", file=sys.stderr)
            return 1

        print(f"STATE: {detection.state.value}")
        print(f"Wallet branch: {wallet.variant.value}")
        print(f"Owner: {wallet.owner_username}")
        if detection.state is ScreenState.TARGET_WALLET_PASSWORD_REQUIRED:
            print(f"Prefilled username: {wallet.login_username}")
            print(
                "Password: hidden and encrypted "
                f"at Lv.{wallet.encryptor_level} "
                f"({wallet.masked_password_length} mask characters)"
            )
            print(f"Exploit Kits available: {wallet.exploit_kit_count}")
            print(f"Available actions: {', '.join(wallet.available_actions)}")
        elif detection.state is ScreenState.TARGET_WALLET_LOGIN:
            print(f"Prefilled username: {wallet.login_username}")
            print(
                "Password: masked and present "
                f"({wallet.masked_password_length} mask characters)"
            )
            print(f"Available actions: {', '.join(wallet.available_actions)}")
        else:
            print(f"Wallet address: {wallet.wallet_address}")
            print(f"Hot wallet: {wallet.hot_wallet_crypto} Crypto")
            cold = (
                f"{wallet.cold_storage_crypto} Crypto"
                if wallet.cold_storage_crypto is not None
                else "unknown"
            )
            print(f"Cold storage: {cold}")
            print(
                "Protection evidence: "
                f"{', '.join(wallet.protection_evidence) or 'none'}"
            )
        print(f"UI hierarchy: {dump.path}")
        return 0

    if args.command in {
        "transfer-target-wallet",
        "target-wallet-back",
        "open-target-wallet",
        "login-target-wallet",
        "crack-target-wallet-password",
    }:
        controller = TargetWalletController(
            ADBClient(adb_path=args.adb_path),
            HumanizedInput(InputSettings.from_environment()),
            NavigationSettings.from_environment(),
            event_handler=print,
        )
        try:
            if args.command == "transfer-target-wallet":
                result = controller.transfer_available_crypto(args.serial)
                print(f"Wallet result: {result.status.value}")
                print(f"Initial hot wallet: {result.initial_balance} Crypto")
                print(f"Transferred: {result.transferred_crypto} Crypto")
                final = (
                    f"{result.final_balance} Crypto"
                    if result.final_balance is not None
                    else "confirmed by matching success message"
                )
                print(f"Final hot wallet: {final}")
            elif args.command == "target-wallet-back":
                result = controller.return_to_dashboard(args.serial)
                print(f"STATE: {result.source.value}")
                print(f"Verified after observations: {result.observations}")
                print(f"Action attempts: {result.attempts}")
                print(f"STATE: {result.destination.value}")
            elif args.command == "open-target-wallet":
                result = controller.open_from_dashboard(
                    args.serial, expected_ip_address=args.expected_ip
                )
                print(f"STATE: {result.source.value}")
                print(f"Verified after observations: {result.observations}")
                print(f"Action attempts: {result.attempts}")
                print(f"STATE: {result.destination.value}")
            elif args.command == "login-target-wallet":
                result = controller.login(args.serial)
                print(f"STATE: {result.source.value}")
                print(f"Verified after observations: {result.observations}")
                print(f"Action attempts: {result.attempts}")
                print(f"STATE: {result.destination.value}")
            else:
                result = controller.start_password_crack(args.serial)
                print(f"Password crack result: {result.status.value}")
                print(f"STATE: {result.source.value}")
                print(f"Verified after observations: {result.observations}")
                print(f"Action attempts: {result.attempts}")
                print(f"STATE: {result.destination.value}")
        except (
            ADBError,
            ConfigurationError,
            OSError,
            TargetWalletActionError,
            TargetWalletParseError,
            ValueError,
        ) as exc:
            print(f"Target wallet action failed: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.command == "open-target-log":
        controller = TargetLogController(
            ADBClient(adb_path=args.adb_path),
            HumanizedInput(InputSettings.from_environment()),
            NavigationSettings.from_environment(),
            event_handler=print,
        )
        try:
            result = controller.open_from_dashboard(
                args.serial, expected_ip_address=args.expected_ip
            )
        except (
            ADBError,
            ConfigurationError,
            OSError,
            TargetDashboardParseError,
            TargetLogActionError,
            ValueError,
        ) as exc:
            print(f"Target Log action failed: {exc}", file=sys.stderr)
            return 1
        print(f"STATE: {result.source.value}")
        print(f"Verified after observations: {result.observations}")
        print(f"Action attempts: {result.attempts}")
        print(f"STATE: {result.destination.value}")
        return 0

    if args.command == "inspect-target-log":
        timestamp = f"{datetime.now():%Y%m%d-%H%M%S}"
        client = ADBClient(adb_path=args.adb_path)
        try:
            dump = client.capture_ui_hierarchy(
                Path("diagnostics", f"target-log-{timestamp}.xml"), args.serial
            )
            detection = detect_screen(dump.hierarchy)
            if detection.state is not ScreenState.TARGET_LOG:
                raise TargetLogParseError(
                    f"expected TARGET_LOG, observed {detection.state.value}"
                )
            log = parse_target_log(dump.hierarchy)
        except (ADBError, OSError, TargetLogParseError, ValueError) as exc:
            print(f"Target Log inspection failed: {exc}", file=sys.stderr)
            return 1
        print("STATE: TARGET_LOG")
        print(f"Log branch: {log.variant.value}")
        print(f"Has content: {'yes' if log.has_content else 'no'}")
        print(f"Content length: {log.content_length}")
        print(f"SAVE enabled: {'yes' if log.save_enabled else 'no'}")
        print(f"Lock evidence: {', '.join(log.lock_evidence) or 'none'}")
        print(f"UI hierarchy: {dump.path}")
        return 0

    if args.command in {"clear-target-log", "disconnect-target-log"}:
        controller = TargetLogController(
            ADBClient(adb_path=args.adb_path),
            HumanizedInput(InputSettings.from_environment()),
            NavigationSettings.from_environment(),
            event_handler=print,
        )
        try:
            if args.command == "clear-target-log":
                result = controller.clear_and_save(args.serial)
                print(f"Log result: {result.status.value}")
                print(f"Initial content length: {result.initial_content_length}")
                print(f"Observations: {result.observations}")
            else:
                result = controller.disconnect(args.serial)
                print(f"STATE: {result.source.value}")
                print(f"Verified after observations: {result.observations}")
                print(f"STATE: {result.destination.value}")
        except (
            ADBError,
            ConfigurationError,
            OSError,
            TargetLogActionError,
            TargetLogParseError,
            ValueError,
        ) as exc:
            print(f"Target Log action failed: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.command == "process-filter":
        destination = ProcessFilter(args.filter.upper())
        client = ADBClient(adb_path=args.adb_path)
        try:
            controller = ProcessFilterController(
                client,
                HumanizedInput(InputSettings.from_environment()),
                NavigationSettings.from_environment(),
                event_handler=print,
            )
            result = controller.select(destination, args.serial)
        except (
            ADBError,
            ConfigurationError,
            OSError,
            ProcessFilterError,
            ProcessParseError,
            ValueError,
        ) as exc:
            print(f"Process filter selection failed: {exc}", file=sys.stderr)
            _save_process_filter_failure_diagnostics(client, args.serial)
            return 1

        if result.tap is None:
            print(f"Already at process filter: {result.destination.value}")
        else:
            print(f"Verified after observations: {result.observations}")
            print(f"Action attempts: {result.attempts}")
        print(f"PROCESS FILTER: {result.destination.value}")
        return 0

    if args.command == "scroll-processes":
        direction = ScrollDirection(args.direction.upper())
        client = ADBClient(adb_path=args.adb_path)
        try:
            scroller = ProcessScroller(
                client,
                HumanizedInput(InputSettings.from_environment()),
                NavigationSettings.from_environment(),
                event_handler=print,
            )
            result = scroller.scroll_once(direction, args.serial)
        except (
            ADBError,
            ConfigurationError,
            OSError,
            ProcessParseError,
            ProcessScrollError,
            ValueError,
        ) as exc:
            print(f"Process scroll failed: {exc}", file=sys.stderr)
            return 1
        print(f"Process filter: {result.filter.value}")
        print(f"Before visible: {', '.join(result.before_visible_ids) or 'none'}")
        print(f"After visible: {', '.join(result.after_visible_ids) or 'none'}")
        print(f"Reached boundary: {'yes' if result.reached_boundary else 'no'}")
        print(f"Action attempts: {result.attempts}")
        return 0

    return 2


def _save_navigation_failure_diagnostics(
    client: ADBClient, serial: str | None
) -> None:
    timestamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    try:
        ui = client.capture_ui_hierarchy(
            Path("diagnostics", f"navigation-failure-{timestamp}.xml"), serial
        )
        screenshot = client.capture_screenshot(
            Path("diagnostics", f"navigation-failure-{timestamp}.png"), serial
        )
    except (ADBError, OSError, ValueError) as exc:
        print(f"Failure diagnostics unavailable: {exc}", file=sys.stderr)
        return
    print(f"Failure UI hierarchy: {ui.path}", file=sys.stderr)
    print(f"Failure screenshot: {screenshot.path}", file=sys.stderr)


def _save_process_filter_failure_diagnostics(
    client: ADBClient, serial: str | None
) -> None:
    timestamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    try:
        ui = client.capture_ui_hierarchy(
            Path("diagnostics", f"filter-failure-{timestamp}.xml"), serial
        )
        screenshot = client.capture_screenshot(
            Path("diagnostics", f"filter-failure-{timestamp}.png"), serial
        )
    except (ADBError, OSError, ValueError) as exc:
        print(f"Filter failure diagnostics unavailable: {exc}", file=sys.stderr)
        return
    print(f"Filter failure UI hierarchy: {ui.path}", file=sys.stderr)
    print(f"Filter failure screenshot: {screenshot.path}", file=sys.stderr)
