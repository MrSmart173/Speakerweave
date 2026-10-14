"""The metronome: clicks that leave every speaker at the same moment, so what is
heard out of step comes from the speakers themselves."""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from speakerweave.engine import Engine
from speakerweave.model import Project

SR = 48000.0


def rig():
    p = Project(mode="2.1", input_kind="device", input_name="Line in", master_db=0.0)
    p.bass_redirect = False
    tv = p.add_device("TV", 2)
    sub = p.add_device("Sub amp", 1)
    p.set_role(sub.speakers[0], "LFE")
    for spk in tv.speakers:
        spk.hp_on = spk.lp_on = False
    eng = Engine(p)
    eng.configure(SR, 2)
    return p, tv, sub, eng


def onsets(signal, threshold=0.05):
    """Sample positions where a click starts."""
    loud = np.abs(signal) > threshold
    starts = np.flatnonzero(loud[1:] & ~loud[:-1]) + 1
    keep, last = [], -10 ** 9
    for s in starts:
        if s - last > 2000:
            keep.append(int(s))
        last = s if s - last > 2000 else last
    return keep


def play(eng, blocks, n=480):
    music = np.full((n, 2), 0.3, dtype=np.float32)          # the PC sound, which must wait
    outs = [eng.process(music) for _ in range(blocks)]
    return {dev: np.concatenate([o[dev] for o in outs]) for dev in outs[0]}


def test_every_speaker_clicks_at_the_same_moment_and_delay_moves_a_click():
    p, tv, sub, eng = rig()
    left, right = tv.speakers
    eng.set_metronome(120, [(left.id, False), (right.id, False), (sub.speakers[0].id, True)])
    assert eng.metronome_on
    out = play(eng, 300)                                     # 3 seconds: 6 beats
    a, b = onsets(out[tv.id][:, 0]), onsets(out[tv.id][:, 1])
    assert len(a) == 6 and a == b and a[1] - a[0] == 24000   # 120 BPM, exactly together
    assert abs(a[0] - int(0.08 * SR)) <= 3
    assert np.abs(out[tv.id]).max() < 0.75                   # no PC sound underneath, no overload
    thump = out[sub.id][:, 0]
    spectrum = np.abs(np.fft.rfft(thump[a[1]:a[1] + 4800]))
    assert np.argmax(spectrum) * SR / 4800 < 120             # the sub gets a low thump

    right.delay_ms = 5.0                                    # a later speaker, as heard by ear
    eng.update_speaker(right.id) if hasattr(eng, "update_speaker") else eng.rebuild()
    out = play(eng, 300)
    a, b = onsets(out[tv.id][:, 0]), onsets(out[tv.id][:, 1])
    assert all(y - x == 240 for x, y in zip(a, b))           # 5 ms later, exactly


def test_one_speaker_after_another_and_back_to_the_pc_sound():
    p, tv, sub, eng = rig()
    left, right = tv.speakers
    eng.set_metronome(240, [(left.id, False), (right.id, False)], turns=True)
    out = play(eng, 400)
    a, b = onsets(out[tv.id][:, 0]), onsets(out[tv.id][:, 1])
    assert a and b and all((y - x) == 12000 for x, y in zip(a, b))   # right comes one beat after left
    assert a[1] - a[0] == 24000                                      # each plays every second beat
    eng.stop_metronome()
    assert not eng.metronome_on
    out = play(eng, 50)
    assert np.abs(out[tv.id][-480:]).max() > 0.1                     # the PC sound is back


def state_rig():
    from PySide6.QtWidgets import QApplication
    from fake_audio import FakeSoundDevice
    from speakerweave import backend
    from speakerweave.ui import state as state_module
    folder = tempfile.mkdtemp()
    state_module.config_dir = lambda: folder
    QApplication.instance() or QApplication([])
    backend._sd = lambda: FakeSoundDevice([{"name": "TV", "outputs": 2},
                                           {"name": "Rear", "outputs": 2},
                                           {"name": "Line in", "inputs": 2, "silent": True}])
    from speakerweave.ui.state import AppState
    state = AppState("")
    state.settings.default_output = False
    p = state.project = Project(mode="4.0", input_kind="device", input_name="Line in")
    state.engine.project = state.runner.project = state.rgb.project = p
    front = p.add_device("TV", 2)
    rear = p.add_device("Rear", 2)
    front.x, front.y, front.rotation = 0.0, -1.5, 0.0
    rear.x, rear.y, rear.rotation = 0.0, 2.0, 180.0
    p.set_role(front.speakers[0], "FL")
    p.set_role(front.speakers[1], "FR")
    p.set_role(rear.speakers[0], "BR")
    p.set_role(rear.speakers[1], "BL")
    state.scan_devices()
    state.touch_streams()
    return state, front, rear


def test_the_click_goes_round_the_room_clockwise_from_front_left():
    state, front, rear = state_rig()
    order = [spk_id for spk_id, _low in state.metronome_targets("turns")]
    names = {s.id: s.role for d in (front, rear) for s in d.speakers}
    roles = [names[i] for i in order]
    assert roles[0] == "FL" and roles[1] == "FR" and set(roles[2:]) == {"BR", "BL"}
    assert roles.index("BR") < roles.index("BL")               # clockwise: right side first
    assert state.metronome_targets("selected") == []
    state.select(front.id, front.speakers[1].id)
    assert [i for i, _ in state.metronome_targets("selected")] == [front.speakers[1].id]


def test_switching_it_on_starts_the_sound_and_off_stops_it_again():
    state, front, rear = state_rig()
    assert not state.runner.running
    assert state.start_metronome(mode="together", bpm=90)
    assert state.runner.running and state.engine.metronome_on
    assert state.settings.metronome_bpm == 90
    state._restart()                                         # a setting changed meanwhile
    assert state.engine.metronome_on
    state.stop_metronome()
    assert not state.engine.metronome_on and not state.runner.running
    state.start()                                            # the person started the sound
    state.start_metronome()
    state.stop_metronome()
    assert state.runner.running                              # so it keeps running
    state.start_metronome()
    state.stop()                                             # Stop ends the metronome too
    assert not state.engine.metronome_on
