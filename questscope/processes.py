"""Parsing helpers for Android's read-only process listing."""
from __future__ import annotations

def parse_process_list(text: str) -> list[dict[str, str]]:
    """Parse common Android ps output without assuming fixed column positions."""
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return []
    headers = [header.upper() for header in lines[0].split()]
    pid_index = next((i for i, name in enumerate(headers) if name == "PID"), None)
    name_index = next((i for i, name in enumerate(headers) if name in {"NAME", "CMD", "COMMAND"}), None)
    user_index = next((i for i, name in enumerate(headers) if name in {"USER", "UID"}), None)
    state_index = next((i for i, name in enumerate(headers) if name in {"S", "STAT", "STATE"}), None)
    if pid_index is None or name_index is None:
        return []
    processes = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) <= max(pid_index, name_index):
            continue
        pid = parts[pid_index]
        if not pid.isdigit():
            continue
        processes.append({
            "pid": pid,
            "name": parts[name_index],
            "user": parts[user_index] if user_index is not None and user_index < len(parts) else "",
            "state": parts[state_index] if state_index is not None and state_index < len(parts) else "",
        })
    return processes
