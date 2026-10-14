"""A pretend sound system for tests: every device runs in real time on its own,
slightly wrong clock, the way real sound cards do."""
import threading
import time
from types import SimpleNamespace

import numpy as np


class _Stream:
    def __init__(self, rate, frames, channels, callback, tones=None):
        self.rate, self.frames, self.channels = rate, frames, channels
        self.callback, self.tones = callback, tones
        self.silent = False
        self.recorded = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=1.0)

    def close(self):
        pass

    def _run(self):
        start, done = time.perf_counter(), 0
        while not self._stop.is_set():
            block = np.zeros((self.frames, self.channels), dtype=np.float32)
            if self.tones is None:                      # an output
                self.callback(block, self.frames, None, None)
                self.recorded.append(block.copy())
            else:                                       # an input
                t = (done + np.arange(self.frames)) / 48000.0
                for ch, freq in self.tones.items():
                    block[:, ch] = 0.4 * np.sin(2 * np.pi * freq * t)
                if not self.silent:             # Windows loopback sends nothing during silence
                    self.callback(block, self.frames, None, None)
            done += self.frames
            wait = start + done / self.rate - time.perf_counter()
            if wait > 0:
                time.sleep(wait)


class FakeSoundDevice:
    """Stands in for the sounddevice module."""

    def __init__(self, devices):
        # devices: list of dicts with name, inputs, outputs, ppm, tones
        self.devices = devices
        self.default = SimpleNamespace(hostapi=0)
        self.streams = {}

    def query_hostapis(self):
        return [{"name": "Pretend audio"}]

    def query_devices(self):
        return [{"name": d["name"], "hostapi": 0, "max_input_channels": d.get("inputs", 0),
                 "max_output_channels": d.get("outputs", 0), "default_samplerate": 48000.0}
                for d in self.devices]

    def _terminate(self):
        pass

    def _initialize(self):
        pass

    def OutputStream(self, device, channels, samplerate, callback, **_kw):
        d = self.devices[device]
        s = _Stream(samplerate * (1 + d.get("ppm", 0) * 1e-6), 441, channels, callback)
        self.streams[d["name"]] = s
        return s

    def InputStream(self, device, channels, samplerate, callback, blocksize=480, **_kw):
        d = self.devices[device]
        s = _Stream(samplerate * (1 + d.get("ppm", 0) * 1e-6), blocksize, channels, callback,
                    tones=d.get("tones", {}))
        s.silent = bool(d.get("silent"))
        self.streams[d["name"]] = s
        return s
