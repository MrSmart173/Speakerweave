"""Sound card side: lists devices and runs the live streams.

Uses the sounddevice library (WASAPI on Windows). Capturing "what the PC is
playing" from a normal output device needs the optional PyAudioWPatch library.
"""
from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass

import numpy as np

from .dsp import PinkNoise
from .engine import Engine, AdaptiveFifo
from .model import OFF, Project

MAX_SOURCE_CHANNELS = 8
TEST_STEP_SECONDS = 1.2
EXTRA_BUFFER_MS = 40.0      # how far behind an extra source runs, to absorb clock drift
EXCLUSIVE_LATENCY_S = 0.006     # what an output used on its own is asked to buffer


def _same_rate(rate: float, main: float) -> None:
    if abs(rate - main) > 1.0:
        raise RuntimeError(f"it runs at {rate:.0f} Hz but the PC sound at {main:.0f} Hz. Set both "
                           f"to the same rate (Sound control panel, Advanced tab)")


@dataclass
class DeviceInfo:
    name: str           # unique name shown in the app and stored in profiles
    index: int
    inputs: int
    outputs: int
    samplerate: float
    wasapi: bool = False


def _sd():
    import sounddevice as sd
    return sd


def list_devices() -> list[DeviceInfo]:
    """All sound devices. On Windows only the WASAPI ones, so each device
    shows up once instead of once per driver type."""
    sd = _sd()
    apis = sd.query_hostapis()
    wasapi = next((i for i, a in enumerate(apis) if "WASAPI" in a["name"]), None)
    if wasapi is not None:
        api = wasapi
    else:
        api = sd.default.hostapi if sd.default.hostapi >= 0 else 0
    found: list[DeviceInfo] = []
    seen: dict[tuple, int] = {}
    for index, d in enumerate(sd.query_devices()):
        if d["hostapi"] != api:
            continue
        for is_out in (True, False):
            chans = d["max_output_channels"] if is_out else d["max_input_channels"]
            if chans <= 0:
                continue
            key = (d["name"], is_out)
            seen[key] = seen.get(key, 0) + 1
            name = d["name"] if seen[key] == 1 else f"{d['name']} ({seen[key]})"
            found.append(DeviceInfo(name, index,
                                    0 if is_out else chans, chans if is_out else 0,
                                    float(d["default_samplerate"]), wasapi is not None))
    return found


def refresh() -> None:
    """Ask the system for the device list again (after plugging something in).
    Only call this while no audio is running."""
    sd = _sd()
    try:
        sd._terminate()
        sd._initialize()
    except Exception:
        pass


def output_count_hint():
    """A very cheap number that changes when sound outputs are plugged in or
    removed (Windows only), so the list only has to be read again then."""
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes
        return int(ctypes.windll.winmm.waveOutGetNumDevs())
    except Exception:
        return None


def list_outputs() -> list[DeviceInfo]:
    return [d for d in list_devices() if d.outputs > 0]


def list_inputs() -> list[DeviceInfo]:
    return [d for d in list_devices() if d.inputs > 0]


def loopback_available() -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        import pyaudiowpatch  # noqa: F401
        return True
    except Exception:
        return False


def list_loopbacks() -> list[DeviceInfo]:
    """Output devices that can be listened in on (Windows + PyAudioWPatch)."""
    if not loopback_available():
        return []
    import pyaudiowpatch as pa
    p = pa.PyAudio()
    try:
        return [DeviceInfo(d["name"], int(d["index"]), int(d["maxInputChannels"]), 0,
                           float(d["defaultSampleRate"]), True)
                for d in p.get_loopback_device_info_generator()]
    finally:
        p.terminate()


def _extra(info: DeviceInfo):
    if info.wasapi:
        try:
            return _sd().WasapiSettings(auto_convert=True)
        except Exception:
            return None
    return None


class AudioRunner:
    """Owns the live streams: one capture and one output per enabled device."""

    def __init__(self, project: Project, engine: Engine):
        self.project = project
        self.engine = engine
        self.running = False
        self.errors: list[str] = []
        self.fifos: dict[str, AdaptiveFifo] = {}
        self.load = 0.0             # share of each block's time the sound work takes, smoothed
        self.load_peak = 0.0
        self.blocks_done = 0
        self._streams: list = []
        self._pa = None
        self._pa_stream = None
        self._pa_extra = None           # PyAudio for the extra sources' loopback streams
        self._extra_streams: list = []
        self._test_thread = None
        self._filler_thread = None
        self._stop = threading.Event()
        self._feed_lock = threading.Lock()
        self._last_real = 0.0
        self.test_role = ""         # role the test signal is playing right now
        self.callback_errors = 0
        # where the delay comes from, as Windows reports it (seconds)
        self.input_latency = 0.0
        self.output_latency: dict = {}     # {device id: seconds}
        self.exclusive: set = set()        # outputs SpeakerWeave has to itself right now
        self.notes: list = []              # things worth knowing that are not problems

    # -------------------------------------------------------------- lifecycle
    def start(self) -> list[str]:
        """Starts everything. Returns a list of problems (empty = all good)."""
        self.stop()
        self.errors = []
        self.notes = []
        self.output_latency = {}
        self.exclusive = set()
        self.input_latency = 0.0
        self._stop.clear()
        p = self.project
        try:
            sr, channels, opener = self._prepare_input()
        except Exception as exc:
            self.errors.append(f"Input: {exc}")
            return self.errors

        self.engine.layout_override = "7.1" if p.input_kind == "test" else ""
        self.engine.configure(sr, channels)
        self.fifos = {}
        try:
            outputs = {d.name: d for d in list_outputs()}
        except Exception as exc:
            self.errors.append(f"Could not list sound devices: {exc}")
            return self.errors

        sd = _sd()
        for dev in p.devices:
            if not dev.enabled:
                continue
            info = outputs.get(dev.name)
            if info is None:
                self.errors.append(f"{dev.title}: not connected right now")
                continue
            if p.input_kind == "loopback" and p.input_name.replace(" [Loopback]", "") == dev.name:
                self.errors.append(f"{dev.title}: skipped, it is the device being listened to "
                                   f"(playing into it would cause an echo loop)")
                continue
            channels_open = min(dev.channels, info.outputs)
            opened = None
            if p.exclusive_outputs and info.wasapi:
                try:
                    opened = self._open_exclusive(sd, info, sr, channels_open, dev.channels)
                    self.exclusive.add(dev.id)
                except Exception:
                    self.notes.append(f"{dev.title} could not be used on its own, so it plays "
                                      f"through Windows' mixer (a few milliseconds later)")
            if opened is None:
                fifo = AdaptiveFifo(dev.channels, sr, p.buffer_ms, block=p.blocksize)
                try:
                    stream = sd.OutputStream(
                        device=info.index, channels=channels_open, samplerate=sr,
                        dtype="float32", latency="low", extra_settings=_extra(info),
                        callback=self._make_output_callback(fifo, channels_open))
                    stream.start()
                except Exception as exc:
                    self.errors.append(f"{dev.title}: {exc}")
                    continue
                opened = (stream, fifo)
            stream, fifo = opened
            self.fifos[dev.id] = fifo
            self._streams.append(stream)
            try:
                self.output_latency[dev.id] = float(stream.latency)
            except Exception:
                self.output_latency[dev.id] = 0.0

        if not self.fifos:
            self.errors.append("No output device could be started")
            self.stop()
            return self.errors
        try:
            opener()
        except Exception as exc:
            self.errors.append(f"Input: {exc}")
            self.stop()
            return self.errors
        self._open_extras(sr)
        if p.input_kind != "test":
            self._last_real = time.perf_counter()
            self._filler_thread = threading.Thread(target=self._fill_silence, args=(sr, channels),
                                                   daemon=True)
            self._filler_thread.start()
        self.running = True
        return self.errors

    def _open_exclusive(self, sd, info, sr: float, channels_open: int, channels: int):
        """Opens an output for SpeakerWeave alone (WASAPI exclusive mode). Windows' sound
        mixer and its buffer are left out, which takes several milliseconds off. The output
        plays at its own sample rate, the buffer converts. Raises when the device refuses."""
        rate = float(info.samplerate or sr)
        fifo = AdaptiveFifo(channels, sr, self.project.buffer_ms, block=self.project.blocksize,
                            out_rate=rate)
        stream = sd.OutputStream(
            device=info.index, channels=channels_open, samplerate=rate, dtype="float32",
            latency=EXCLUSIVE_LATENCY_S, extra_settings=sd.WasapiSettings(exclusive=True),
            callback=self._make_output_callback(fifo, channels_open))
        stream.start()
        return stream, fifo

    def stop(self) -> None:
        self.running = False
        self._stop.set()
        for stream in self._extra_streams:
            try:
                if hasattr(stream, "stop_stream"):
                    stream.stop_stream()
                else:
                    stream.stop()
                stream.close()
            except Exception:
                pass
        self._extra_streams = []
        self.engine.extra_fifos = {}
        if self._pa_extra is not None:
            try:
                self._pa_extra.terminate()
            except Exception:
                pass
            self._pa_extra = None
        if self._test_thread is not None:
            self._test_thread.join(timeout=1.0)
            self._test_thread = None
        if self._filler_thread is not None:
            self._filler_thread.join(timeout=1.0)
            self._filler_thread = None
        if self._pa_stream is not None:
            try:
                self._pa_stream.stop_stream()
                self._pa_stream.close()
            except Exception:
                pass
            self._pa_stream = None
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None
        for stream in self._streams:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        self._streams = []
        self.test_role = ""

    # -------------------------------------------------------------- audio flow
    def _feed(self, block: np.ndarray, real: bool = True) -> None:
        """One block of captured audio in, one block per device out."""
        began = time.perf_counter()
        if real:
            self._last_real = began
        try:
            with self._feed_lock:
                outs = self.engine.process(block)
                for dev_id, data in outs.items():
                    fifo = self.fifos.get(dev_id)
                    if fifo is not None:
                        fifo.write(data)
                self._share_target()
        except Exception:
            self.callback_errors += 1
        self._measure(time.perf_counter() - began, len(block))

    def _measure(self, spent: float, frames: int) -> None:
        """How much of a block's own time the work on it took (1.0: all of it, and the
        sound would start to break up)."""
        sr = getattr(self.engine, "sr", 0.0) or 48000.0
        if frames <= 0:
            return
        load = spent * sr / frames
        self.blocks_done += 1
        self.load = load if self.blocks_done == 1 else self.load * 0.97 + load * 0.03
        self.load_peak = max(self.load_peak, load)

    def take_load_peak(self) -> float:
        """The highest block load since the last call."""
        peak, self.load_peak = self.load_peak, 0.0
        return peak

    def _share_target(self) -> None:
        """Every output plays the same distance behind the PC, so they stay in line:
        the safety buffer chosen, or what the most demanding device needs, whichever
        is larger. With a safety buffer of 0 ms that is as little delay as works."""
        fifos = list(self.fifos.values())
        if not fifos:
            return
        chosen = int(self.project.buffer_ms * fifos[0].sr / 1000.0)
        target = max([chosen] + [f.need for f in fifos])
        for fifo in fifos:
            if fifo.target != target:
                fifo.set_target(target)

    def delay_parts(self) -> dict:
        """Where SpeakerWeave's delay comes from, in milliseconds: "listening" (Windows
        handing over the PC sound), "buffer" (the room kept so no output runs dry, and the
        block the engine works on), "output" (Windows' buffer of the slowest output) and
        "speakers" (the most delay any playing speaker has been given to line it up)."""
        if not self.fifos:
            return {"listening": 0.0, "buffer": 0.0, "output": 0.0, "speakers": 0.0}
        # on average a device has half of its own block still to play, and the engine
        # works one block at a time. The slowest device is the one you hear last.
        buffer = max((f.target + f._max_read / 2 + self.project.blocksize) * 1000.0 / f.sr
                     for f in self.fifos.values())
        output = max(self.output_latency.values(), default=0.0) * 1000.0
        p = self.project
        speakers = max((d.trim_ms + s.delay_ms for d, s in p.all_speakers()
                        if d.enabled and d.id in self.fifos and s.role != OFF), default=0.0)
        return {"listening": self.input_latency * 1000.0, "buffer": buffer,
                "output": output, "speakers": max(0.0, speakers)}

    def delay_ms(self) -> float:
        """How far the speakers play behind the PC sound arriving, from SpeakerWeave and
        Windows' buffers (each device adds its own lag inside on top)."""
        if not self.fifos:
            return 0.0
        return sum(self.delay_parts().values())

    def _fill_silence(self, sr: float, channels: int) -> None:
        """Windows sends nothing at all while nothing is playing. Then this keeps
        the outputs fed with silence, so test sounds and meters still work and
        the outputs stay in step for when the sound comes back."""
        n = self.project.blocksize
        period = n / sr
        quiet = np.zeros((n, channels), dtype=np.float32)
        next_time = time.perf_counter()
        while not self._stop.is_set():
            now = time.perf_counter()
            if now - self._last_real < 0.06:
                next_time = now
                time.sleep(0.01)
                continue
            self._feed(quiet, real=False)
            next_time += period
            wait = next_time - time.perf_counter()
            if wait > 0:
                time.sleep(wait)
            elif wait < -0.25:
                next_time = time.perf_counter()

    def _make_output_callback(self, fifo: AdaptiveFifo, channels: int):
        def callback(outdata, frames, _time, _status):
            try:
                outdata[:] = fifo.read(frames)[:, :channels]
            except Exception:
                outdata.fill(0)
                self.callback_errors += 1
        return callback

    # -------------------------------------------------------------- extra sources
    def _open_extras(self, sr: float) -> None:
        """Opens every extra source (SimHub effects, a spotter app ...). Each one
        fills its own buffer, which the engine reads block by block in step with
        the main sound, so the clocks of the devices never drift apart."""
        self.engine.extra_fifos = {}
        for src in self.project.extra_sources:
            if not src.enabled or not src.name:
                continue
            try:
                self._open_extra(src, sr)
            except Exception as exc:
                self.errors.append(f"{src.label}: {exc}")

    def _open_extra(self, src, sr: float) -> None:
        main = self.project.input_name if self.project.input_kind == src.kind else None
        if src.name == main:
            raise RuntimeError("it is the same device as the PC sound, choose another one")
        if src.kind == "loopback":
            if not loopback_available():
                raise RuntimeError("listening to an output device needs the PyAudioWPatch library")
            import pyaudiowpatch as pa
            if self._pa_extra is None:
                self._pa_extra = pa.PyAudio()
            info = next((d for d in self._pa_extra.get_loopback_device_info_generator()
                         if d["name"] == src.name), None)
            if info is None:
                raise RuntimeError("not connected right now")
            total, rate = int(info["maxInputChannels"]), float(info["defaultSampleRate"])
            _same_rate(rate, sr)
            fifo = AdaptiveFifo(total, sr, EXTRA_BUFFER_MS)

            def on_audio(in_data, frame_count, time_info, status):
                fifo.write(np.frombuffer(in_data, dtype=np.float32).reshape(-1, total))
                return (None, pa.paContinue)
            stream = self._pa_extra.open(format=pa.paFloat32, channels=total, rate=int(rate),
                                         input=True, input_device_index=int(info["index"]),
                                         frames_per_buffer=self.project.blocksize,
                                         stream_callback=on_audio)
        else:
            info = next((d for d in list_inputs() if d.name == src.name), None)
            if info is None:
                raise RuntimeError("not connected right now")
            total = min(info.inputs, MAX_SOURCE_CHANNELS)
            _same_rate(info.samplerate, sr)
            fifo = AdaptiveFifo(total, sr, EXTRA_BUFFER_MS)
            sd = _sd()
            stream = sd.InputStream(device=info.index, channels=total, samplerate=sr,
                                    dtype="float32", blocksize=self.project.blocksize,
                                    latency="low", extra_settings=_extra(info),
                                    callback=lambda indata, frames, t, status: fifo.write(indata))
            stream.start()
        self._extra_streams.append(stream)
        self.engine.extra_fifos[src.id] = fifo

    # -------------------------------------------------------------- inputs
    def _prepare_input(self):
        """Returns (sample rate, channels, function that starts capturing)."""
        p = self.project
        if p.input_kind == "test":
            return 48000.0, 8, self._start_test_signal
        if p.input_kind == "loopback":
            return self._prepare_loopback()
        info = next((d for d in list_inputs() if d.name == p.input_name), None)
        if info is None:
            raise RuntimeError(f"input device '{p.input_name}' was not found")
        channels = min(info.inputs, MAX_SOURCE_CHANNELS)
        sr = info.samplerate

        def opener():
            sd = _sd()
            stream = sd.InputStream(
                device=info.index, channels=channels, samplerate=sr, dtype="float32",
                blocksize=p.blocksize, latency="low", extra_settings=_extra(info),
                callback=lambda indata, frames, t, status: self._feed(indata))
            stream.start()
            self._streams.append(stream)
            try:
                self.input_latency = float(stream.latency)
            except Exception:
                self.input_latency = 0.0
        return sr, channels, opener

    def _prepare_loopback(self):
        p = self.project
        if not loopback_available():
            raise RuntimeError("listening to an output device needs the PyAudioWPatch library")
        import pyaudiowpatch as pa
        from . import cable
        self._pa = pa.PyAudio()
        found = {d["name"]: d for d in self._pa.get_loopback_device_info_generator()}
        info = found.get(cable.pick(p.input_name, found))
        if info is None:
            raise RuntimeError(f"'{p.input_name}' was not found")
        total = int(info["maxInputChannels"])
        sr = float(info["defaultSampleRate"])

        def on_audio(in_data, frame_count, time_info, status):
            block = np.frombuffer(in_data, dtype=np.float32).reshape(-1, total)
            self._feed(block[:, :MAX_SOURCE_CHANNELS])
            return (None, pa.paContinue)

        def opener():
            self._pa_stream = self._pa.open(
                format=pa.paFloat32, channels=total, rate=int(sr), input=True,
                input_device_index=int(info["index"]), frames_per_buffer=p.blocksize,
                stream_callback=on_audio)
            try:
                self.input_latency = float(self._pa_stream.get_input_latency())
            except Exception:
                self.input_latency = 0.0
        return sr, min(total, MAX_SOURCE_CHANNELS), opener

    def _start_test_signal(self) -> None:
        self._test_thread = threading.Thread(target=self._test_loop, daemon=True)
        self._test_thread.start()

    def _test_loop(self) -> None:
        """Built in test: noise that steps through the 7.1 channels one by one,
        so you can hear which speaker ended up with which role."""
        sr, n = 48000.0, self.project.blocksize
        noise = PinkNoise(3)
        roles = self.engine.source_roles
        step = int(TEST_STEP_SECONDS * sr)
        fade = int(0.03 * sr)
        pos = 0
        start = time.perf_counter()
        sent = 0
        while not self._stop.is_set():
            block = np.zeros((n, 8), dtype=np.float32)
            ch = (pos // step) % 8
            t = pos % step + np.arange(n)
            env = np.clip(np.minimum(t, step - t) / fade, 0.0, 1.0)
            block[:, ch] = noise.block(n) * env * 0.35
            self.test_role = roles[ch] if ch < len(roles) else ""
            self._feed(block)
            pos += n
            sent += n
            wait = start + sent / sr - time.perf_counter()
            if wait > 0:
                time.sleep(wait)

    # -------------------------------------------------------------- status
    def status(self) -> dict:
        """{device id: (buffer in ms, clock correction in ppm, interruptions)}"""
        return {dev_id: (f.fill_ms, (f.ratio - 1.0) * 1e6, f.glitches)
                for dev_id, f in self.fifos.items()}
