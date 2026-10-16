"""Mute and solo keep the music whole, and speakers keep their lows while there is no
subwoofer to take them."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from speakerweave.engine import Engine
from speakerweave.model import Project
from speakerweave.presets import apply_range_preset

SR = 48000.0
N = 480
L_HZ, R_HZ = 440.0, 660.0


def eli_room():
    """The setup from the screenshot: laptop SL and FL, DELL both centre, VG258 FR and SR."""
    p = Project(input_kind="loopback", master_db=0.0, bass_redirect=False)
    p.set_mode("5.1", rear=False)
    laptop, dell, vg = p.add_device("Laptop", 2), p.add_device("DELL", 2), p.add_device("VG258", 2)
    for spk, role in ((laptop.speakers[0], "SL"), (laptop.speakers[1], "FL"),
                      (dell.speakers[0], "FC"), (dell.speakers[1], "FC"),
                      (vg.speakers[0], "FR"), (vg.speakers[1], "SR")):
        p.set_role(spk, role)
        spk.hp_on = spk.lp_on = False
    eng = Engine(p)
    eng.configure(SR, 8)
    return p, eng, laptop, dell, vg


def spotify(eng, seconds=1.0, left=L_HZ, right=R_HZ, level=0.4):
    """Stereo music into a 7.1 device: front left and right only. Returns the last block."""
    out = None
    for b in range(int(seconds * SR / N)):
        t = (np.arange(N) + b * N) / SR
        block = np.zeros((N, 8), dtype=np.float32)
        block[:, 0] = level * np.sin(2 * np.pi * left * t)
        block[:, 1] = level * np.sin(2 * np.pi * right * t)
        out = eng.process(block)
    return out


def tone_level(signal, freq):
    x = signal * np.hanning(len(signal))
    spec = np.abs(np.fft.rfft(x)) / (len(x) / 4)
    k = int(round(freq * len(x) / SR))
    return float(spec[max(0, k - 2):k + 3].max())


def test_a_soloed_speaker_plays_the_whole_song():
    p, eng, laptop, dell, vg = eli_room()
    laptop.speakers[1].solo = True                     # the laptop's right speaker, front left
    eng.rebuild()
    out = spotify(eng)
    solo = out[laptop.id][:, 1]
    assert tone_level(solo, L_HZ) > 0.1 and tone_level(solo, R_HZ) > 0.1   # left and right
    assert np.abs(out[dell.id]).max() == 0 and np.abs(out[vg.id]).max() == 0
    assert np.abs(out[laptop.id][:, 0]).max() == 0
    loud = spotify(eng, left=440.0, right=440.0, level=0.9)                 # the same in both
    assert np.abs(loud[laptop.id][:, 1]).max() < 1.0                        # no clipping


def test_a_muted_speaker_hands_its_part_to_the_others():
    p, eng, laptop, dell, vg = eli_room()
    vg.speakers[0].mute = True                         # front right muted
    eng.rebuild()
    out = spotify(eng)
    assert np.abs(out[vg.id][:, 0]).max() == 0
    others = [out[laptop.id][:, 1], out[dell.id][:, 0], out[dell.id][:, 1], out[vg.id][:, 1]]
    assert max(tone_level(x, R_HZ) for x in others) > 0.1           # the right side still plays
    vg.speakers[0].mute = False
    eng.rebuild()
    out = spotify(eng)
    assert tone_level(out[vg.id][:, 0], R_HZ) > 0.1                 # and back on its own speaker


def test_without_a_subwoofer_speakers_keep_their_lows():
    p, eng, laptop, dell, vg = eli_room()
    for spk in dell.speakers:
        apply_range_preset(spk, "tiny")                # monitor preset: nothing below 200 Hz
    eng.rebuild()
    out = spotify(eng, left=60.0, right=60.0)
    assert tone_level(out[dell.id][:, 0], 60.0) > 0.1               # no subwoofer: the bass stays
    p.keep_lows = False
    eng.rebuild()
    out = spotify(eng, left=60.0, right=60.0)
    assert tone_level(out[dell.id][:, 0], 60.0) < 0.02              # the cut, as set
    p.keep_lows = True
    sub_dev = p.add_device("Sub", 2)
    p.set_role(sub_dev.speakers[0], "LFE")
    eng.rebuild()
    out = spotify(eng, left=60.0, right=60.0)
    assert tone_level(out[dell.id][:, 0], 60.0) < 0.02              # a subwoofer takes it now
