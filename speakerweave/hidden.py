"""Outputs the person hid in the Sound outputs list ("Hidden by user").

Hiding is about this PC, not about one setup: a hidden output is taken out of every
setup that is loaded, and its place on the map, roles and sound settings are kept
here, so it comes back exactly as it was. Each entry, by output name:

    device   the output as it was in the setup (asdict of Device), or None when it was
             never part of the setup
    enabled  whether it was ticked when it was hidden
    seen     whether it was connected the last time SpeakerWeave looked
    quiet    "Ignore and don't show again": never say that it was found again
"""
from __future__ import annotations

from dataclasses import asdict

from .model import Project, _id, device_from_dict


def clean(entries) -> dict:
    """The saved list, made safe to use whatever is in the settings file."""
    out = {}
    if not isinstance(entries, dict):
        return out
    for name, entry in entries.items():
        if not name or not isinstance(entry, dict):
            continue
        device = entry.get("device")
        out[str(name)] = {"device": device if isinstance(device, dict) else None,
                          "enabled": bool(entry.get("enabled", False)),
                          "seen": bool(entry.get("seen", False)),
                          "quiet": bool(entry.get("quiet", False))}
    return out


def same_output(a: str, b: str) -> bool:
    """Windows and the sound library can shorten names, so a name that starts the
    same way counts as the same output."""
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    return bool(a and b) and (a == b or a.startswith(b) or b.startswith(a))


def is_hidden(settings, name: str) -> bool:
    return name in settings.hidden_outputs


def connected(name: str, present) -> bool:
    return any(same_output(name, other) for other in present)


def hide(settings, project: Project, name: str, present=()) -> None:
    """Moves the output into "Hidden by user"."""
    dev = next((d for d in project.devices if d.name == name), None)
    old = settings.hidden_outputs.get(name, {})
    entry = {"device": old.get("device"), "enabled": old.get("enabled", False),
             "seen": connected(name, present), "quiet": old.get("quiet", False)}
    if dev is not None:
        entry["device"], entry["enabled"] = asdict(dev), dev.enabled
        project.remove_device(dev.id)
    settings.hidden_outputs[name] = entry


def unhide(settings, project: Project, name: str, activate: bool = False):
    """Takes the output out of "Hidden by user". Returns the Device when it came back
    into the setup as it was, None when it was never part of it (then it is listed
    with the other outputs again, or added like a newly ticked one when activated)."""
    entry = settings.hidden_outputs.pop(name, None)
    if not entry or not entry.get("device"):
        return None
    if any(d.name == name for d in project.devices):
        dev = next(d for d in project.devices if d.name == name)
    else:
        try:
            dev = device_from_dict(entry["device"])
        except Exception:
            return None
        if project.find_device(dev.id) is not None:     # another output has its id by now
            dev.id = _id()
            for spk in dev.speakers:
                spk.id = _id()
        project.devices.append(dev)
    dev.enabled = True if activate else bool(entry.get("enabled", False))
    return dev


def pull_hidden(settings, project: Project) -> list:
    """A setup was loaded: hidden outputs are taken out of it (the latest version of
    each is kept to come back with). Returns the names taken out."""
    taken = []
    for dev in list(project.devices):
        if dev.name in settings.hidden_outputs:
            entry = settings.hidden_outputs[dev.name]
            entry["device"], entry["enabled"] = asdict(dev), dev.enabled
            project.remove_device(dev.id)
            taken.append(dev.name)
    return taken


def found_again(settings, present) -> list:
    """Notes which hidden outputs are connected now. Returns the ones that were not
    connected the last time and should be announced (not "don't show again")."""
    found = []
    for name, entry in settings.hidden_outputs.items():
        now = connected(name, present)
        if now and not entry.get("seen") and not entry.get("quiet"):
            found.append(name)
        entry["seen"] = now
    return found
