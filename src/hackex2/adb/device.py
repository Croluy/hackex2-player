"""Reliable discovery of Android devices exposed through ADB."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field


class ADBError(RuntimeError):
    """Raised when ADB cannot provide a safe, unambiguous device."""


@dataclass(frozen=True)
class ADBDevice:
    serial: str
    state: str
    properties: dict[str, str] = field(default_factory=dict)
    width: int | None = None
    height: int | None = None

    @property
    def model(self) -> str:
        return self.properties.get("model", "unknown")


class ADBClient:
    def __init__(self, adb_path: str = "adb", timeout_seconds: float = 10.0) -> None:
        self.adb_path = adb_path
        self.timeout_seconds = timeout_seconds

    def _run(self, *arguments: str) -> str:
        try:
            completed = subprocess.run(
                [self.adb_path, *arguments],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise ADBError(
                f"ADB timed out after {self.timeout_seconds:g} seconds"
            ) from exc

        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise ADBError(detail or f"ADB exited with code {completed.returncode}")
        return completed.stdout

    def list_devices(self) -> list[ADBDevice]:
        return parse_devices(self._run("devices", "-l"))

    def select_device(self, serial: str | None = None) -> ADBDevice:
        devices = self.list_devices()

        if serial:
            matching = [device for device in devices if device.serial == serial]
            if not matching:
                raise ADBError(f"device {serial!r} was not reported by ADB")
            selected = matching[0]
            if selected.state != "device":
                raise ADBError(
                    f"device {serial!r} is {selected.state!r}; authorize it and retry"
                )
            return selected

        authorized = [device for device in devices if device.state == "device"]
        if not authorized:
            states = ", ".join(
                f"{device.serial} ({device.state})" for device in devices
            )
            detail = f" Reported devices: {states}." if states else ""
            raise ADBError(f"no authorized Android device found.{detail}")
        if len(authorized) > 1:
            serials = ", ".join(device.serial for device in authorized)
            raise ADBError(
                f"multiple authorized devices found ({serials}); use --serial"
            )
        return authorized[0]

    def inspect_device(self, serial: str | None = None) -> ADBDevice:
        selected = self.select_device(serial)
        width, height = parse_screen_size(
            self._run("-s", selected.serial, "shell", "wm", "size")
        )
        return ADBDevice(
            serial=selected.serial,
            state=selected.state,
            properties=selected.properties,
            width=width,
            height=height,
        )


def parse_devices(output: str) -> list[ADBDevice]:
    devices: list[ADBDevice] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("List of devices attached") or line.startswith("*"):
            continue

        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[:2]
        properties: dict[str, str] = {}
        for token in parts[2:]:
            if ":" not in token:
                continue
            key, value = token.split(":", 1)
            properties[key] = value
        devices.append(ADBDevice(serial, state, properties))
    return devices


def parse_screen_size(output: str) -> tuple[int, int]:
    sizes: dict[str, tuple[int, int]] = {}
    for label, width, height in re.findall(
        r"(?im)^\s*(Physical|Override) size:\s*(\d+)x(\d+)\s*$", output
    ):
        sizes[label.lower()] = (int(width), int(height))

    if "override" in sizes:
        return sizes["override"]
    if "physical" in sizes:
        return sizes["physical"]
    raise ADBError(f"could not parse screen size from ADB output: {output.strip()!r}")

