"""Sound effects for fun: bass boost, chipmunk or deep voice, robot, distortion and more.

They change the PC sound before it is spread over the speakers, so every speaker plays the
changed sound, in step. Spin round the room is different: it turns the finished surround
mix itself, so it lives in the engine (Engine._spin).

Everything here runs in the audio thread, a block at a time, with numpy. Each effect fades
in and out over a moment, so switching one on or off never clicks. While any effect plays,
a limiter at the end keeps a bass boost or distortion from overloading the speakers.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import signal

from .dsp import biquad


@dataclass(frozen=True)
class Effect:
    key: str
    name: str
    blurb: str
    amount_name: str        # what the slider changes
    lo: float
    hi: float
    default: float
    step: float
    unit: str = ""
    seconds: float = 10.0   # how long "Play for" runs, to start with

    def text(self, amount: float) -> str:
        """The slider's value as it is shown: "+7 semitones", "0.35 s", "6 bits"."""
        if self.key == "pitch":
            return f"{amount:+.0f} semitones" if amount else "0 semitones"
        number = f"{amount:.2f}".rstrip("0").rstrip(".") if self.step < 1 else f"{amount:.0f}"
        if self.unit == "%":
            return f"{number}%"
        return f"{number} {self.unit}".strip()


EFFECTS = (
    Effect("bass", "Bass boost", "Lifts the low notes, like a club or a car with a big subwoofer.",
           "Boost", 3, 18, 10, 1, "dB"),
    Effect("pitch", "Chipmunk or deep voice", "Moves every note higher or lower without changing the "
           "speed. Up for chipmunks, down for a monster.", "Shift", -12, 12, 7, 1),
    Effect("robot", "Robot", "Turns every voice into a robot's.", "Buzz", 20, 120, 45, 1, "Hz"),
    Effect("distort", "Distortion", "Like a speaker turned up far too loud.", "Drive", 1, 10, 5, 1),
    Effect("phone", "Telephone", "Thin and tinny, like a phone call or an old radio. Turn up the "
           "crackle for a bad line.", "Crackle", 0, 10, 3, 1),
    Effect("underwater", "Underwater", "Muffled and wobbly, as if heard from the bottom of a pool.",
           "Depth", 1, 10, 6, 1),
    Effect("echo", "Echo", "Every sound comes back again and again, a little quieter each time.",
           "Delay", 0.1, 1.0, 0.35, 0.05, "s"),
    Effect("hall", "Stadium", "A huge hall that rings on after every sound.", "Size", 1, 10, 7, 1),
    Effect("crush", "8 bit", "Crunchy and gritty, like an old games console.", "Bits", 3, 10, 5, 1, "bits"),
    Effect("karaoke", "Karaoke", "Takes the singer out of most songs (the voice that sits in the middle). "
           "Works on stereo music.", "Strength", 50, 100, 100, 5, "%"),
    Effect("spin", "Spin round the room", "The whole sound circles round you through every speaker. "
           "Best with speakers all round.", "One turn every", 1, 20, 4, 0.5, "s"),
)
BY_KEY = {e.key: e for e in EFFECTS}
ORDER = ("karaoke", "pitch", "robot", "phone", "underwater", "crush", "distort", "bass", "echo", "hall")
TAILS = {"echo": 0.6, "hall": 1.2}     # these fade out slower, so their echoes die away
FADE_S = 0.05
LIMIT = 0.89                           # about 1 dB under full scale
RELEASE_S = 0.4


def clean_amount(key: str, value) -> float:
    effect = BY_KEY[key]
    try:
        value = float(value)
    except (TypeError, ValueError):
        return float(effect.default)
    if not math.isfinite(value):
        return float(effect.default)
    return float(min(max(value, effect.lo), effect.hi))


SECONDS_MIN, SECONDS_MAX = 1, 600      # "Play for" between a second and ten minutes


def clean_seconds(key: str, value) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return float(BY_KEY[key].seconds)
    if not math.isfinite(value):
        return float(BY_KEY[key].seconds)
    return float(min(max(round(value), SECONDS_MIN), SECONDS_MAX))


def clean_settings(saved) -> dict:
    """The effects' saved amounts and times, with anything unknown or broken left out."""
    out = {}
    if not isinstance(saved, dict):
        return out
    for key, entry in saved.items():
        if key not in BY_KEY or not isinstance(entry, dict):
            continue
        out[key] = {"amount": clean_amount(key, entry.get("amount", BY_KEY[key].default)),
                    "seconds": clean_seconds(key, entry.get("seconds", BY_KEY[key].seconds))}
    return out


# ---------------------------------------------------------------- the effects

class _Filter:
    """A stack of second order sections run over every channel, its state kept between blocks."""

    def __init__(self, channels: int):
        self.channels = channels
        self.sos = None
        self.zi = None

    def set(self, sos: np.ndarray) -> None:
        if self.sos is None or len(sos) != len(self.sos):
            self.zi = np.zeros((len(sos), 2, self.channels))
        self.sos = sos

    def run(self, x: np.ndarray) -> np.ndarray:
        y, self.zi = signal.sosfilt(self.sos, x, axis=0, zi=self.zi)
        if not np.all(np.isfinite(self.zi)):
            self.zi = np.zeros_like(self.zi)
            return np.zeros_like(x)
        return y


class _Line:
    """A delay line that can be read between samples: the past of every channel, with the
    block being processed at its end."""

    def __init__(self, channels: int, longest: int):
        self.keep = int(longest) + 4
        self.hist = np.zeros((self.keep, channels))

    def read(self, x: np.ndarray, delays: np.ndarray) -> np.ndarray:
        """x: this block (n, channels). delays: (n,) samples back from each sample, >= 1."""
        n = len(x)
        full = np.vstack([self.hist, x])
        pos = self.keep + np.arange(n) - np.clip(delays, 1.0, self.keep - 2)
        i0 = np.floor(pos).astype(int)
        frac = (pos - i0)[:, None]
        out = full[i0] * (1.0 - frac) + full[i0 + 1] * frac
        self.hist = full[-self.keep:]
        return out


class Bass:
    def __init__(self, sr, ch):
        self.sr, self.f, self.gain = sr, _Filter(ch), None

    def process(self, x, amount, _roles):
        if amount != self.gain:
            self.gain = amount
            self.f.set(biquad("lowshelf", 90.0, amount, 0.8, self.sr)[None, :])
        return self.f.run(x)


class Pitch:
    """Two reading points slide through a short delay line, faster or slower than the sound
    arrives, and take turns, so the notes move without the speed changing."""
    WINDOW_S = 0.06

    def __init__(self, sr, ch):
        self.w = max(64, int(self.WINDOW_S * sr))
        self.line = _Line(ch, self.w + 2)
        self.phase = 0.0

    def process(self, x, amount, _roles):
        n = len(x)
        ratio = 2.0 ** (amount / 12.0)
        step = (1.0 - ratio) / self.w
        phase = (self.phase + step * np.arange(n)) % 1.0
        self.phase = float((self.phase + step * n) % 1.0)
        other = (phase + 0.5) % 1.0
        hist_before = self.line.hist.copy()
        a = self.line.read(x, 1.0 + phase * (self.w - 2))
        self.line.hist = hist_before
        b = self.line.read(x, 1.0 + other * (self.w - 2))
        ga = np.sin(np.pi * phase)[:, None] ** 2
        return a * ga + b * (1.0 - ga)              # the two always add up to one


class Robot:
    def __init__(self, sr, ch):
        self.sr, self.phase = sr, 0.0

    def process(self, x, amount, _roles):
        n = len(x)
        step = 2.0 * np.pi * amount / self.sr
        carrier = np.sin(self.phase + step * np.arange(n))
        self.phase = float((self.phase + step * n) % (2.0 * np.pi))
        return x * carrier[:, None] * 1.6


class Distort:
    def __init__(self, sr, ch):
        pass

    def process(self, x, amount, _roles):
        drive = 1.0 + amount * 3.0
        return np.tanh(x * drive) * 0.35


class Phone:
    def __init__(self, sr, ch):
        self.sr = sr
        self.f = _Filter(ch)
        self.f.set(signal.butter(4, (320.0, 3300.0), btype="bandpass", fs=sr, output="sos"))
        self.rng = np.random.default_rng(5)

    def process(self, x, amount, _roles):
        y = np.tanh(self.f.run(x) * 2.5) * 0.7
        if amount > 0:
            n = len(x)
            pops = self.rng.random((n, 1)) < amount * 4e-4
            y = y + pops * self.rng.uniform(-0.25, 0.25, (n, 1)) + \
                self.rng.normal(0.0, 0.0015 * amount, (n, 1))
        return y


class Underwater:
    def __init__(self, sr, ch):
        self.sr = sr
        self.f = _Filter(ch)
        self.depth = None
        self.line = _Line(ch, int(0.012 * sr))
        self.phase = 0.0

    def process(self, x, amount, _roles):
        if amount != self.depth:
            self.depth = amount
            cut = 1300.0 - amount * 100.0
            self.f.set(signal.butter(4, cut, btype="lowpass", fs=self.sr, output="sos"))
        n = len(x)
        swing = (0.0015 + amount * 0.0004) * self.sr       # how far the wobble pulls, in samples
        step = 2.0 * np.pi * 1.3 / self.sr
        wobble = np.sin(self.phase + step * np.arange(n))
        self.phase = float((self.phase + step * n) % (2.0 * np.pi))
        return self.line.read(self.f.run(x), 2.0 + swing * (1.0 + wobble)) * 1.3


class Echo:
    FEEDBACK, LEVEL = 0.45, 0.55

    def __init__(self, sr, ch):
        self.sr, self.ch = sr, ch
        self.buf = np.zeros((0, ch))

    def process(self, x, amount, _roles):
        d = max(1, int(amount * self.sr))
        if len(self.buf) != d:                       # the delay was changed: keep what fits
            if len(self.buf) > d:
                self.buf = self.buf[-d:]
            else:
                self.buf = np.vstack([np.zeros((d - len(self.buf), self.ch)), self.buf])
        out = np.empty_like(x)
        k = 0
        while k < len(x):                             # pieces no longer than the delay
            m = min(d, len(x) - k)
            back = self.buf[:m]
            chunk = x[k:k + m]
            out[k:k + m] = chunk + back * self.LEVEL
            self.buf = np.vstack([self.buf[m:], chunk + back * self.FEEDBACK])
            k += m
        return out


class Hall:
    """A small Freeverb: four damped feedback delays side by side, then two all pass delays.
    It runs on two sends (the odd and the even channels), whatever the number of channels,
    with slightly different lengths each, so the hall sounds wide and stays cheap."""
    COMBS = (1116, 1277, 1422, 1617)
    PASSES = (556, 341)
    DAMP = 0.3
    SENDS = 2

    def __init__(self, sr, ch):
        self.sr, self.ch = sr, ch
        self.sends = min(ch, self.SENDS)
        k = sr / 44100.0
        spread = [23 * c for c in range(self.sends)]
        self.comb_len = [[int(c * k) + d for d in spread] for c in self.COMBS]
        self.pass_len = [[int(a * k) + d // 2 for d in spread] for a in self.PASSES]
        self.comb_buf = [[np.zeros(n) for n in lens] for lens in self.comb_len]
        self.comb_low = np.zeros((len(self.COMBS), self.sends))
        self.pass_buf = [[np.zeros(n) for n in lens] for lens in self.pass_len]
        self.shortest = min(min(min(c) for c in self.comb_len), min(min(a) for a in self.pass_len))
        # which send each channel feeds and hears back: odd and even channels take turns
        self.route = np.arange(ch) % self.sends

    def _send(self, c, x, feedback):
        wet = np.zeros(len(x))
        for i in range(len(self.COMBS)):
            buf = self.comb_buf[i][c]
            out = buf[:len(x)].copy()
            # the damping: a gentle low pass on what goes round again
            low, _zf = signal.lfilter([1.0 - self.DAMP], [1.0, -self.DAMP], out,
                                      zi=[self.comb_low[i, c] * self.DAMP])
            self.comb_low[i, c] = low[-1]
            self.comb_buf[i][c] = np.concatenate([buf[len(x):], x * 0.03 + low * feedback])
            wet += out
        for i in range(len(self.PASSES)):
            buf = self.pass_buf[i][c]
            back = buf[:len(wet)].copy()
            self.pass_buf[i][c] = np.concatenate([buf[len(wet):], wet + back * 0.5])
            wet = back - wet
        return wet

    def process(self, x, amount, _roles):
        feedback = 0.70 + 0.027 * amount            # bigger: rings on longer
        out = np.empty_like(x)
        k = 0
        while k < len(x):
            m = min(self.shortest, len(x) - k)
            chunk = x[k:k + m]
            wet = np.empty((m, self.sends))
            for c in range(self.sends):
                send = chunk[:, self.route == c].mean(axis=1)
                wet[:, c] = self._send(c, send, feedback)
            out[k:k + m] = chunk * 0.8 + wet[:, self.route] * 2.2
            k += m
        return out


class Crush:
    HOLD_HZ = 9000.0

    def __init__(self, sr, ch):
        self.hold = max(1, int(round(sr / self.HOLD_HZ)))
        self.count = 0
        self.held = np.zeros(ch)

    def process(self, x, amount, _roles):
        n = len(x)
        steps = 2.0 ** (amount - 1)
        idx = np.arange(n)
        fresh = (idx + self.count) % self.hold == 0
        latest = np.maximum.accumulate(np.where(fresh, idx, -1))
        y = np.where((latest >= 0)[:, None], x[np.maximum(latest, 0)], self.held[None, :])
        y = np.round(y * steps) / steps
        self.held = y[-1].copy() if n else self.held
        self.count = (self.count + n) % self.hold
        return y


class Karaoke:
    """The singer is usually the same in left and right. Left minus right cancels them; the
    low notes, which are also the same in both, are put back so the bass stays."""

    def __init__(self, sr, ch):
        self.low = _Filter(1)
        self.low.set(signal.butter(2, 140.0, btype="lowpass", fs=sr, output="sos"))

    def process(self, x, amount, roles):
        if "FL" not in roles or "FR" not in roles:
            return x
        left, right = roles.index("FL"), roles.index("FR")
        if left >= x.shape[1] or right >= x.shape[1]:
            return x
        y = x.copy()
        mid = (x[:, left] + x[:, right]) * 0.5
        side = (x[:, left] - x[:, right]) * 0.5
        bass = self.low.run(mid[:, None])[:, 0]
        y[:, left] = side + bass
        y[:, right] = -side + bass
        if "FC" in roles and roles.index("FC") < x.shape[1]:
            y[:, roles.index("FC")] = 0.0              # a film's or a 5.1 song's voices
        k = amount / 100.0
        return x * (1.0 - k) + y * k


MAKERS = {"bass": Bass, "pitch": Pitch, "robot": Robot, "distort": Distort, "phone": Phone,
          "underwater": Underwater, "echo": Echo, "hall": Hall, "crush": Crush, "karaoke": Karaoke}


class FunChain:
    """All the effects in a fixed order. active: {effect key: amount}, replaced as a whole by
    the user interface and read once per block here."""

    def __init__(self):
        self.sr = 0.0
        self.channels = 0
        self.procs: dict = {}
        self.mix: dict = {}          # how far each effect is faded in, 0 to 1
        self.amounts: dict = {}      # the last amount, kept while an effect fades out
        self.gain = 1.0              # the limiter

    @property
    def busy(self) -> bool:
        return bool(self.mix)

    def process(self, x: np.ndarray, active: dict, sr: float, roles) -> np.ndarray:
        n, ch = x.shape
        if sr != self.sr or ch != self.channels:
            self.sr, self.channels = sr, ch
            self.procs, self.mix = {}, {}
            self.gain = 1.0
        if not n:
            return x
        y = x
        for key in ORDER:
            target = 1.0 if key in active else 0.0
            now = self.mix.get(key, 0.0)
            if target == 0.0 and now == 0.0:
                continue
            if key in active:
                self.amounts[key] = clean_amount(key, active[key])
            proc = self.procs.get(key)
            if proc is None:
                proc = self.procs[key] = MAKERS[key](sr, ch)
            wet = proc.process(y, self.amounts.get(key, BY_KEY[key].default), roles)
            fade = TAILS.get(key, FADE_S) if target == 0.0 else FADE_S
            step = n / max(1.0, fade * sr)
            end = min(1.0, now + step) if target else max(0.0, now - step)
            if now == 1.0 and end == 1.0:
                y = wet
            else:
                ramp = np.linspace(now, end, n)[:, None]
                y = y + (wet - y) * ramp
            if end == 0.0:
                self.mix.pop(key, None)
                self.procs.pop(key, None)         # starts fresh next time: no old echoes
            else:
                self.mix[key] = end
        if not self.mix and self.gain >= 0.999:
            self.gain = 1.0
            return y
        return self._limit(y)             # also while it comes back up after the last effect

    def _limit(self, y: np.ndarray) -> np.ndarray:
        """Turns the sound down at once when it would overload, and back up slowly."""
        n = len(y)
        peak = float(np.max(np.abs(y)))
        want = min(1.0, LIMIT / peak) if peak > 0 else 1.0
        if not math.isfinite(want):
            want = 1.0
        if want < self.gain:
            new = want
        else:
            new = min(want, self.gain + n / (RELEASE_S * self.sr))
        gains = np.linspace(self.gain, new, n)[:, None]
        self.gain = new
        out = y * gains
        return np.clip(out, -LIMIT, LIMIT) if want < 1.0 else out
