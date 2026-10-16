"""Making Windows play into the device SpeakerWeave listens to.

SpeakerWeave hears the PC through a device Windows plays into (usually the
virtual VB-CABLE device) and spreads that over the speakers. For that to work
the device has to be the default output of Windows. With the setting on, this
is checked every time SpeakerWeave opens, so also after every restart of the
PC, and the old default comes back when SpeakerWeave quits.
"""
from __future__ import annotations

from . import cable, windefault
from .speaker_library import recognise

LOOPBACK_TAG = " [Loopback]"


def plan(project, loopbacks) -> tuple[str, str, str]:
    """What Windows should play into: (device name, loopback name SpeakerWeave
    should listen to, problem). An empty device name with no problem means
    nothing needs to change (the source is a microphone or line in)."""
    in_setup = {d.name for d in project.devices if d.enabled}
    if project.input_kind == "loopback" and project.input_name:
        device = project.input_name.replace(LOOPBACK_TAG, "")
        if device in in_setup:
            return "", "", (f"{device} is one of your speakers, so Windows should not play into it. "
                            f"Choose the virtual device (SpeakerWeave Virtual Speaker output) under Listen to.")
        return device, project.input_name, ""
    if project.input_kind == "device":
        return "", "", ""
    # VB-CABLE first (SpeakerWeave Virtual Speaker output), then any other virtual device
    ordered = sorted(loopbacks, key=lambda info: not cable.is_cable_input(getattr(info, "name", info)))
    for info in ordered:
        name = getattr(info, "name", info)
        device = name.replace(LOOPBACK_TAG, "")
        entry = recognise(device)
        if entry is not None and entry.category == "virtual" and device not in in_setup:
            return device, name, ""
    return "", "", ("No virtual sound device was found, so there is nothing for Windows to play "
                    "into. Install VB-CABLE (see the guide), then open SpeakerWeave again.")


def apply(settings, device_name: str, outputs=None) -> tuple[bool, str]:
    """Makes device_name the Windows default output and remembers the old one.
    Returns (changed, problem)."""
    if not windefault.supported():
        return False, ""
    outputs = windefault.list_outputs() if outputs is None else outputs
    dev_id = windefault.find(device_name, outputs)
    if not dev_id and cable.is_cable_input(device_name):
        dev_id = cable.find(outputs)[0]           # VB-CABLE under its other name
    if not dev_id:
        return False, f"Windows has no output called {device_name} right now."
    current = windefault.defaults()
    if all(value == dev_id for value in current.values()):
        if settings.managed_output != dev_id:
            settings.managed_output = dev_id
            settings.previous_outputs = {}        # it was already the default before us
        return False, ""
    if settings.managed_output != dev_id or not settings.previous_outputs:
        settings.previous_outputs = {role: value for role, value in current.items()
                                     if value and value != dev_id}
    windefault.set_default(dev_id)
    settings.managed_output = dev_id
    return True, ""


def restore(settings) -> bool:
    """Puts back the defaults that were there before SpeakerWeave changed them,
    unless someone has picked another output in the meantime."""
    managed, previous = settings.managed_output, dict(settings.previous_outputs or {})
    settings.managed_output, settings.previous_outputs = "", {}
    if not managed or not previous or not windefault.supported():
        return False
    current = windefault.defaults()
    available = {dev_id for dev_id, _ in windefault.list_outputs()}
    changed = False
    for role, dev_id in previous.items():
        if current.get(role) == managed and dev_id in available:
            windefault.set_default(dev_id, roles=(int(role),))
            changed = True
    return changed
