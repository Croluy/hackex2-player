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

The first supported state is `HOME`. Detection requires all configured HOME markers; otherwise the command reports `UNKNOWN_SCREEN` and saves both the hierarchy and a screenshot for diagnosis without tapping the UI.

## Focused test

```bash
.venv/bin/python -m unittest discover -s tests -v
```
