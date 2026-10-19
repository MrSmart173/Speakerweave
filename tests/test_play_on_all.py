"""A test sound with no speaker selected plays on every speaker that is not muted."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from speakerweave.engine import Engine
from speakerweave.model import OFF, Project


def test_the_engine_plays_a_test_sound_on_several_speakers_at_once():
    p = Project(mode="4.0", master_db=0.0)
    front, rear = p.add_device("Front", 2), p.add_device("Rear", 2)
    for spk in front.speakers + rear.speakers:
        spk.hp_on = spk.lp_on = False
    eng = Engine(p)
    eng.configure(48000.0, 2)
    chosen = [front.speakers[0].id, rear.speakers[1].id]
    eng.identify(chosen, 0.5, "noise")
    out = [eng.process(np.zeros((480, 2))) for _ in range(5)][-1]
    assert np.max(np.abs(out[front.id][:, 0])) > 0.01 and np.max(np.abs(out[rear.id][:, 1])) > 0.01
    assert np.max(np.abs(out[front.id][:, 1])) == 0 and np.max(np.abs(out[rear.id][:, 0])) == 0
    eng.identify(front.speakers[1].id, 0.5, "noise")                 # one speaker, as before
    out = eng.process(np.zeros((480, 2)))
    assert np.max(np.abs(out[front.id][:, 1])) > 0.01 and np.max(np.abs(out[front.id][:, 0])) == 0


def test_nothing_selected_plays_on_every_speaker_that_is_not_muted(monkeypatch):
    from test_hidden_outputs import pump, window
    app, state, win = window([{"name": "Front", "outputs": 2}, {"name": "Rear", "outputs": 2}])
    try:
        p = state.project
        p.set_mode("4.0")
        front, rear = p.add_device("Front", 2), p.add_device("Rear", 2)
        front.enabled = rear.enabled = True
        p.set_role(rear.speakers[0], "BL")
        p.set_role(rear.speakers[1], "BR")
        rear.speakers[1].mute = True
        played = []
        monkeypatch.setattr(state.engine, "identify",
                            lambda ids, seconds=1.5, kind="noise", samples=None: played.append((list(ids), kind)))
        monkeypatch.setattr(state.runner, "running", True)
        state.select("", "")
        win._play_selected("noise")
        ids, kind = played[-1]
        assert set(ids) == {front.speakers[0].id, front.speakers[1].id, rear.speakers[0].id}
        assert kind == "noise"
        rear.speakers[0].solo = True                                   # a solo: only that one
        win._play_selected("sweep")
        assert played[-1] == ([rear.speakers[0].id], "sweep")
        rear.speakers[0].solo = False
        p.set_role(front.speakers[0], OFF)                             # no role: not part of it
        win._play_selected("noise")
        assert front.speakers[0].id not in played[-1][0]
        state.select(front.id, front.speakers[1].id)                   # selected: only that one
        win._play_selected("noise")
        assert played[-1] == ([front.speakers[1].id], "noise")
        menu = win.play_btn.menu()
        win._fill_play_menu(menu)
        assert menu.actions()[0].text() == "On the selected speaker"
        state.select("", "")
        win._fill_play_menu(menu)
        assert menu.actions()[0].text() == "On every speaker (none is selected)"
    finally:
        monkeypatch.undo()
        win.close()
        state.stop()
        pump(app, 0.1)
