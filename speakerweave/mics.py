"""Microphones on the room map: which recording devices count as one, and how loud each
microphone on the map hears the room right now.

Only the microphones you put on the map (and left ticked) are opened, and only to measure
their level. Nothing they hear is recorded or kept.
"""
from __future__ import annotations

import re
import threading

import numpy as np

from . import backend
from .speaker_library import recognise

# recording devices that are the PC's own sound, not a microphone
NOT_A_MIC = re.compile(r"Stereo Mix|What U Hear|Wave Out|Wave Mix|Loopback|Rec\. Playback",
                       re.IGNORECASE)


def is_microphone(name: str) -> bool:
    if NOT_A_MIC.search(name or ""):
        return False
    entry = recognise(name or "")
    return entry is None or entry.category != "virtual"


class MicMeters:
    """Keeps one small input stream open per microphone on the map, and the loudest
    moment each one heard since it was last asked."""

    def __init__(self):
        self._streams: dict = {}         # mic id -> (device name, stream)
        self._peaks: dict = {}
        self._lock = threading.Lock()
        self.problems: dict = {}         # mic id -> why it could not be opened

    def follow(self, mics, inputs) -> None:
        """Opens the microphones that are on the map and ticked, closes the others.
        inputs: the PC's recording devices (backend.DeviceInfo)."""
        by_name = {d.name: d for d in inputs}
        wanted = {m.id: m.name for m in mics if m.enabled and m.name in by_name}
        for mic_id in list(self._streams):
            name, _stream = self._streams[mic_id]
            if wanted.get(mic_id) != name:
                self._close(mic_id)
        self.problems = {m.id: "not connected right now" for m in mics
                         if m.enabled and m.name not in by_name}
        for mic_id, name in wanted.items():
            if mic_id in self._streams:
                continue
            try:
                self._streams[mic_id] = (name, self._open(mic_id, by_name[name]))
            except Exception as exc:
                self.problems[mic_id] = str(exc)

    def _open(self, mic_id: str, info):
        sd = backend._sd()
        channels = max(1, min(int(info.inputs), 2))

        def heard(indata, _frames, _time, _status):
            peak = float(np.max(np.abs(indata))) if len(indata) else 0.0
            with self._lock:
                self._peaks[mic_id] = max(self._peaks.get(mic_id, 0.0), peak)
        stream = sd.InputStream(device=info.index, channels=channels, samplerate=info.samplerate,
                                dtype="float32", extra_settings=backend._extra(info), callback=heard)
        stream.start()
        return stream

    def _close(self, mic_id: str) -> None:
        _name, stream = self._streams.pop(mic_id, (None, None))
        with self._lock:
            self._peaks.pop(mic_id, None)
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    def close_all(self) -> None:
        for mic_id in list(self._streams):
            self._close(mic_id)

    def take_levels(self) -> dict:
        """{mic id: loudest moment (0 to 1)} since the last call."""
        with self._lock:
            levels, self._peaks = dict(self._peaks), {k: 0.0 for k in self._peaks}
        return levels

    @property
    def open_count(self) -> int:
        return len(self._streams)
