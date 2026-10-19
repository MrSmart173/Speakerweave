"""Sound effects for fun: each one is measured to do what its card says, never overloads,
and fades in and out without a click."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from speakerweave import fun
from speakerweave.engine import Engine
from speakerweave.model import Project

SR = 48000.0
N = 480
STEREO = ["FL", "FR"]


def tone(freq, seconds, level=0.3, channels=2):
    t = np.arange(int(seconds * SR)) / SR
    return np.repeat((np.sin(2 * np.pi * freq * t) * level)[:, None], channels, axis=1)


def run(chain, x, active, roles=STEREO):
    out = [chain.process(x[k:k + N], active, SR, roles) for k in range(0, len(x) - N + 1, N)]
    return np.vstack(out)


def strongest(y, lo=20.0, hi=8000.0):
    """The loudest frequency of a mono signal."""
    spec = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    freqs = np.fft.rfftfreq(len(y), 1 / SR)
    keep = (freqs >= lo) & (freqs <= hi)
    return float(freqs[keep][np.argmax(spec[keep])])


def level_at(y, freq):
    spec = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    freqs = np.fft.rfftfreq(len(y), 1 / SR)
    band = (freqs > freq * 0.9) & (freqs < freq * 1.1)
    return float(np.max(spec[band]))


@pytest.mark.parametrize("effect", [e for e in fun.EFFECTS if e.key != "spin"], ids=lambda e: e.key)
@pytest.mark.parametrize("channels", [2, 8])
def test_every_effect_stays_safe_with_loud_noise(effect, channels):
    rng = np.random.default_rng(1)
    x = rng.uniform(-1, 1, (int(SR * 1.5), channels))           # as loud as it gets
    roles = STEREO if channels == 2 else ["FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"]
    for amount in (effect.lo, effect.default, effect.hi):
        chain = fun.FunChain()
        y = run(chain, x, {effect.key: amount}, roles)
        assert np.all(np.isfinite(y))
        assert float(np.max(np.abs(y))) <= 1.0                    # never overloads
        assert float(np.sqrt(np.mean(y[N * 20:] ** 2))) > 0.01   # and is not silent


def test_pitch_moves_the_notes_and_keeps_the_speed():
    x = tone(440.0, 1.5)
    for semitones, want in ((12, 880.0), (7, 440.0 * 2 ** (7 / 12)), (-12, 220.0)):
        y = run(fun.FunChain(), x, {"pitch": semitones})
        assert len(y) == len(x) - len(x) % N                       # the same length: the same speed
        assert abs(strongest(y[int(0.3 * SR):, 0]) - want) < want * 0.02


def test_bass_boost_lifts_the_lows_only():
    x = tone(60.0, 1.0, 0.02) + tone(3000.0, 1.0, 0.02)
    y = run(fun.FunChain(), x, {"bass": 12})[int(0.3 * SR):, 0]
    dry = x[int(0.3 * SR):len(y) + int(0.3 * SR), 0]
    lows = 20 * np.log10(level_at(y, 60.0) / level_at(dry, 60.0))
    highs = 20 * np.log10(level_at(y, 3000.0) / level_at(dry, 3000.0))
    assert 9.0 < lows < 13.0 and abs(highs) < 1.0


def test_robot_buzzes_and_telephone_cuts_lows_and_highs():
    y = run(fun.FunChain(), tone(440.0, 1.0), {"robot": 45})[int(0.2 * SR):, 0]
    assert abs(strongest(y) - 395.0) < 6 or abs(strongest(y) - 485.0) < 6   # the voice split in two
    x = tone(100.0, 1.0, 0.1) + tone(1000.0, 1.0, 0.1) + tone(7000.0, 1.0, 0.1)
    y = run(fun.FunChain(), x, {"phone": 0})[int(0.2 * SR):, 0]
    assert level_at(y, 1000.0) > 20 * level_at(y, 100.0)
    assert level_at(y, 1000.0) > 20 * level_at(y, 7000.0)


def test_underwater_is_muffled():
    x = tone(200.0, 1.0, 0.1) + tone(4000.0, 1.0, 0.1)
    y = run(fun.FunChain(), x, {"underwater": 6})[int(0.2 * SR):, 0]
    assert level_at(y, 200.0) > 30 * level_at(y, 4000.0)


def test_echo_comes_back_after_the_delay_and_dies_away():
    x = np.zeros((int(SR * 2), 2))
    x[N * 4] = 0.5                                                  # one click
    chain = fun.FunChain()
    chain.mix["echo"] = 1.0                                         # already fully on
    y = run(chain, x, {"echo": 0.3})[:, 0]
    d = int(0.3 * SR)
    first, second = abs(y[N * 4 + d]), abs(y[N * 4 + 2 * d])
    assert first > 0.2 and 0.05 < second < first                   # again, a little quieter


def test_stadium_rings_on():
    x = np.zeros((int(SR * 2), 2))
    x[N * 4:N * 4 + 200] = np.random.default_rng(2).uniform(-0.5, 0.5, (200, 2))
    tails = {}
    for size in (1, 8):
        chain = fun.FunChain()
        chain.mix["hall"] = 1.0
        y = run(chain, x, {"hall": size})
        tail = y[N * 4 + int(0.5 * SR):N * 4 + int(0.6 * SR)]
        tails[size] = float(np.sqrt(np.mean(tail ** 2)))
    assert tails[8] > 0.001                                         # still ringing half a second on
    assert tails[8] > 10 * tails[1]                                 # a bigger hall rings longer
    assert not np.allclose(tail[:, 0], tail[:, 1])                  # wide: left and right differ


def test_8_bit_has_few_steps():
    y = run(fun.FunChain(), tone(300.0, 0.5, 0.9), {"crush": 4})[int(0.2 * SR):, 0]
    assert len(np.unique(np.round(y, 6))) <= 2 ** 4 + 1


def test_karaoke_takes_out_the_middle_and_keeps_the_sides_and_bass():
    voice = tone(800.0, 1.0, 0.2)                                   # the same in left and right
    guitar = tone(1500.0, 1.0, 0.2)
    guitar[:, 1] = 0.0                                              # only on the left
    bass = tone(60.0, 1.0, 0.2)
    y = run(fun.FunChain(), voice + guitar + bass, {"karaoke": 100})[int(0.3 * SR):, 0]
    dry = (voice + guitar + bass)[int(0.3 * SR):len(y) + int(0.3 * SR), 0]
    assert level_at(y, 800.0) < level_at(dry, 800.0) * 0.05         # the singer is gone
    assert level_at(y, 1500.0) > level_at(dry, 1500.0) * 0.4        # the guitar stays
    assert level_at(y, 60.0) > level_at(dry, 60.0) * 0.6            # and the bass


def test_switching_an_effect_on_and_off_fades_without_a_click():
    x = tone(220.0, 2.0, 0.5)
    chain = fun.FunChain()
    out = []
    for k in range(0, len(x) - N + 1, N):
        active = {"robot": 45} if SR * 0.5 <= k < SR * 1.2 else {}
        out.append(chain.process(x[k:k + N], active, SR, STEREO))
    y = np.vstack(out)[:, 0]
    jumps = np.max(np.abs(np.diff(y)))
    assert jumps < 2 * np.max(np.abs(np.diff(x[:, 0]))) * 1.6 * 1.2  # no step bigger than the sound's own
    assert not chain.busy                                           # all faded out again
    assert np.allclose(y[-N:], x[len(y) - N:len(y), 0])             # and the sound is as it was


def test_all_effects_at_once_are_quick_enough_for_8_channels():
    rng = np.random.default_rng(3)
    x = rng.uniform(-0.5, 0.5, (N * 60, 8))
    chain = fun.FunChain()
    roles = ["FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"]
    active = {e.key: e.default for e in fun.EFFECTS}
    run(chain, x[:N * 10], active, roles)                           # warmed up
    t0 = time.perf_counter()
    run(chain, x, active, roles)
    per_block = (time.perf_counter() - t0) / 60
    assert per_block < 0.008                                        # a block lasts 10 ms


def five_one():
    p = Project(input_kind="loopback", master_db=0.0, bass_redirect=False, upmix=False)
    p.set_mode("5.1", rear=False)
    dev = p.add_device("Speakers (Realtek)", 8)
    for spk in dev.speakers:
        spk.hp_on = spk.lp_on = False
    eng = Engine(p)
    eng.configure(SR, 8)
    return p, eng, dev


def test_spin_carries_the_sound_round_every_speaker_and_back():
    p, eng, dev = five_one()
    by_role = {s.role: s for s in dev.speakers}
    x = np.zeros((N, 8))
    x[:, 0] = 0.3 * np.sin(2 * np.pi * 300 * np.arange(N) / SR)     # front left only
    eng.set_fun({"spin": 2.0})                                      # one turn every 2 s
    seen = []
    for _ in range(int(2.0 * SR / N)):
        out = eng.process(x)[dev.id]
        loud = {r: float(np.max(np.abs(out[:, s.channel]))) for r, s in by_role.items() if r != "LFE"}
        seen.append(max(loud, key=loud.get))
    assert {"FL", "FC", "FR", "SR", "SL"} <= set(seen)              # it went everywhere
    order = [r for k, r in enumerate(seen) if k == 0 or r != seen[k - 1]]
    assert order.index("FC") < order.index("FR") < order.index("SR")   # clockwise from front left
    eng.set_fun({})
    for _ in range(int(0.5 * SR / N)):
        out = eng.process(x)[dev.id]
    fl = by_role["FL"].channel
    others = [s.channel for r, s in by_role.items() if r not in ("FL", "LFE")]
    assert np.max(np.abs(out[:, fl])) > 0.25 and np.max(np.abs(out[:, others])) < 1e-6   # back home


def test_effects_change_the_pc_sound_but_not_test_sounds():
    p, eng, dev = five_one()
    eng.set_fun({"robot": 45})
    spk = dev.speakers[0]
    eng.identify(spk.id, 1.0, "noise")
    a = eng.process(np.zeros((N, 8)))[dev.id][:, spk.channel]
    eng2 = Engine(p)
    eng2.configure(SR, 8)
    eng2.identify(spk.id, 1.0, "noise")
    b = eng2.process(np.zeros((N, 8)))[dev.id][:, spk.channel]
    assert np.allclose(a, b)
