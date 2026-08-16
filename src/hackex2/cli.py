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
from hackex2.navigation import NavigationError, Navigator
from hackex2.processes import (
    ProcessFilter,
    ProcessParseError,
    infer_selected_process_filter,
    parse_process_list,
)
from hackex2.process_filters import ProcessFilterController, ProcessFilterError
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hackex2")
    subparsers = parser.add_subparsers(dest="command", required=True)

    device_parser = subparsers.add_parser(
        "device", help="inspect the connected Android device"
    )
    add_adb_arguments(device_parser)

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


def main(argv: Sequence[str] | None = None) -> int:
    try:
        load_env_file()
    except ConfigurationError as exc:
        print(f"Configuration failed: {exc}", file=sys.stderr)
        return 1
    args = build_parser().parse_args(argv)

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
            target = parse_target_dashboard(dump.hierarchy)
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
