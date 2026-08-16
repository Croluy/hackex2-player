# HackEx2 Player

Private, state-aware automation for HackEx2 running on macOS and controlling an unrooted Android device through ADB.

## Current milestone

The project can discover one authorized Android device, report its model and effective screen resolution, and capture a verified PNG screenshot. It does not interact with the game yet.

## Requirements

- macOS
- Python 3.11 or newer
- Android Platform Tools (`adb`)
- USB debugging enabled on the Android device

## Setup

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --no-build-isolation -e .
cp .env.example .env
```

If more than one Android device is connected, set `ANDROID_SERIAL` in your shell or pass `--serial` explicitly.

## Verify the connected device

```bash
.venv/bin/python -m hackex2 device
```

Expected output:

```text
Device connected: <serial>
Model: <model>
Resolution: <width>x<height>
```

## Capture a screenshot

```bash
.venv/bin/python -m hackex2 screenshot
```

The command validates the PNG returned by ADB and saves it under `diagnostics/`. That directory is intentionally excluded from Git.

## Inspect the Android UI hierarchy

```bash
.venv/bin/python -m hackex2 ui-dump
```

The command validates and parses the UIAutomator XML, reports the visible and clickable element counts, and stores the diagnostic XML under `diagnostics/`.

## Detect the current screen

```bash
.venv/bin/python -m hackex2 detect-screen
```

The supported states are `HOME` and `PROCESSES`. Detection requires every marker configured for exactly one state; otherwise the command reports `UNKNOWN_SCREEN` and saves both the hierarchy and a screenshot for diagnosis without tapping the UI.

## Humanized input configuration

Input timing and position variation are read from `.env`:

```env
MIN_ACTION_DELAY_MS=100
MAX_ACTION_DELAY_MS=500
TAP_RANDOM_RADIUS_PX=12
```

Tap points use a center-weighted distribution, stay inside the detected clickable element, and are delayed independently before being sent to ADB.

## Verified navigation

```bash
.venv/bin/python -m hackex2 navigate home
.venv/bin/python -m hackex2 navigate processes
```

Navigation starts only from a recognized screen, targets exactly one enabled UI element, and polls a limited number of times until the requested destination is recognized. A tap may be retried only while the observed state remains exactly the known source state. Unknown or alternative states stop immediately. Failed transitions save diagnostic XML and PNG files.

## Focused test

```bash
.venv/bin/python -m unittest discover -s tests -v
```
