"""The Bluetooth devices paired with this PC (Windows), read through PowerShell."""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass

QUERY = (
    "Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | "
    "Where-Object { $_.InstanceId -match '^(BTHENUM|BTHLE)\\\\DEV_' } | "
    "Select-Object FriendlyName, Status, InstanceId | ConvertTo-Json -Compress"
)


@dataclass
class BluetoothDevice:
    name: str
    available: bool         # Windows reports the device as present and working
    low_energy: bool


def parse(text: str) -> list:
    text = (text or "").strip()
    if not text:
        return []
    data = json.loads(text)
    if isinstance(data, dict):
        data = [data]
    out = []
    for item in data:
        name = str(item.get("FriendlyName") or "").strip()
        if not name:
            continue
        out.append(BluetoothDevice(name, str(item.get("Status") or "") == "OK",
                                   str(item.get("InstanceId") or "").upper().startswith("BTHLE")))
    out.sort(key=lambda d: (not d.available, d.name.lower()))
    return out


def list_devices(timeout: float = 15.0) -> list:
    if not sys.platform.startswith("win"):
        raise RuntimeError("The Bluetooth list is only available on Windows.")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", QUERY],
                            capture_output=True, text=True, timeout=timeout, creationflags=flags)
    return parse(result.stdout)
