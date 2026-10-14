"""A surround channel test (one channel at a time) must come out of that channel's
speakers only, also front left and front right, which used to be spread like stereo."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from speakerweave.engine import Engine
from speakerweave.model import Project

SR = 48000.0
SEVEN_ONE = ["FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"]     # Windows' 7.1 channel order


def elis_room():
    """The setup from the screenshot: 5.0 with the surround pair at the sides."""
    p = Project(mode="5.0", input_kind="loopback", input_name="CABLE Input [Loopback]",
                master_db=0.0, bass_redirect=False)
    p.set_mode("5.0", rear=False)
    laptop, dell, vg = p.add_device("Laptop", 2), p.add_device("DELL", 2), p.add_device("VG258", 2)
    for spk, role in ((laptop.speakers[0], "SL"), (laptop.speakers[1], "FL"),
                      (dell.speakers[0], "FL"), (dell.speakers[1], "FR"),
                      (vg.speakers[0], "FR"), (vg.speakers[1], "SR")):
        p.set_role(spk, role)
        spk.hp_on = spk.lp_on = False
    eng = Engine(p)
    eng.configure(SR, 8)
    return p, eng, {"laptop": laptop, "dell": dell, "vg": vg}


def play(eng, active, seconds=2.0):
    """Tone on the given source channels only, the way a test page plays it."""
    n = 480
    t = np.arange(n) / SR
    out = None
    for b in range(int(seconds * SR / n)):
        block = np.zeros((n, 8), dtype=np.float32)
        for name in active:
            block[:, SEVEN_ONE.index(name)] = 0.3 * np.sin(2 * np.pi * 440 * (t + b * n / SR))
        out = eng.process(block)
    return out


def loud(out, devs):
    """{speaker role on its device: playing} for the last block."""
    found = set()
    for key, dev in devs.items():
        for spk in dev.speakers:
            if np.abs(out[dev.id][:, spk.channel]).max() > 0.01:
                found.add(f"{key} {spk.role}")
    return found


def test_each_channel_of_a_channel_test_plays_on_its_own_speakers():
    p, eng, devs = elis_room()
    assert loud(play(eng, ["FL"]), devs) == {"laptop FL", "dell FL"}
    assert loud(play(eng, ["FR"]), devs) == {"dell FR", "vg FR"}
    assert loud(play(eng, ["SL"]), devs) == {"laptop SL"}
    assert loud(play(eng, ["SR"]), devs) == {"vg SR"}
    # no centre speaker in 5.0 without it: the centre is shared by the front speakers
    assert loud(play(eng, ["FC"]), devs) == {"laptop FL", "dell FL", "dell FR", "vg FR"}
    # and front left again, long after the last surround sound
    assert loud(play(eng, ["FL"], seconds=6.0), devs) == {"laptop FL", "dell FL"}


def test_stereo_music_is_still_spread_over_every_speaker():
    p, eng, devs = elis_room()
    out = play(eng, ["FL", "FR"], seconds=5.0)
    assert loud(out, devs) == {"laptop SL", "laptop FL", "dell FL", "dell FR", "vg FR", "vg SR"}
    assert not eng.surround_now
    p.upmix = False                                     # "Fill every speaker" off: fronts only
    eng.rebuild()
    out = play(eng, ["FL", "FR"], seconds=2.0)
    assert loud(out, devs) == {"laptop FL", "dell FL", "dell FR", "vg FR"}
