# QuestScope

**A live desktop monitoring and diagnostics toolkit for Meta Quest.**

QuestScope is a Windows-first, root-free desktop dashboard for sampling metrics exposed by a connected Quest through ordinary Android Debug Bridge (ADB) commands.

## Current status

The dashboard polls every three seconds in a background worker and plots rolling history for CPU activity, RAM pressure, battery level, and battery temperature when the headset exposes those values. ADB does not expose every hardware sensor on every firmware, so unavailable values are left blank rather than fabricated. Charts retain up to 30 samples.

## Requirements

- Windows 10/11 (primary target; other platforms may work)
- Python 3.12+
- Android Platform Tools (`adb`) installed and available on `PATH`
- Meta Quest with Developer Mode enabled and USB debugging authorized

## Run from source

    py -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install -r requirements.txt
    python main.py

Connect the headset over USB, enable USB debugging, and accept the authorization prompt inside the headset. Wireless ADB can also work if it is already configured and visible to the local `adb` executable.

## Features

- Live ADB connection and authorization status
- Headset model and Android version
- Rolling CPU activity chart from `/proc/stat` when readable
- RAM usage estimate from `/proc/meminfo` when readable
- Battery level and battery temperature from `dumpsys battery` when reported
- Recent Android logcat capture
- Background sampling so slow ADB calls do not block the main window
- No root, bootloader unlocking, flashing, or headset modification

## Notes on telemetry

CPU activity is calculated from changes in cumulative `/proc/stat` counters; the first sample establishes a baseline. RAM usage is an OS-level estimate, not an app-specific memory breakdown. Battery temperature is the battery sensor reported by Android, not CPU or GPU temperature. Sensor access can vary by Quest model and firmware.

Logs can contain personal information; review them before sharing diagnostics.

## Tests

    python -m unittest discover -s tests -v

## License

MIT. See [LICENSE](LICENSE).
