"""RGB lighting through OpenRGB (https://openrgb.org).

OpenRGB talks to the actual hardware. This module connects to its SDK server
(through our own connection in lights.py) and drives the LEDs of whatever
device you link to a speaker.
"""
from __future__ import annotations

import colorsys
import math
import threading
import time

from .lights import LightsError, OpenRGBConnection
from .model import Project, ROLE_COLORS

RGB_MODES = {
    "static": "Static colour",
    "pulse": "Pulse with the sound",
    "vu": "Level meter along the LEDs",
    "rainbow": "Rainbow",
}


def hex_to_rgb(text: str) -> tuple[int, int, int]:
    text = (text or "").lstrip("#")
    if len(text) != 6:
        return (255, 255, 255)
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (255, 255, 255)


def level_to_unit(peak: float) -> float:
    """Maps a peak level to 0..1 on a 48 dB scale, which looks natural."""
    if peak <= 1e-4:
        return 0.0
    return min(1.0, max(0.0, 1.0 + 20.0 * math.log10(peak) / 48.0))


def led_colors(mode: str, base: tuple, level: float, n_leds: int, t: float) -> list[tuple]:
    """Colour of each LED. level is 0..1, t is seconds since start."""
    n_leds = max(1, n_leds)
    if mode == "static":
        return [base] * n_leds
    if mode == "pulse":
        k = 0.08 + 0.92 * level
        return [tuple(int(c * k) for c in base)] * n_leds
    if mode == "vu":
        lit = level * n_leds
        out = []
        for i in range(n_leds):
            k = min(1.0, max(0.0, lit - i))
            out.append(tuple(int(c * (0.04 + 0.96 * k)) for c in base))
        return out
    if mode == "rainbow":
        out = []
        for i in range(n_leds):
            r, g, b = colorsys.hsv_to_rgb((t * 0.15 + i / n_leds) % 1.0, 1.0, 0.25 + 0.75 * level)
            out.append((int(r * 255), int(g * 255), int(b * 255)))
        return out
    return [base] * n_leds


class RgbController:
    """Background thread that pushes colours about 25 times a second.

    A speaker is linked to an OpenRGB device, or to one zone of a device
    (for example one addressable header of a motherboard or LED controller).
    """

    def __init__(self, project: Project, level_source):
        self.project = project
        self.level_source = level_source    # function(speaker id) -> peak 0..1
        self.client = None
        self.error = ""
        self._thread = None
        self._stop = threading.Event()
        self._smooth: dict[str, float] = {}

    @property
    def connected(self) -> bool:
        return self.client is not None

    def connect(self) -> bool:
        self.disconnect()
        client = OpenRGBConnection(self.project.rgb_host, int(self.project.rgb_port), "SpeakerWeave")
        try:
            client.connect()
        except LightsError as exc:
            self.client = None
            self.error = (f"Could not connect to OpenRGB: {exc}. Open OpenRGB and press "
                          f"Start Server on its SDK Server tab first.")
            return False
        self.client = client
        self.error = ""
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    def disconnect(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self.client is not None:
            self.client.close()
            self.client = None

    def targets(self) -> list[tuple[str, str, int]]:
        """Everything a speaker can be linked to: (device, zone, number of LEDs).
        zone "" means the whole device."""
        client = self.client
        if not client:
            return []
        out = []
        for dev in client.devices:
            out.append((dev.name, "", dev.led_count))
            if len(dev.zones) > 1:
                for zone in dev.zones:
                    out.append((dev.name, zone.name, zone.led_count))
        return out

    def frame(self, t: float) -> dict:
        """Colours for every linked target right now:
        {(device, zone): [(r, g, b), ...]}."""
        sizes = {(d, z): n for d, z, n in self.targets()}
        out = {}
        for _, spk in self.project.all_speakers():
            key = (spk.rgb_device, spk.rgb_zone)
            if not spk.rgb_device or key not in sizes:
                continue
            target = level_to_unit(self.level_source(spk.id))
            prev = self._smooth.get(spk.id, 0.0)
            level = target if target > prev else prev + (target - prev) * 0.25
            self._smooth[spk.id] = level
            base = hex_to_rgb(spk.rgb_color or ROLE_COLORS.get(spk.role, "#ffffff"))
            out[key] = led_colors(spk.rgb_mode, base, level, sizes[key], t)
        return out

    def _loop(self) -> None:
        start = time.perf_counter()
        while not self._stop.is_set():
            client = self.client
            if client is None:
                return
            try:
                if client.changed:                  # devices were plugged in or removed
                    client.refresh()
                frame = self.frame(time.perf_counter() - start)
                by_name = {d.name: d for d in client.devices}
                for (name, zone_name), colors in frame.items():
                    dev = by_name[name]
                    if zone_name:
                        zone = next(z for z in dev.zones if z.name == zone_name)
                        client.set_zone_leds(dev.index, zone.index, colors)
                    else:
                        client.set_leds(dev.index, colors)
            except Exception as exc:
                self.error = f"RGB connection lost ({exc})"
                self.client = None
                return
            time.sleep(0.04)
