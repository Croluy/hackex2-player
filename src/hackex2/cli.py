"""Command-line interface for small, verifiable automation milestones."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from hackex2.adb.device import ADBClient, ADBError
from hackex2.states import ScreenState, detect_screen


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

    return 2
