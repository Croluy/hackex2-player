"""Command-line interface for small, verifiable automation milestones."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from hackex2.adb.device import ADBClient, ADBError


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

    return 2
