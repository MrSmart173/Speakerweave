"""Starting SpeakerWeave together with Windows (the "Run" list of the current user)."""
from __future__ import annotations

import sys

from . import paths

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "SpeakerWeave"


def supported() -> bool:
    """Only the installed app has a fixed .exe that Windows can start."""
    return sys.platform.startswith("win") and paths.is_built()


def command() -> str:
    return f'"{sys.executable}" --tray'


def is_enabled() -> bool:
    if not sys.platform.startswith("win"):
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE)
            return bool(value)
    except OSError:
        return False


def set_enabled(on: bool) -> None:
    if not supported():
        raise RuntimeError("Starting with Windows works in the installed app.")
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if on:
            winreg.SetValueEx(key, VALUE, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, VALUE)
            except OSError:
                pass
