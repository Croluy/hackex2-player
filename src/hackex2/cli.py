"""Command-line interface for small, verifiable automation milestones."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from hackex2.adb.device import ADBClient, ADBError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hackex2")
    subparsers = parser.add_subparsers(dest="command", required=True)

    device_parser = subparsers.add_parser(
        "device", help="inspect the connected Android device"
    )
    device_parser.add_argument(
        "--serial",
        default=os.getenv("ANDROID_SERIAL") or None,
        help="ADB device serial; defaults to ANDROID_SERIAL",
    )
    device_parser.add_argument(
        "--adb-path",
        default="adb",
        help="path to the adb executable",
    )
    return parser


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

    return 2

