"""The tone generator: a tone of any pitch from 1 Hz to 20,000 Hz, as a steady tone, beeps,
a pattern of notes and rests, or a sweep from one pitch to another.

A tone is described by a plain dict (kept in the settings), and ToneGenerator turns it into
samples block by block for the engine. Every beep starts and ends with a short fade, so no
click is heard, and square and saw waves are drawn band limited (PolyBLEP), so a high tone
does not fold back into a buzz of lower ones."""
from __future__ import annotations

import math

import numpy as np

LOWEST, HIGHEST = 1.0, 20000.0
WAVES = {"sine": "Sine", "square": "Square", "triangle": "Triangle", "saw": "Saw"}
KINDS = {"steady": "Steady tone", "beeps": "Beeps", "pattern": "Pattern", "sweep": "Sweep"}
FADE_S = 0.004              # every beep fades in and out over this long
MAX_STEPS = 64
LOW_WARNING_HZ = 20.0       # below this most speakers cannot play a tone, and can be harmed

DEFAULT = {
    "kind": "steady", "hz": 440.0, "wave": "sine", "db": -20.0,
    "beep_ms": 200, "gap_ms": 300, "repeat": 0,
    "steps": [[440.0, 250], [0.0, 120], [660.0, 250], [0.0, 120]],
    "sweep_from": 20.0, "sweep_to": 20000.0, "sweep_s": 10.0, "sweep_log": True,
    "sweep_back": False,
}

# name -> steps of [Hz, milliseconds] (0 Hz is a rest)
PATTERNS = {
    "Two tone alarm": [[880.0, 250], [660.0, 250]],
    "Countdown": [[500.0, 120], [0.0, 880], [500.0, 120], [0.0, 880], [500.0, 120], [0.0, 880],
                  [1000.0, 600], [0.0, 1400]],
    "SOS": [[700.0, 100], [0.0, 100], [700.0, 100], [0.0, 100], [700.0, 100], [0.0, 300],
            [700.0, 300], [0.0, 100], [700.0, 300], [0.0, 100], [700.0, 300], [0.0, 300],
            [700.0, 100], [0.0, 100], [700.0, 100], [0.0, 100], [700.0, 100], [0.0, 1000]],
    "Scale up": [[261.63, 220], [293.66, 220], [329.63, 220], [349.23, 220], [392.0, 220],
                 [440.0, 220], [493.88, 220], [523.25, 440], [0.0, 500]],
    "Octaves (speaker check)": [[31.5, 1000], [63.0, 1000], [125.0, 1000], [250.0, 1000],
                                [500.0, 1000], [1000.0, 1000], [2000.0, 1000], [4000.0, 1000],
                                [8000.0, 1000], [16000.0, 1000], [0.0, 1000]],
    "Heartbeat": [[55.0, 90], [0.0, 120], [50.0, 120], [0.0, 670]],
}


def clamp_hz(value, rest_ok: bool = False) -> float:
    try:
        hz = float(value)
    except (TypeError, ValueError):
        return 440.0
    if not math.isfinite(hz):
        return 440.0
    if rest_ok and hz <= 0.0:
        return 0.0
    return float(min(HIGHEST, max(LOWEST, hz)))


def _number(value, low, high, default):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v):
        return default
    return min(high, max(low, v))


def clean_steps(steps) -> list:
    """[[Hz, ms], ...] with every step in range; 0 Hz is a rest."""
    out = []
    for step in steps if isinstance(steps, list) else []:
        if isinstance(step, (list, tuple)) and len(step) >= 2:
            ms = int(_number(step[1], 10, 60000, 0))
            if ms:
                out.append([clamp_hz(step[0], rest_ok=True), ms])
    return out[:MAX_STEPS]


def clean(spec) -> dict:
    """A tone description with every value in range, missing ones from DEFAULT."""
    spec = spec if isinstance(spec, dict) else {}
    out = dict(DEFAULT)
    out["kind"] = spec.get("kind") if spec.get("kind") in KINDS else DEFAULT["kind"]
    out["wave"] = spec.get("wave") if spec.get("wave") in WAVES else DEFAULT["wave"]
    out["hz"] = clamp_hz(spec.get("hz", DEFAULT["hz"]))
    out["db"] = _number(spec.get("db"), -60.0, 0.0, DEFAULT["db"])
    out["beep_ms"] = int(_number(spec.get("beep_ms"), 10, 10000, DEFAULT["beep_ms"]))
    out["gap_ms"] = int(_number(spec.get("gap_ms"), 0, 10000, DEFAULT["gap_ms"]))
    out["repeat"] = int(_number(spec.get("repeat"), 0, 9999, 0))
    out["steps"] = clean_steps(spec.get("steps")) or [list(s) for s in DEFAULT["steps"]]
    out["sweep_from"] = clamp_hz(spec.get("sweep_from", DEFAULT["sweep_from"]))
    out["sweep_to"] = clamp_hz(spec.get("sweep_to", DEFAULT["sweep_to"]))
    out["sweep_s"] = _number(spec.get("sweep_s"), 0.2, 600.0, DEFAULT["sweep_s"])
    out["sweep_log"] = bool(spec.get("sweep_log", DEFAULT["sweep_log"]))
    out["sweep_back"] = bool(spec.get("sweep_back", DEFAULT["sweep_back"]))
    return out


def clean_patterns(patterns) -> dict:
    """Saved patterns: {name: steps}, each with at least one step."""
    out = {}
    if not isinstance(patterns, dict):
        return out
    for name, steps in list(patterns.items())[:50]:
        name = " ".join(str(name).split())[:40]
        good = clean_steps(steps)
        if name and good and name not in PATTERNS:
            out[name] = good
    return out


def parse_steps(text: str) -> list:
    """Steps typed as "440 200, rest 100, 880 200" or "440:200; 0:100": a pitch in Hz (0 or
    rest for a pause) and a length in milliseconds."""
    steps = []
    for part in str(text or "").replace(";", ",").replace("\n", ",").split(","):
        bits = part.replace(":", " ").replace("x", " ").split()
        if len(bits) < 2:
            continue
        hz = 0.0 if bits[0].lower() in ("rest", "pause", "-") else bits[0].lower().replace("hz", "")
        ms = bits[1].lower().replace("ms", "")
        try:
            steps.append([clamp_hz(hz, rest_ok=True), int(max(10, min(60000, float(ms))))])
        except ValueError:
            continue
    return steps[:MAX_STEPS]


def steps_text(steps: list) -> str:
    return ", ".join(("rest" if hz <= 0 else f"{hz:g}") + f" {int(ms)}" for hz, ms in steps)


def describe(spec: dict) -> str:
    """One line on what plays, for the status text."""
    s = clean(spec)
    wave = WAVES[s["wave"]].lower()
    if s["kind"] == "sweep":
        text = f"a {wave} sweep from {hz_text(s['sweep_from'])} to {hz_text(s['sweep_to'])} " \
               f"over {s['sweep_s']:g} s"
        if s["sweep_back"]:
            text += " and back"
    elif s["kind"] == "pattern":
        notes = sum(1 for hz, _ms in s["steps"] if hz > 0)
        text = f"a pattern of {notes} note{'s' if notes != 1 else ''} ({wave})"
    elif s["kind"] == "beeps":
        text = f"{hz_text(s['hz'])} {wave} beeps, {s['beep_ms']} ms on and {s['gap_ms']} ms off"
    else:
        return f"a steady {hz_text(s['hz'])} {wave} tone at {s['db']:.0f} dB"
    if s["repeat"]:
        text += f", {s['repeat']} time{'s' if s['repeat'] != 1 else ''}"
    return text + f" at {s['db']:.0f} dB"


def hz_text(hz: float) -> str:
    if hz >= 1000.0:
        return f"{hz / 1000.0:g} kHz"
    return f"{hz:g} Hz" if hz >= 10 else f"{hz:.3g} Hz"


def _blep(t: np.ndarray, dt) -> np.ndarray:
    """PolyBLEP: the correction that rounds off a jump in a wave so it does not alias."""
    dt = np.broadcast_to(np.asarray(dt, dtype=np.float64), t.shape)
    out = np.zeros_like(t)
    a = t < dt
    x = t[a] / dt[a]
    out[a] = x + x - x * x - 1.0
    b = t > 1.0 - dt
    x = (t[b] - 1.0) / dt[b]
    out[b] = x * x + x + x + 1.0
    return out


def wave_of(kind: str, phase: np.ndarray, dt) -> np.ndarray:
    """One wave for phases in cycles (0 to 1), dt the pitch in cycles per sample."""
    t = phase % 1.0
    if kind == "triangle":
        t = (t + 0.25) % 1.0                   # starts at 0 like the sine
    if kind == "square":
        return np.where(t < 0.5, 1.0, -1.0) + _blep(t, dt) - _blep((t + 0.5) % 1.0, dt)
    if kind == "saw":
        return 2.0 * t - 1.0 - _blep(t, dt)
    if kind == "triangle":
        # added up from its odd harmonics below half the sample rate (they fade as 1/k^2,
        # so 15 of them are as good as perfect)
        dt = np.broadcast_to(np.asarray(dt, dtype=np.float64), t.shape)
        out = np.zeros_like(t)
        for i, k in enumerate(range(1, 31, 2)):
            sign = 1.0 if i % 2 == 0 else -1.0
            part = sign * np.sin(2.0 * np.pi * k * t) / (k * k)
            out += np.where(k * dt < 0.5, part, 0.0)
        return out * (8.0 / np.pi ** 2)
    return np.sin(2.0 * np.pi * t)


# how loud each wave plays at the same setting: the same loudness (RMS) as the sine
_WAVE_GAIN = {"sine": 1.0, "square": 0.7071, "saw": 1.2247, "triangle": 1.2247}


class ToneGenerator:
    """Makes the samples of one tone description, block after block. finished turns True
    once a pattern, a number of beeps or a sweep has played to its end."""

    def __init__(self, spec: dict, sr: float):
        self.spec = clean(spec)
        self.sr = float(sr)
        self.pos = 0                    # samples played
        self.phase = 0.0                # in cycles
        self.finished = False
        s = self.spec
        # every wave peaks at 1: never past full scale, whatever the wave
        self.gain = min(1.0, 10.0 ** (s["db"] / 20.0) * _WAVE_GAIN[s["wave"]])
        self._gain_now = self.gain
        self.fade = max(1, int(FADE_S * self.sr))
        self.total = None               # samples in all, None while it plays until stopped
        self._segments = self._plan()

    def retune(self, spec: dict) -> None:
        """A new pitch, wave or level while a steady tone or beeps play, without starting
        again (the pitch glides on from where the wave is, the level over one block)."""
        new = clean(spec)
        if new["kind"] != self.spec["kind"] or new["kind"] not in ("steady", "beeps"):
            return
        spec = dict(self.spec, hz=new["hz"], wave=new["wave"], db=new["db"])
        self.gain = min(1.0, 10.0 ** (spec["db"] / 20.0) * _WAVE_GAIN[spec["wave"]])
        if spec["kind"] == "beeps":
            self._segments = [(start, length, spec["hz"]) for start, length, _hz in self._segments]
        self.spec = spec

    def _plan(self):
        """(start sample, length, Hz) of every sounding part of one round, and the length of
        a round. A steady tone or a sweep is one part."""
        s, sr = self.spec, self.sr
        if s["kind"] == "beeps":
            on = max(1, int(s["beep_ms"] * sr / 1000.0))
            off = int(s["gap_ms"] * sr / 1000.0)
            round_len = on + off
            parts = [(0, on, s["hz"])]
        elif s["kind"] == "pattern":
            parts, at = [], 0
            for hz, ms in s["steps"]:
                length = max(1, int(ms * sr / 1000.0))
                if hz > 0:
                    parts.append((at, length, hz))
                at += length
            round_len = max(1, at)
        elif s["kind"] == "sweep":
            length = max(1, int(s["sweep_s"] * sr))
            round_len = length * (2 if s["sweep_back"] else 1)
            parts = [(0, round_len, None)]
        else:
            round_len, parts = None, None
        if round_len is not None and s["repeat"]:
            self.total = round_len * s["repeat"]
        self.round_len = round_len
        return parts

    def _sweep_hz(self, pos: np.ndarray) -> np.ndarray:
        s = self.spec
        length = max(1, int(s["sweep_s"] * self.sr))
        x = (pos % self.round_len) / float(length)
        if s["sweep_back"]:
            x = np.where(x > 1.0, 2.0 - x, x)
        x = np.clip(x, 0.0, 1.0)
        a, b = s["sweep_from"], s["sweep_to"]
        if s["sweep_log"]:
            return a * (b / a) ** x
        return a + (b - a) * x

    def render(self, n: int) -> np.ndarray:
        if self.finished or n <= 0:
            return np.zeros(max(0, n))
        s = self.spec
        pos = self.pos + np.arange(n)
        if s["kind"] == "steady":
            hz = np.full(n, s["hz"])
            env = np.clip(pos / self.fade, 0.0, 1.0)
        elif s["kind"] == "sweep":
            hz = self._sweep_hz(pos)
            env = np.clip(pos / self.fade, 0.0, 1.0)
            if self.total is not None:
                env = np.minimum(env, np.clip((self.total - pos) / self.fade, 0.0, 1.0))
        else:
            local = pos % self.round_len
            hz = np.zeros(n)
            env = np.zeros(n)
            for start, length, part_hz in self._segments:
                inside = (local >= start) & (local < start + length)
                if not inside.any():
                    continue
                hz[inside] = part_hz
                into = local[inside] - start
                env[inside] = np.clip(np.minimum(into, length - into) / self.fade, 0.0, 1.0)
            if self.total is not None:
                env = np.where(pos < self.total, env, 0.0)
        dt = hz / self.sr
        phase = self.phase + np.cumsum(dt) - dt         # the phase at each sample
        self.phase = float((phase[-1] + dt[-1]) % 1.0)
        # the phase stands still during a rest; the fades keep every start and end smooth
        gain = self.gain
        if gain != self._gain_now:
            level = np.linspace(self._gain_now, gain, n)
            self._gain_now = gain
        else:
            level = gain
        sound = wave_of(s["wave"], phase, np.maximum(dt, 1e-9)) * env * level
        self.pos += n
        if self.total is not None and self.pos >= self.total:
            self.finished = True
        return sound
