# QuestScope

**Live desktop monitoring and diagnostics for Meta Quest.**

QuestScope is a Windows-first, root-free dashboard for sampling metrics exposed by a connected headset through ordinary Android Debug Bridge (ADB) commands.

## Features

- Dark desktop dashboard with rolling charts for CPU activity, OS-level RAM pressure, battery level, and reported battery temperature
- Three-second background sampling so ADB work does not block the interface
- Read-only process explorer with search/filter
- Recent logcat capture, on-screen filtering, and save-to-file
- Performance-session recorder that exports timestamped telemetry to CSV
- Clear connection and USB-debugging authorization status
- No root, bootloader unlocking, flashing, or headset modification

## Requirements

- Windows 10/11 (primary target; other platforms may work)
- Python 3.12+
- Android Platform Tools (adb) available on PATH
- Meta Quest with Developer Mode and USB debugging enabled and authorized

## Run from source

    py -m venv .venv
    .\\.venv\\Scripts\\Activate.ps1
    python -m pip install -r requirements.txt
    python main.py

Connect the headset over USB and accept the USB debugging prompt inside the headset. Wireless ADB can work if it is already configured and visible to the local ADB executable.

## Telemetry accuracy

CPU activity is calculated from changes in cumulative /proc/stat counters; the first sample establishes a baseline. RAM is an OS-level estimate, not per-app memory. Temperature is the battery sensor reported by Android, not CPU or GPU temperature. The process explorer displays process metadata only and does not invent per-process CPU or memory figures. Availability varies by headset firmware.

A session CSV is written on the PC and contains timestamps, device serial, and available telemetry. Logcat may contain personal information; review logs before sharing them.

## Tests

    python -m unittest discover -s tests -v

## License

MIT. See LICENSE.
