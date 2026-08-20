# HackEx2 Player

Private, state-aware automation for HackEx2 running on macOS and controlling an unrooted Android device through ADB.

## Current milestone

The project can inspect and navigate the game through accessibility data, traverse typed process views, open a completed target with exact process verification, service the known Wallet and Log branches, disconnect safely, and persist target observations and outcomes in a local SQLite database. Every consequential tap is gated by a recognized state and verified afterward.

## Requirements

- macOS
- Python 3.11 or newer
- Android Platform Tools (`adb`)
- USB or wireless debugging enabled on the Android device

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

The supported states cover Home, Processes, target Dashboard, the known target Wallet branches, and target Log. Detection requires every marker configured for exactly one state; otherwise the command reports `UNKNOWN_SCREEN` and saves both the hierarchy and a screenshot for diagnosis without tapping the UI.

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

## Inspect visible processes

```bash
.venv/bin/python -m hackex2 inspect-processes
```

The command requires the verified `PROCESSES` state, reads process cards by their dynamic `proc-*` identifiers, distinguishes visible cards from zero-sized off-screen cards, and recognizes completed, failed, running, invalidated, paused, and unknown states. It also extracts observable IP addresses, success chances, lower-case game tags, system markers, and identifiable actions. It does not assume that the active-task count equals the currently visible card count.

## Select a verified process filter

```bash
.venv/bin/python -m hackex2 process-filter shield
.venv/bin/python -m hackex2 process-filter lock
```

The unlabelled filter buttons are located relative to the accessible `ALL` control in the same row. Selection is accepted only when the observed process type matches the requested shield (`Firewall Bypass`), lock (`Password Crack`), or antivirus (`Antivirus Scan`) filter. Empty or ambiguous results stop without guessing.

## Scroll the process list once

```bash
.venv/bin/python -m hackex2 scroll-processes up
.venv/bin/python -m hackex2 scroll-processes down
```

The swipe stays inside the detected scrollable process region. The command verifies that the selected filter is unchanged and that the visible process signature moved. It detects the first or last exposed process as a boundary rather than assuming a fixed number of swipes.

## Inspect a connected target

```bash
.venv/bin/python -m hackex2 inspect-target
```

The command requires a verified `TARGET_DASHBOARD` and parses the observed identity, level, reputation, score, XP, IPv4 address, device, network, firewall, encryptor, and available actions. It only reads the UI hierarchy and never opens Wallet, Apps, Processes, Log, Crews, or Disconnect.

## Local target database

```bash
.venv/bin/python -m hackex2 database-status
```

The versioned SQLite database defaults to `data/hackex2.sqlite3`. The `data/` directory is ignored by Git, while migrations and repository code are versioned. It stores only observed target state, Wallet and Log outcomes, Crypto-transfer aggregates, game tags, and a separate event history. Set `HACKEX2_DB_PATH` or pass `--database` to choose another local path.

## Open a completed process target

```bash
.venv/bin/python -m hackex2 open-process-target --process-id 1992580
.venv/bin/python -m hackex2 open-process-target --ip 88.55.27.70
```

The command requires one exact visible `COMPLETED` process with an active `HACK` action. It taps `HACK` once, never retries it, waits through transient unknown screens, and accepts the target dashboard only when its parsed IPv4 address matches the selected process. The verified dashboard and game tags are then stored locally.

## Service a target with one command

```bash
.venv/bin/python -m hackex2 service-target --expected-ip 255.173.212.38
.venv/bin/python -m hackex2 service-process-target --process-id 2223558
```

`service-target` starts from a verified connected dashboard. `service-process-target` first performs the one-shot process-to-dashboard verification and then runs the same workflow. Known Wallet branches are handled independently: login and conditional transfer, protected or empty Wallet skip, or normal password-crack request without Exploit Kits. The workflow then clears an editable Log or records a protected one, disconnects from the verified safe Log state, and persists each outcome. A proxy-masked address such as `255.173.xxx.xxx` is stored as a known-octet pattern; it is resolved to a full process IP only when the visible prefix matches exactly.

## Inspect a target-wallet branch

```bash
.venv/bin/python -m hackex2 inspect-target-wallet
```

Wallet is treated as a branching transition. `TARGET_WALLET_LOGIN` confirms the owner and prefilled username agree, reports only the length of the masked password, and never submits the form. `TARGET_WALLET_PASSWORD_REQUIRED` recognizes the encryptor level and the accessible `CRACK PASSWORD` and `USE EXPLOIT KIT` actions. `crack-target-wallet-password` chooses the normal crack once and deliberately leaves the consumable Exploit Kit untouched. If the Password Required screen remains unchanged because the game reports that the crack is already queued, that is a benign `SCREEN_UNCHANGED` result: the action is never retried, and the target flow should return to the dashboard, clean the Log, and disconnect. A different or incomplete Wallet layout remains `UNKNOWN_SCREEN` until it has been observed and implemented as its own branch.

After login, the authenticated Wallet is classified as `TRANSFERABLE`, `PROTECTED`, or confirmed `TRANSFERRED` from accessible balance, protection, confirmation, and control state. `transfer-target-wallet` skips protected Wallets and balances of 1 Crypto or less. Otherwise it taps `MAX`, requires either the exact exposed amount or a same-attempt disabled-to-enabled transfer transition when the WebView marks the input `NAF`, taps transfer once, and requires either a matching success message or a zero final balance. It never retries the transfer tap. `target-wallet-back` supports both authenticated and password-required branches; `open-target-wallet` and `login-target-wallet` provide separately verified entry transitions.

Screen recognition is theme-independent: screenshots are diagnostic artifacts only. Automation relies on accessible text, enabled/clickable properties, and structural relationships between UI elements, never on wallpaper, button backgrounds, colors, or pixel matching.

`open-target-log` opens the target Log only from a verified dashboard and accepts the destination only when the accessible `// VICTIM LOG`, editor, Save, and Disconnect structure is present. Disabled editor and Save controls remain recognizable so locked and already-saved branches can be modeled independently.

`inspect-target-log` classifies the Log as editable, locked, or saved without printing its contents. `clear-target-log` skips locked or already-saved branches; otherwise it verifies editor focus, selects and deletes all text with Android key events, confirms the editor is empty, hides the keyboard, saves once, and requires an empty editor with disabled Save. `disconnect-target-log` refuses to disconnect until that saved state or an explicit lock is present, then verifies the return to `PROCESSES` without retrying Disconnect.

## Focused test

```bash
.venv/bin/python -m unittest discover -s tests -v
```
