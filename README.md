# HackEx2 Player

Private, state-aware automation for HackEx2 running on macOS and controlling an unrooted Android device through ADB.

## Current milestone

The project can discover one authorized Android device, report its model, and read its effective screen resolution. It does not interact with the game yet.

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

## Focused test

```bash
.venv/bin/python -m unittest discover -s tests -v
```

