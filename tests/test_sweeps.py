"""Speaker sweeps: a sound that goes round every speaker, or across the front from left to
right, gliding from one speaker to the next."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from speakerweave import engine as engine_module
from speakerweave.engine import Engine
from speakerweave.model import Project

SR = 48000.0
N = 480


def room():
    """Five speakers on one 8 channel output: FL FR C and the side pair, plus a subwoofer."""
    p = Project(input_kind="loopback", master_db=0.0, bass_redirect=False)
    p.set_mode("5.1", rear=False)
    dev = p.add_device("Speakers (Realtek)", 8)
    for spk in dev.speakers:
        spk.hp_on = spk.lp_on = False
    eng = Engine(p)
    eng.configure(SR, 8)
    return p, eng, dev


def run(eng, seconds):
    """{speaker id: loudness per block} while the sweep plays."""
    blocks = []
    for _ in range(int(seconds * SR / N)):
        blocks.append(eng.process(np.zeros((N, 8), dtype=np.float32)))
    return blocks


def loudest(blocks, dev, at):
    out = blocks[at][dev.id]
    return dev.speakers[int(np.argmax([np.abs(out[:, s.channel]).max() for s in dev.speakers]))].role


def test_the_pan_shares_a_sound_between_the_two_speakers_either_side():
    pts = [("fl", -30.0), ("fr", 30.0), ("sr", 110.0), ("sl", -110.0)]
    g = Engine._pan(0.0, pts, True)
    assert set(g) == {"fl", "fr"} and abs(g["fl"] - g["fr"]) < 1e-9
    assert abs(g["fl"] ** 2 + g["fr"] ** 2 - 1.0) < 1e-9            # equal power
    assert Engine._pan(110.0, pts, True)["sr"] > 0.999
    assert set(Engine._pan(180.0, pts, True)) == {"sr", "sl"}       # behind: round the back
    line = Engine._pan(-90.0, [("a", -30.0), ("b", 30.0)], False)
    assert line["a"] > 0.999                                         # never past the end


def test_the_circle_goes_round_clockwise_from_ahead_and_ends():
    p, eng, dev = room()
    from speakerweave.model import speaker_angle
    targets = [(s.id, speaker_angle(p, dev, s)) for s in dev.speakers if s.role in ("FL", "FR", "FC", "SL", "SR")]
    eng.set_sweep("circle", targets, 1)
    assert eng.sweeping
    period, passes = engine_module.SWEEPS["circle"]
    blocks = run(eng, period * passes + 0.2)
    per_s = SR / N
    order = [loudest(blocks, dev, int(f * period * per_s)) for f in (0.03, 0.25, 0.5, 0.75, 0.92)]
    assert order[0] == "FC"
    assert order.index("SR") < order.index("SL")                  # right side first: clockwise
    sub = next(s for s in dev.speakers if s.role == "LFE")
    assert max(np.abs(b[dev.id][:, sub.channel]).max() for b in blocks) == 0.0   # never the sub
    assert not eng.sweeping                                       # it ended by itself
    assert np.abs(blocks[-1][dev.id]).max() == 0.0


def test_left_to_right_stays_in_front():
    p, eng, dev = room()
    from speakerweave.model import speaker_angle
    targets = [(s.id, speaker_angle(p, dev, s)) for s in dev.speakers if s.role in ("FL", "FR", "FC")]
    eng.set_sweep("sides", targets, 2)
    period, _ = engine_module.SWEEPS["sides"]
    blocks = run(eng, period)
    per_s = SR / N
    assert loudest(blocks, dev, int(0.02 * period * per_s)) == "FL"
    assert loudest(blocks, dev, int(0.25 * period * per_s)) == "FC"
    assert loudest(blocks, dev, int(0.5 * period * per_s) - 1) == "FR"
    assert loudest(blocks, dev, int(0.98 * period * per_s)) == "FL"
    sides = [s for s in dev.speakers if s.role in ("SL", "SR")]
    assert all(np.abs(b[dev.id][:, s.channel]).max() == 0.0 for b in blocks for s in sides)


def test_the_app_starts_a_sweep_and_tells_you_what_to_listen_for():
    from test_hidden_outputs import pump, window
    app, state, win = window([{"name": "Speakers", "outputs": 8}])
    try:
        dev = state.project.add_device("Speakers", 8)
        targets = state.sweep_targets("sides")
        roles = {s.role for s in dev.speakers if s.id in dict(targets)}
        assert roles <= {"FL", "FR", "FC"} and len(roles) >= 2
        assert all(not r.startswith("LFE") for r in {s.role for s in dev.speakers if s.id in dict(state.sweep_targets("circle"))})
        state.runner.running = True                     # as if the sound were on
        assert state.start_sweep("circle") and state.sweep_kind == "circle"
        assert "clockwise" in win.sweep_text()
        menu = win.play_btn.menu()
        win._fill_play_menu(menu)
        texts = [a.text() for a in menu.actions()]
        assert "Stop the sweep" in texts and any("360" in t for t in texts)
        state.stop_sweep()
        assert state.sweep_kind == "" and not state.engine.sweeping
    finally:
        state.runner.running = False
        win.close()
        state.stop()
        pump(app, 0.1)
