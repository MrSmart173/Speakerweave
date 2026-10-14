"""Runs the real stream code against pretend sound cards with drifting clocks.
Takes a few seconds because it runs in real time."""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fake_audio import FakeSoundDevice
from speakerweave import backend
from speakerweave.engine import Engine
from speakerweave.model import SOURCE_LAYOUTS, Project

S71 = SOURCE_LAYOUTS["7.1"]


def loudest_tone(x, sr=48000.0):
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.argmax(spectrum) * sr / len(x))


def test_three_tvs_live(monkeypatch=None):
    tones = {S71.index("FL"): 300.0, S71.index("FR"): 400.0, S71.index("BL"): 500.0,
             S71.index("BR"): 600.0, S71.index("SL"): 700.0, S71.index("SR"): 800.0}
    fake = FakeSoundDevice([
        {"name": "TV left", "outputs": 2, "ppm": -300},
        {"name": "TV middle", "outputs": 2, "ppm": 0},
        {"name": "TV right", "outputs": 2, "ppm": 250},
        {"name": "Mixer", "inputs": 8, "ppm": 40, "tones": tones},
    ])
    original = backend._sd
    backend._sd = lambda: fake
    try:
        proj = Project(mode="6.0", input_kind="device", input_name="Mixer",
                       master_db=0.0, buffer_ms=100.0)
        wanted = {"TV left": ("BL", "SL"), "TV middle": ("FL", "FR"), "TV right": ("SR", "BR")}
        for name, roles in wanted.items():
            dev = proj.add_device(name, 2)
            for spk, role in zip(dev.speakers, roles):
                proj.set_role(spk, role)
        runner = backend.AudioRunner(proj, Engine(proj))
        assert runner.start() == []
        time.sleep(1.0)
        settled = {k: v[2] for k, v in runner.status().items()}
        time.sleep(3.0)
        status = runner.status()
        runner.stop()
    finally:
        backend._sd = original

    assert runner.callback_errors == 0
    for dev_id, (fill, _ppm, drops) in status.items():
        assert drops == settled[dev_id], "dropouts after the start"
        assert 40 < fill < 180, fill
    expect = {"TV left": (500.0, 700.0), "TV middle": (300.0, 400.0), "TV right": (800.0, 600.0)}
    for name, freqs in expect.items():
        audio = np.concatenate(fake.streams[name].recorded)[-48000:]
        for ch, freq in enumerate(freqs):
            assert np.abs(audio[:, ch]).max() > 0.2, (name, ch)
            assert abs(loudest_tone(audio[:, ch]) - freq) < 3.0, (name, ch, loudest_tone(audio[:, ch]))


if __name__ == "__main__":
    test_three_tvs_live()
    print("ok")
