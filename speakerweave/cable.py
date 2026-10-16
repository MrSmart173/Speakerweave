"""The virtual sound device SpeakerWeave listens to, VB-CABLE, under SpeakerWeave's name.

VB-CABLE calls its output "CABLE Input". In Windows' lists of outputs that looks like
something to plug a cable into, so SpeakerWeave renames it to "SpeakerWeave Virtual
Speaker output", as the Sound control panel would. Windows still adds the driver's part,
"(VB-Audio Virtual Cable)", after it. Uninstalling SpeakerWeave gives the old name back.

Setups saved before the rename still name the old device, so names are translated both
ways wherever SpeakerWeave looks a device up.
"""
from __future__ import annotations

from . import windefault

OLD_NAME = "CABLE Input"
NEW_NAME = "SpeakerWeave Virtual Speaker output"
DRIVER = "(VB-Audio Virtual Cable)"


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
    return windefault.short_name(dev_id) == want


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
