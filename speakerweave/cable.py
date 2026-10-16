"""The virtual sound device SpeakerWeave listens to, VB-CABLE, under SpeakerWeave's name.

VB-CABLE calls its output "CABLE Input". In Windows' lists of outputs that looks like
something to plug a cable into, so SpeakerWeave renames it to "SpeakerWeave Virtual
Speaker output", as the Sound control panel would. Windows still adds the driver's part,
"(VB-Audio Virtual Cable)", after it. Uninstalling SpeakerWeave gives the old name back.

Setups saved before the rename still name the old device, so names are translated both
ways wherever SpeakerWeave looks a device up.
"""
from __future__ import annotations

import time

from . import windefault

OLD_NAME = "CABLE Input"
NEW_NAME = "SpeakerWeave Virtual Speaker output"
DRIVER = "(VB-Audio Virtual Cable)"
LOOPBACK = " [Loopback]"
SETTLE_S = 5.0          # how long Windows may take to show a new name everywhere


def is_cable_input(name: str) -> bool:
    """True for VB-CABLE's output, under either name (and with " [Loopback]" after it)."""
    name = (name or "").strip()
    return name.startswith(OLD_NAME + " (VB-Audio") or name == OLD_NAME \
        or name.startswith(NEW_NAME)


def other_name(name: str) -> str:
    """The same device under its other name: old to new, or new back to old ("" if the name
    is not VB-CABLE's output)."""
    name = name or ""
    if name.startswith(OLD_NAME + " (VB-Audio"):
        return NEW_NAME + name[len(OLD_NAME):]
    if name.startswith(NEW_NAME):
        return OLD_NAME + name[len(NEW_NAME):]
    return ""


def matches(wanted: str, have: str) -> bool:
    """True when have is the device wanted: the same name, or VB-CABLE's output under its
    other name (a setup saved before the rename, or after it was undone)."""
    if wanted == have:
        return True
    return bool(wanted) and is_cable_input(wanted) and is_cable_input(have) \
        and wanted.endswith(LOOPBACK) == have.endswith(LOOPBACK)


def pick(wanted: str, names) -> str:
    """The name in names that is the device wanted ("" if none): the exact name first."""
    names = list(names)
    if wanted in names:
        return wanted
    return next((name for name in names if matches(wanted, name)), "")


def find(outputs=None) -> tuple:
    """(id, full name) of VB-CABLE's output, or ("", "")."""
    outputs = windefault.list_outputs() if outputs is None else outputs
    for dev_id, name in outputs:
        if is_cable_input(name) and "VB-Audio" in name:
            return dev_id, name
    return "", ""


def _rename(want: str, only_from: str) -> bool:
    if not windefault.supported():
        return False
    dev_id, _name = find()
    if not dev_id or windefault.short_name(dev_id) != only_from:
        return False                    # not there, or someone gave it a name of their own
    windefault.rename(dev_id, want)
    if windefault.short_name(dev_id) != want:
        return False
    _wait_for(dev_id, want)
    return True


def _wait_for(dev_id: str, want: str) -> None:
    """Windows shows the new full name a moment after the rename, and the device can drop
    out of the lists in between. Waits until the lists of outputs show it again."""
    deadline = time.monotonic() + SETTLE_S
    while time.monotonic() < deadline:
        try:
            if any(i == dev_id and name.startswith(want) for i, name in windefault.list_outputs()):
                time.sleep(0.3)         # and a little longer for the sound libraries
                return
        except Exception:
            pass
        time.sleep(0.15)


def brand() -> bool:
    """Renames "CABLE Input" to "SpeakerWeave Virtual Speaker output". True if it did."""
    try:
        return _rename(NEW_NAME, OLD_NAME)
    except Exception:
        return False


def unbrand() -> bool:
    """Gives VB-CABLE its own name back. True if it did."""
    try:
        return _rename(OLD_NAME, NEW_NAME)
    except Exception:
        return False
