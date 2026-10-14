"""Buttons of game controllers, racing wheels, button boxes and pedals.

Uses SDL2, which reads every kind of controller Windows knows about, and keeps
reading while a game has the focus. Only button presses (and hat switch
directions) are reported. Nothing here needs a window.
"""
from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass

from . import paths

HAT_DIRECTIONS = (("up", 1), ("right", 2), ("down", 4), ("left", 8))


@dataclass
class PadEvent:
    guid: str
    device: str
    input: str          # "b12" for button 13, "h0up" for hat 1 pushed up
    text: str


@dataclass
class PadInfo:
    guid: str
    name: str
    buttons: int
    hats: int


def input_text(input_id: str, device: str) -> str:
    if input_id.startswith("b"):
        return f"Button {int(input_id[1:]) + 1} on {device}"
    if input_id.startswith("h"):
        number = "".join(ch for ch in input_id[1:] if ch.isdigit())
        direction = input_id[1 + len(number):]
        return f"Hat {int(number) + 1} {direction} on {device}"
    return f"{input_id} on {device}"


class GamepadWatcher:
    def __init__(self):
        self.sdl = None
        self.error = ""
        self._open = {}         # instance id -> [joystick, guid, name, previous buttons, previous hats]

    @property
    def available(self) -> bool:
        return self.sdl is not None

    def start(self) -> bool:
        if self.sdl is not None:
            return True
        os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
        if paths.is_built():
            bundled = paths.resource("sdl2")
            if os.path.isdir(bundled):
                os.environ["PYSDL2_DLL_PATH"] = bundled
        try:
            import sdl2
        except Exception as exc:
            self.error = f"Controller support is missing ({exc})"
            return False
        sdl2.SDL_SetHint(b"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", b"1")
        if sdl2.SDL_Init(sdl2.SDL_INIT_JOYSTICK) != 0:
            self.error = "Controllers could not be started: " + (sdl2.SDL_GetError() or b"").decode(errors="replace")
            return False
        sdl2.SDL_JoystickEventState(sdl2.SDL_IGNORE)     # we read the state ourselves
        self.sdl = sdl2
        self.error = ""
        return True

    def stop(self) -> None:
        if self.sdl is None:
            return
        for joy, *_rest in self._open.values():
            self.sdl.SDL_JoystickClose(joy)
        self._open = {}
        self.sdl.SDL_QuitSubSystem(self.sdl.SDL_INIT_JOYSTICK)
        self.sdl = None

    def _guid(self, joy) -> str:
        buf = ctypes.create_string_buffer(33)
        self.sdl.SDL_JoystickGetGUIDString(self.sdl.SDL_JoystickGetGUID(joy), buf, 33)
        return buf.value.decode(errors="replace")

    def _sync_devices(self) -> None:
        sdl = self.sdl
        for inst in list(self._open):
            joy = self._open[inst][0]
            if not sdl.SDL_JoystickGetAttached(joy):
                sdl.SDL_JoystickClose(joy)
                del self._open[inst]
        for index in range(sdl.SDL_NumJoysticks()):
            inst = sdl.SDL_JoystickGetDeviceInstanceID(index)
            if inst in self._open:
                continue
            joy = sdl.SDL_JoystickOpen(index)
            if not joy:
                continue
            name = (sdl.SDL_JoystickName(joy) or b"Controller").decode(errors="replace")
            buttons = [0] * max(0, sdl.SDL_JoystickNumButtons(joy))
            hats = [0] * max(0, sdl.SDL_JoystickNumHats(joy))
            # read the current state first, so a button held while plugging in is not a press
            sdl.SDL_JoystickUpdate()
            for i in range(len(buttons)):
                buttons[i] = sdl.SDL_JoystickGetButton(joy, i)
            for i in range(len(hats)):
                hats[i] = sdl.SDL_JoystickGetHat(joy, i)
            self._open[inst] = [joy, self._guid(joy), name, buttons, hats]

    def devices(self) -> list:
        if self.sdl is None:
            return []
        self.sdl.SDL_JoystickUpdate()
        self._sync_devices()
        return [PadInfo(guid, name, len(btn), len(hats)) for _j, guid, name, btn, hats in self._open.values()]

    def poll(self) -> list:
        """Presses since the last call."""
        if self.sdl is None:
            return []
        sdl = self.sdl
        sdl.SDL_JoystickUpdate()
        self._sync_devices()
        events = []
        for joy, guid, name, buttons, hats in self._open.values():
            for i in range(len(buttons)):
                now = sdl.SDL_JoystickGetButton(joy, i)
                if now and not buttons[i]:
                    events.append(PadEvent(guid, name, f"b{i}", input_text(f"b{i}", name)))
                buttons[i] = now
            for i in range(len(hats)):
                now = sdl.SDL_JoystickGetHat(joy, i)
                for direction, bit in HAT_DIRECTIONS:
                    if now & bit and not hats[i] & bit:
                        input_id = f"h{i}{direction}"
                        events.append(PadEvent(guid, name, input_id, input_text(input_id, name)))
                hats[i] = now
        return events
