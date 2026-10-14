"""Frequency range presets for different kinds of speaker.

The numbers are sensible starting points for each kind of speaker, based on how
low drivers of that size can play cleanly. They are meant to be fine tuned by ear.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .model import SUB_HP_HZ, SUB_LP_HZ, Speaker


@dataclass(frozen=True)
class RangePreset:
    key: str
    name: str
    hint: str
    low_cut: Optional[float] = None         # nothing below this, None = no limit
    high_cut: Optional[float] = None        # nothing above this, None = no limit
    low_slope: int = 24
    high_slope: int = 24


RANGE_PRESETS = [
    RangePreset("full", "Full range",
                "No limits. For big speakers, headphones, and systems that manage their own bass."),
    RangePreset("sub", "Subwoofer",
                f"Only the lowest notes, {SUB_HP_HZ:g} to {SUB_LP_HZ:g} Hz.", SUB_HP_HZ, SUB_LP_HZ),
    RangePreset("sub_small", "Subwoofer under small speakers",
                "10 to 120 Hz, so it fills in for small speakers that stop around 120 Hz.", 10.0, 120.0),
    RangePreset("shaker", "Bass shaker (tactile transducer)",
                "ButtKicker style shakers on a seat or rig: 10 to 80 Hz, felt more than heard.",
                10.0, 80.0, 24, 48),
    RangePreset("sat80", "Speaker paired with a subwoofer",
                "Hands everything below 80 Hz to the subwoofer, the usual home cinema crossover.", 80.0),
    RangePreset("floor", "Floor standing speaker",
                "Large speakers that reach deep: a gentle cut below 30 Hz.", 30.0, None, 12),
    RangePreset("monitor_8", "8 inch monitor or bookshelf", "Nothing below 35 Hz.", 35.0),
    RangePreset("monitor_6", "6 to 6.5 inch monitor or bookshelf", "Nothing below 45 Hz.", 45.0),
    RangePreset("monitor_5", "4.5 to 5 inch monitor or bookshelf", "Nothing below 55 Hz.", 55.0),
    RangePreset("small_3", "3 to 4 inch speaker", "Nothing below 80 Hz.", 80.0),
    RangePreset("soundbar", "Soundbar without a subwoofer", "Nothing below 80 Hz.", 80.0),
    RangePreset("tv", "TV speakers",
                "Speakers built into a TV rarely go below about 100 Hz.", 100.0),
    RangePreset("desktop", "Small desktop speaker (2 to 3 inch)", "Nothing below 120 Hz.", 120.0),
    RangePreset("portable", "Small portable or Bluetooth speaker", "Nothing below 100 Hz.", 100.0),
    RangePreset("tiny", "Tiny built in speaker (monitor, laptop)",
                "Very small drivers sound cleaner without deep bass: 200 Hz and up.", 200.0),
    RangePreset("midrange", "Midrange driver only",
                "200 Hz to 3 kHz, for the middle driver of a speaker you built yourself.", 200.0, 3000.0),
    RangePreset("tweeter", "Tweeter (treble only)",
                "High notes only, 3 kHz and up. Protects a tweeter from bass.", 3000.0, None, 24),
]

BY_KEY = {p.key: p for p in RANGE_PRESETS}


def apply_range_preset(spk: Speaker, key: str) -> None:
    preset = BY_KEY[key]
    spk.hp_on = preset.low_cut is not None
    if preset.low_cut is not None:
        spk.hp_freq, spk.hp_slope = float(preset.low_cut), preset.low_slope
    spk.lp_on = preset.high_cut is not None
    if preset.high_cut is not None:
        spk.lp_freq, spk.lp_slope = float(preset.high_cut), preset.high_slope
    spk.range_preset = key


def matching_preset(spk: Speaker) -> str:
    """The preset the speaker's limits currently match, or "" if they were changed by hand."""
    for preset in RANGE_PRESETS:
        low_ok = (preset.low_cut is None and not spk.hp_on) or (
            preset.low_cut is not None and spk.hp_on and abs(spk.hp_freq - preset.low_cut) < 0.05
            and spk.hp_slope == preset.low_slope)
        high_ok = (preset.high_cut is None and not spk.lp_on) or (
            preset.high_cut is not None and spk.lp_on and abs(spk.lp_freq - preset.high_cut) < 0.05
            and spk.lp_slope == preset.high_slope)
        if low_ok and high_ok:
            if spk.range_preset and spk.range_preset != preset.key and \
                    spk.range_preset in BY_KEY and _same_limits(BY_KEY[spk.range_preset], preset):
                return spk.range_preset         # two presets share numbers: keep the chosen name
            return preset.key
    return ""


def _same_limits(a: RangePreset, b: RangePreset) -> bool:
    return (a.low_cut, a.high_cut, a.low_slope, a.high_slope) == (b.low_cut, b.high_cut, b.low_slope, b.high_slope)
