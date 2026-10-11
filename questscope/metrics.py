"""Parsers for telemetry exposed by standard Android ADB shell commands."""
from __future__ import annotations


def parse_cpu_stat(text: str) -> tuple[int, int] | None:
    """Return cumulative CPU ticks (total, idle+iowait) from /proc/stat."""
    first = next((line for line in text.splitlines() if line.startswith("cpu ")), None)
    if first is None:
        return None
    values = [int(value) for value in first.split()[1:]]
    if len(values) < 4:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


def cpu_percent(previous: tuple[int, int] | None, current: tuple[int, int]) -> float | None:
    if previous is None:
        return None
    total_delta = current[0] - previous[0]
    idle_delta = current[1] - previous[1]
    if total_delta <= 0:
        return None
    return max(0.0, min(100.0, 100.0 * (total_delta - idle_delta) / total_delta))


def parse_meminfo(text: str) -> dict[str, int | float] | None:
    values: dict[str, int] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].endswith(":"):
            try:
                values[parts[0][:-1]] = int(parts[1])
            except ValueError:
                continue
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if total is None:
        return None
    if available is None:
        available = values.get("MemFree", 0) + values.get("Buffers", 0) + values.get("Cached", 0)
    used = max(0, total - available)
    return {
        "total_mb": round(total / 1024),
        "used_mb": round(used / 1024),
        "used_percent": max(0.0, min(100.0, 100.0 * used / total)) if total else 0.0,
    }


def parse_battery(text: str) -> dict[str, float | int | None]:
    level = None
    temperature_c = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("level:"):
            try:
                level = max(0, min(100, int(stripped.split(":", 1)[1].strip())))
            except ValueError:
                pass
        elif stripped.startswith("temperature:"):
            try:
                temperature_c = int(stripped.split(":", 1)[1].strip()) / 10.0
            except ValueError:
                pass
    return {"level": level, "temperature_c": temperature_c}
