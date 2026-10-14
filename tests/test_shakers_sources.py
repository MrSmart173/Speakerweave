"""Bass shakers and extra sound sources (SimHub effects, a spotter app)."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from fake_audio import FakeSoundDevice
from speakerweave import backend
from speakerweave.engine import AdaptiveFifo, Engine
from speakerweave.mixer import build_matrix
from speakerweave.model import SHAKER, ExtraSource, Project, Route


def rig():
    p = Project(mode="5.1", input_kind="device", input_name="Line in", master_db=0.0)
    p.bass_redirect = False
    card = p.add_device("Card", 6)
    shakers = p.add_device("Shaker amp", 2)
    for spk in shakers.speakers:
        p.set_role(spk, SHAKER)
    for spk in card.speakers:
        spk.hp_on = spk.lp_on = False
    return p, card, shakers


def test_a_shaker_feels_the_game_bass_and_keeps_its_role_in_every_mode():
    p, card, shakers = rig()
    seat = shakers.speakers[0]
    assert seat.lp_on and seat.lp_freq == 80 and seat.hp_freq == 10      # shaker range
    assert SHAKER in p.roles_in_use() and SHAKER in p.role_choices()
    m = build_matrix(["FL", "FR", "FC", "LFE"], ["FL", "FR", SHAKER], shaker_gain=1.0)
    assert m[2].tolist() == [0.5, 0.5, 0.5, 1.0]
    assert not build_matrix(["FL", "FR"], [SHAKER], shaker_gain=0.0).any()
    p.set_mode("2.0")
    assert seat.role == SHAKER                    # not a position, so the mode leaves it alone
    p.set_role(seat, "FL")
    assert not seat.lp_on                         # its shaker range goes with the role
    again = Project.from_json(p.to_json())
    assert again.devices[1].speakers[1].role == SHAKER


def test_effects_from_an_extra_source_reach_only_the_chosen_speakers():
    p, card, shakers = rig()
    p.shaker_game_on = False                      # only the effects, no game bass
    fx = ExtraSource(name="SimHub fx", kind="device", label="SimHub effects")
    fx.route(2).targets = [shakers.speakers[0].id, shakers.speakers[1].id]   # channel 3: impacts
    fx.route(2).label = "Impacts"
    fx.route(0).targets = [card.speakers[0].id]                             # channel 1: tyres
    fx.route(0).gain_db = -6.0
    p.extra_sources.append(fx)
    eng = Engine(p)
    eng.configure(48000.0, 2)
    fifo = AdaptiveFifo(8, 48000.0, 40.0)
    eng.extra_fifos[fx.id] = fifo
    effects = np.zeros((48000, 8), dtype=np.float32)
    effects[:, 2] = 0.4 * np.sin(2 * np.pi * 40 * np.arange(48000) / 48000.0)   # a 40 Hz rumble
    effects[:, 0] = 0.2
    pos = 0

    def feed(blocks):
        nonlocal pos
        out = None
        for _ in range(blocks):
            fifo.write(effects[pos:pos + 480])
            pos += 480
            out = eng.process(np.zeros((480, 2)))
        return out
    for _ in range(5):                       # the source runs a little ahead, like a real one
        fifo.write(effects[pos:pos + 480])
        pos += 480
    outs = feed(10)
    seat = outs[shakers.id]
    assert np.abs(seat[:, 0]).max() > 0.2 and np.abs(seat[:, 1]).max() > 0.2
    front_left = outs[card.id][:, 0]
    assert 0.08 < np.abs(front_left).max() < 0.12          # 0.2 at -6 dB
    assert np.abs(outs[card.id][:, 1:]).max() < 1e-6       # nobody else hears the effects
    assert eng.extra_peaks[fx.id][2] > 0.3
    shakers.speakers[1].mute = True                        # mute still works on extra sound
    eng.rebuild()
    outs = feed(30)                                        # once the filter has rung out
    assert np.abs(outs[shakers.id][:, 1]).max() < 1e-3
    again = Project.from_json(p.to_json())
    assert again.extra_sources[0].route(2).label == "Impacts"


def test_extra_source_runs_live_next_to_the_pc_sound():
    fake = FakeSoundDevice([{"name": "Card", "outputs": 6},
                            {"name": "Shaker amp", "outputs": 2},
                            {"name": "Line in", "inputs": 2, "silent": True},
                            {"name": "SimHub fx", "inputs": 8, "tones": {2: 40}}])
    backend._sd = lambda: fake
    p, card, shakers = rig()
    p.shaker_game_on = False
    fx = ExtraSource(name="SimHub fx", kind="device")
    fx.route(2).targets = [shakers.speakers[0].id]
    p.extra_sources.append(fx)
    eng = Engine(p)
    eng.rebuild()
    runner = backend.AudioRunner(p, eng)
    problems = runner.start()
    assert runner.running and not problems, problems
    time.sleep(1.0)
    runner.stop()
    played = np.concatenate(fake.streams["Shaker amp"].recorded)
    assert np.abs(played[:, 0]).max() > 0.05 and np.abs(played[:, 1]).max() == 0.0
    assert eng.extra_fifos == {}
    # the same device as the PC sound is refused with a clear reason
    fx.name = "Line in"
    runner = backend.AudioRunner(p, eng)
    problems = runner.start()
    assert any("same device" in text for text in problems)
    runner.stop()


def test_effects_tab_adds_sources_and_routes_channels():
    import tempfile
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from speakerweave.ui import state as state_module
    from speakerweave.ui import theme
    state_module.config_dir = lambda d=tempfile.mkdtemp(): d
    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    fake = FakeSoundDevice([{"name": "Card", "outputs": 2},
                            {"name": "Line in", "inputs": 2, "silent": True},
                            {"name": "SimHub fx", "inputs": 8, "silent": True}])
    backend._sd = lambda: fake
    from speakerweave.ui.state import AppState
    from speakerweave.ui.extras import ExtrasPanel
    state = AppState("")
    state.settings.default_output = False
    state.scan_devices()
    p = state.project
    p.input_kind, p.input_name = "device", "Line in"
    card = p.add_device("Card", 2)
    p.set_role(card.speakers[1], SHAKER)
    panel = ExtrasPanel(state)
    panel.add_source("simhub")
    src = p.extra_sources[0]
    assert src.label == "SimHub effects" and src.name == ""      # no virtual device here
    src.kind, src.name = "device", "SimHub fx"
    panel.load()
    rows = panel.rows[src.id]
    assert len(rows) == 8 and rows[2].name.placeholderText() == "Channel 3 (centre)"
    rows[2]._toggle(card.speakers[1].id, True)
    assert src.route(2).targets == [card.speakers[1].id] and "Card" in rows[2].targets.text()
    assert state.engine._plan.slots == 1
    rows[2].gain.setValue(-6.0)
    assert src.route(2).gain_db == -6.0
    panel.game_bass.setChecked(False)
    assert not p.shaker_game_on
    assert "1 speaker set up as bass shaker" in panel.shaker_note.text()
    panel._remove(src)
    assert p.extra_sources == []
