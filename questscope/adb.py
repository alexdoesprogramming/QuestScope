"""Small, testable wrapper around the Android Debug Bridge CLI."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Device:
    serial: str
    state: str
    details: str = ""

    @property
    def ready(self) -> bool:
        return self.state == "device"


class AdbError(RuntimeError):
    """An ADB command could not be completed."""


class AdbClient:
    def __init__(self, executable: str | None = None, timeout: float = 8.0):
        self.executable = executable or shutil.which("adb")
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.executable)

    def run(self, args: Sequence[str], *, timeout: float | None = None) -> str:
        if not self.executable:
            raise AdbError(
                "ADB was not found. Install Android Platform Tools and add adb.exe to PATH."
            )
        try:
            result = subprocess.run(
                [self.executable, *args],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=self.timeout if timeout is None else timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AdbError(f"ADB command timed out after {exc.timeout} seconds.") from exc
        except OSError as exc:
            raise AdbError(f"Could not start ADB: {exc}") from exc

        output = (result.stdout or "").strip()
        error = (result.stderr or "").strip()
        if result.returncode != 0:
            raise AdbError(error or output or f"ADB exited with code {result.returncode}.")
        return output

    def devices(self) -> list[Device]:
        output = self.run(["devices", "-l"])
        found: list[Device] = []
        for line in output.splitlines()[1:]:
            line = line.strip()
            if not line or line.startswith("*"):
                continue
            parts = line.split(maxsplit=2)
            if len(parts) < 2:
                continue
            found.append(Device(parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
        return found

    def shell(self, serial: str, *args: str, timeout: float | None = None) -> str:
        if not serial or any(ch.isspace() for ch in serial):
            raise ValueError("A valid device serial is required.")
        return self.run(["-s", serial, "shell", *args], timeout=timeout)

    def properties(self, serial: str) -> dict[str, str]:
        keys = {
            "Model": "ro.product.model",
            "Android version": "ro.build.version.release",
            "Build": "ro.build.display.id",
            "Manufacturer": "ro.product.manufacturer",
        }
        result: dict[str, str] = {}
        for label, key in keys.items():
            try:
                value = self.shell(serial, "getprop", key, timeout=4)
            except AdbError:
                value = ""
            result[label] = value or "Unavailable"
        return result

    def battery(self, serial: str) -> str:
        output = self.shell(serial, "dumpsys", "battery", timeout=5)
        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("level:"):
                return stripped.split(":", 1)[1].strip() + "%"
        return "Unavailable"
