"""Per speaker signal processing: EQ, frequency limits, delay, gain."""
from __future__ import annotations

import math

import numpy as np
from scipy import signal

from .model import Speaker, EQBand

MAX_DELAY_MS = 500.0
F_MIN, F_MAX = 5.0, 22000.0


def db_to_lin(db: float) -> float:
    return 10.0 ** (db / 20.0)


def _clamp_freq(freq: float, sr: float) -> float:
    return float(min(max(freq, F_MIN), sr * 0.45))


def biquad(kind: str, freq: float, gain_db: float, q: float, sr: float) -> np.ndarray:
    """One second order section (RBJ audio EQ cookbook)."""
    freq = _clamp_freq(freq, sr)
    q = max(0.1, float(q))
    a = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * freq / sr
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / (2.0 * q)
    if kind == "lowshelf":
        k = 2.0 * math.sqrt(a) * alpha
        b0 = a * ((a + 1) - (a - 1) * cw + k)
        b1 = 2 * a * ((a - 1) - (a + 1) * cw)
        b2 = a * ((a + 1) - (a - 1) * cw - k)
        a0 = (a + 1) + (a - 1) * cw + k
        a1 = -2 * ((a - 1) + (a + 1) * cw)
        a2 = (a + 1) + (a - 1) * cw - k
    elif kind == "highshelf":
        k = 2.0 * math.sqrt(a) * alpha
        b0 = a * ((a + 1) + (a - 1) * cw + k)
        b1 = -2 * a * ((a - 1) + (a + 1) * cw)
        b2 = a * ((a + 1) + (a - 1) * cw - k)
        a0 = (a + 1) - (a - 1) * cw + k
        a1 = 2 * ((a - 1) - (a + 1) * cw)
        a2 = (a + 1) - (a - 1) * cw - k
    else:  # peak
        b0 = 1 + alpha * a
        b1 = -2 * cw
        b2 = 1 - alpha * a
        a0 = 1 + alpha / a
        a1 = -2 * cw
        a2 = 1 - alpha / a
    return np.array([b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0])


def _order(slope_db: int) -> int:
    return {12: 2, 24: 4, 48: 8}.get(int(slope_db), 4)


def design_sos(spk: Speaker, sr: float, keep_lows: bool = False) -> np.ndarray:
    """All filters of one speaker as a stack of second order sections. keep_lows leaves
    out its "Nothing below" cut (no subwoofer to take those notes)."""
    sections = []
    if spk.hp_on and not keep_lows:
        sections.append(signal.butter(_order(spk.hp_slope), _clamp_freq(spk.hp_freq, sr),
                                      btype="highpass", fs=sr, output="sos"))
    if spk.lp_on:
        sections.append(signal.butter(_order(spk.lp_slope), _clamp_freq(spk.lp_freq, sr),
                                      btype="lowpass", fs=sr, output="sos"))
    if spk.eq_on:
        for band in spk.eq:
            if band.enabled and abs(band.gain_db) > 0.01:
                sections.append(biquad(band.kind, band.freq, band.gain_db, band.q, sr)[None, :])
    if not sections:
        return np.zeros((0, 6))
    return np.vstack(sections)


def response_db(spk: Speaker, sr: float, freqs: np.ndarray) -> np.ndarray:
    """Magnitude response in dB at the given frequencies (for the EQ graph)."""
    sos = design_sos(spk, sr)
    if len(sos) == 0:
        return np.zeros_like(freqs, dtype=float)
    _, h = signal.sosfreqz(sos, worN=freqs, fs=sr)
    return 20.0 * np.log10(np.maximum(np.abs(h), 1e-6))


class SpeakerChain:
    """Real time processor for one speaker. Settings are swapped in between
    blocks, so the user interface can change them while audio is running."""

    def __init__(self, sr: float):
        self.sr = float(sr)
        self._pending = None
        self._sos = np.zeros((0, 6))
        self._zi = np.zeros((0, 2))
        self._gain = 0.0            # starts silent and fades in
        self._target_gain = 1.0
        self._delay = 0
        self._hist = np.zeros(0)
        self.peak = 0.0             # for the level meters
        self.clipped = False

    def configure(self, spk: Speaker, extra_delay_ms: float = 0.0, extra_gain_db: float = 0.0,
                  keep_lows: bool = False) -> None:
        """Called from the user interface thread."""
        gain = db_to_lin(spk.gain_db + extra_gain_db)
        if spk.invert:
            gain = -gain
        delay_ms = min(max(spk.delay_ms + extra_delay_ms, 0.0), MAX_DELAY_MS)
        self._pending = (design_sos(spk, self.sr, keep_lows), gain,
                         int(round(delay_ms * self.sr / 1000.0)))

    def _apply_pending(self) -> None:
        pending, self._pending = self._pending, None
        if pending is None:
            return
        sos, gain, delay = pending
        if len(sos) != len(self._sos):
            self._zi = np.zeros((len(sos), 2))
        self._sos = sos
        self._target_gain = gain
        if delay != self._delay:
            if delay > len(self._hist):
                self._hist = np.concatenate([np.zeros(delay - len(self._hist)), self._hist])
            else:
                self._hist = self._hist[len(self._hist) - delay:]
            self._delay = delay

    def process(self, x: np.ndarray) -> np.ndarray:
        """x is one block of mono float64 samples."""
        self._apply_pending()
        n = len(x)
        y = x
        if len(self._sos):
            y, self._zi = signal.sosfilt(self._sos, y, zi=self._zi)
            if not np.all(np.isfinite(self._zi)):
                self._zi = np.zeros_like(self._zi)
                y = np.zeros(n)
        if self._delay:
            joined = np.concatenate([self._hist, y])
            y, self._hist = joined[:n], joined[n:]
        if self._gain != self._target_gain:
            y = y * np.linspace(self._gain, self._target_gain, n, endpoint=True)
            self._gain = self._target_gain
        else:
            y = y * self._gain
        peak = float(np.max(np.abs(y))) if n else 0.0
        self.peak = max(peak, self.peak * 0.9)
        if peak > 1.0:
            self.clipped = True
        return y


class PinkNoise:
    """Pink noise for the Identify button and the built in test signal."""

    def __init__(self, seed: int = 1):
        self._rng = np.random.default_rng(seed)
        # Paul Kellet's economy filter as a transfer function
        self._b = np.array([0.049922035, -0.095993537, 0.050612699, -0.004408786])
        self._a = np.array([1.0, -2.494956002, 2.017265875, -0.522189400])
        self._zi = np.zeros(3)

    def block(self, n: int) -> np.ndarray:
        white = self._rng.standard_normal(n)
        y, self._zi = signal.lfilter(self._b, self._a, white, zi=self._zi)
        return y * 2.5
