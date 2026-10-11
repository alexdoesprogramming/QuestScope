# QuestScope

**Live desktop monitoring and diagnostics for Meta Quest.**

QuestScope is a Windows-first, root-free dashboard for inspecting metrics exposed by a connected headset through ordinary Android Debug Bridge (ADB) commands.

## Features

- Dark desktop dashboard with rolling charts for CPU activity, OS-level RAM pressure, battery level, and reported battery temperature
- Three-second telemetry sampling on a background thread
- Read-only process explorer with search/filter and on-demand per-process memory inspection using Android `dumpsys meminfo` (PSS)
- Recent logcat snapshots and **live logcat streaming**, with severity/crash highlighting, filtering, and save-to-file
- Performance-session recorder that exports timestamped telemetry to CSV
- Connection and USB-debugging authorization status
- No root, bootloader unlocking, flashing, or headset modification

## Requirements

- Windows 10/11 (primary target; other platforms may work)
- Python 3.12+
- Android Platform Tools (`adb`) available on PATH
- Meta Quest with Developer Mode and USB debugging enabled and authorized

## Run from source

    py -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install -r requirements.txt
    python main.py

Connect the headset over USB and accept the USB debugging prompt inside the headset. Wireless ADB works if it is already configured and visible to the local ADB executable.

## Download a standalone Windows build

Every push to `main` triggers a Windows packaging job after tests pass. Open the repository's **Actions** tab, select the latest **Python checks and Windows build** run, and download the `QuestScope-Windows` artifact. Extract it and run `QuestScope.exe`.

The executable is not currently signed, so Windows SmartScreen may show a warning. Only run builds you trust and download them from this repository's Actions artifacts.

## Telemetry accuracy and privacy

CPU activity is calculated from changes in cumulative `/proc/stat` counters; the first sample establishes a baseline. RAM is an OS-level estimate, not per-app memory. Temperature is the battery sensor reported by Android, not CPU or GPU temperature. Per-process PSS is a point-in-time Android estimate and may be unavailable on some firmware.

Live logcat keeps the most recent 5,000 lines in memory to cap UI growth. Logcat and CSV files can contain device identifiers or other personal data; review them before sharing. Log filtering/highlighting changes only the displayed text, not the underlying log source.

## Tests

    python -m unittest discover -s tests -v

## License

MIT. See LICENSE.
