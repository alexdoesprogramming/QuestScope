# QuestScope

**A desktop monitoring and diagnostics toolkit for Meta Quest.**

QuestScope is a Windows-first desktop app for inspecting a connected Quest headset, viewing device information, and investigating logs. It does not require root.

## Current status

Early development. The first milestone is a reliable ADB connection layer and a small desktop dashboard. Metrics are only shown when the device actually exposes them.

## Requirements

- Windows 10/11 (primary target; other platforms may work)
- Python 3.12+
- Android Platform Tools (`adb`) installed and available on `PATH`
- Meta Quest with Developer Mode enabled and USB debugging authorized

## Run from source

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

Connect the headset over USB, enable USB debugging, and accept the authorization prompt inside the headset. Then select **Refresh** in QuestScope.

## First milestone

- Detect whether ADB is installed
- List connected and authorized devices
- Read basic device properties and battery information
- Stream and filter logcat output
- Explain disconnected, unauthorized, and command-failure states clearly

## Safety and privacy

QuestScope uses ordinary ADB commands and does not attempt to root, unlock, flash, or modify the headset. Logs may contain personal information; review them before sharing exported diagnostics.

## Development

Run the standard-library tests:

```powershell
python -m unittest discover -s tests -v
```

## License

MIT. See [LICENSE](LICENSE).
