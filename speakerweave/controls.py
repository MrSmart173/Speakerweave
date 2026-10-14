"""Actions that keys, controller buttons and remote links can trigger, and the
list of which input triggers which action (the bindings).

A binding is a small dict so it can be saved as JSON:
  keyboard   {"action": "volume_up", "kind": "key", "vk": 175, "mods": 0,
              "qt": "Volume Up", "text": "Volume Up"}
  controller {"action": "mute", "kind": "pad", "guid": "0300...", "device": "Button box",
              "input": "b12", "text": "Button 13 on Button box"}
"""
from __future__ import annotations

from dataclasses import dataclass

from .model import CUSTOM, mode_choices
from .settings import SETUP_SLOTS

# Windows modifier flags, as RegisterHotKey wants them
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 1, 2, 4, 8
VOLUME_STEP_DB = 2.0


@dataclass(frozen=True)
class Action:
    key: str
    label: str
    group: str


STATIC_ACTIONS = [
    Action("toggle_sound", "Start or stop the sound", "Sound"),
    Action("volume_up", f"Volume up ({VOLUME_STEP_DB:g} dB)", "Sound"),
    Action("volume_down", f"Volume down ({VOLUME_STEP_DB:g} dB)", "Sound"),
    Action("mute", "Mute or unmute everything", "Sound"),
    Action("next_mode", "Next speaker mode", "Speakers"),
    Action("prev_mode", "Previous speaker mode", "Speakers"),
    Action("toggle_bass", "Bass to the subwoofer on or off", "Speakers"),
    Action("toggle_upmix", "Fill every speaker on or off", "Speakers"),
    Action("test_signal", "Test signal on or off", "Speakers"),
    Action("toggle_metronome", "Metronome on or off", "Speakers"),
    Action("toggle_lights", "Lights on or off", "Lights"),
    Action("show_window", "Show or hide SpeakerWeave", "App"),
] + [Action(f"slot_{n}", f"Load setup slot {n}", "Setups") for n in range(1, SETUP_SLOTS + 1)]


def output_actions(project) -> list:
    return [Action(f"mute_output:{dev.id}", f"Mute or unmute {dev.title}", "Outputs")
            for dev in project.devices]


def all_actions(project) -> list:
    return STATIC_ACTIONS + output_actions(project)


def label_of(action_key: str, project) -> str:
    for action in all_actions(project):
        if action.key == action_key:
            return action.label
    return action_key


def next_mode(current, step: int) -> tuple:
    """The next (or previous) entry of the mode list, as (mode, rear).
    current is a mode name or a (mode, rear) pair. Custom is skipped."""
    choices = [c for c in mode_choices() if c[0] != CUSTOM]
    if isinstance(current, str):
        current = (current, False)
    index = choices.index(tuple(current)) if tuple(current) in choices else (-1 if step > 0 else 0)
    return choices[(index + step) % len(choices)]


# ------------------------------------------------------------------ bindings

def _same_input(a: dict, b: dict) -> bool:
    if a.get("kind") != b.get("kind"):
        return False
    if a.get("kind") == "key":
        return a.get("vk") == b.get("vk") and a.get("mods") == b.get("mods")
    return a.get("guid") == b.get("guid") and a.get("input") == b.get("input")


def binding_for(bindings: list, action: str, kind: str):
    return next((b for b in bindings if b.get("action") == action and b.get("kind") == kind), None)


def set_binding(bindings: list, action: str, binding: dict) -> list:
    """Gives an action this input. One input can only do one thing, so any other
    action that had the same input loses it. Returns the actions that lost it."""
    binding = dict(binding, action=action)
    lost = [b["action"] for b in bindings if _same_input(b, binding) and b.get("action") != action]
    bindings[:] = [b for b in bindings
                   if not _same_input(b, binding)
                   and not (b.get("action") == action and b.get("kind") == binding.get("kind"))]
    bindings.append(binding)
    return lost


def clear_binding(bindings: list, action: str, kind: str) -> None:
    bindings[:] = [b for b in bindings if not (b.get("action") == action and b.get("kind") == kind)]


def actions_for_pad(bindings: list, guid: str, input_id: str) -> list:
    return [b["action"] for b in bindings
            if b.get("kind") == "pad" and b.get("guid") == guid and b.get("input") == input_id]


def key_bindings(bindings: list) -> list:
    return [b for b in bindings if b.get("kind") == "key"]


def describe_mods(mods: int) -> str:
    parts = []
    if mods & MOD_CONTROL:
        parts.append("Ctrl")
    if mods & MOD_ALT:
        parts.append("Alt")
    if mods & MOD_SHIFT:
        parts.append("Shift")
    if mods & MOD_WIN:
        parts.append("Win")
    return "+".join(parts)
