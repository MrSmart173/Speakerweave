"""Easy sync: speakers matched by ear two at a time, then shifted so the earliest is at 0 ms."""
import os
import random
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from speakerweave.easysync import EasySync
from speakerweave.model import SHAKER, Project


def room():
    p = Project(mode="5.1")
    tv = p.add_device("TV", 2)
    rear = p.add_device("Rear", 2)
    sub = p.add_device("Sub", 1)
    seat = p.add_device("Seat", 1)
    p.set_role(tv.speakers[0], "FL")
    p.set_role(tv.speakers[1], "FR")
    p.set_role(rear.speakers[0], "SL")
    p.set_role(rear.speakers[1], "SR")
    p.set_role(sub.speakers[0], "LFE")
    p.set_role(seat.speakers[0], SHAKER)
    return p, tv, rear, sub, seat


# How late each speaker really is (device lag), which only the person's ears can hear
LAG = {"TV": 40.0, "Rear": 5.0, "Sub": 12.0}


def heard_gap(p, sync):
    """ms by which the matched speaker is heard after the new one (what the ears judge)."""
    a, b = sync.pair()
    (da, sa), (db, sb) = p.find_speaker(a), p.find_speaker(b)
    return (LAG[da.name] + sa.delay_ms) - (LAG[db.name] + sb.delay_ms)


def listen_and_fix(p, sync):
    """A person nudging the earlier speaker until the click is one: steps of 5, 1 and 0.2 ms."""
    for step in (5.0, 1.0, 0.2):
        for _ in range(200):
            gap = heard_gap(p, sync)
            if abs(gap) < step:
                break
            a, b = sync.pair()
            sync.hold_back(b if gap > 0 else a, step)


def test_every_speaker_is_matched_once_with_subwoofers_last_and_shakers_left_out():
    p, tv, rear, sub, seat = room()
    sync = EasySync(p, random.Random(3))
    assert sorted(sync.order[:-1]) == sorted(s.id for s in tv.speakers + rear.speakers)
    assert sync.order[-1] == sub.speakers[0].id and seat.speakers[0].id not in sync.order
    assert sync.pairs == 4
    seen = set()
    for i in range(sync.pairs):
        a, b = sync.pair()
        assert a in seen or i == 0                       # each pair joins one new speaker
        seen |= {a, b}
        if i + 1 < sync.pairs:
            assert sync.next()
    assert sync.low_pair() and not sync.next()           # the last pair has the sub: both thump
    assert seen == set(sync.order)


def test_matching_by_ear_lines_everyone_up_with_the_earliest_at_0():
    for seed in range(6):
        p, tv, rear, sub, seat = room()
        tv.speakers[0].delay_ms = 7.0                    # something set earlier
        sync = EasySync(p, random.Random(seed))
        while True:
            listen_and_fix(p, sync)
            if not sync.next():
                break
        final = sync.finish()
        arrivals = [LAG[d.name] + s.delay_ms for d in p.devices for s in d.speakers
                    if s.id in final]
        assert max(arrivals) - min(arrivals) <= 0.6, (seed, arrivals)     # all together
        assert min(final.values()) == 0.0                                 # as early as possible
        assert abs(max(arrivals) - max(LAG.values())) <= 0.6              # the slowest needs nothing
        assert seat.speakers[0].delay_ms == 0.0


def test_holding_back_a_matched_speaker_keeps_earlier_pairs_matched_and_cancel_restores():
    p, tv, rear, sub, seat = room()
    sync = EasySync(p, random.Random(1))
    before = {i: sync.delay(i) for i in sync.order}
    a, b = sync.pair()
    sync.hold_back(a, 3.0)
    sync.next()
    first_two = sync.matched()
    sync.hold_back(sync.pair()[0], 2.0)                  # the matched side moves together
    assert (sync.delay(first_two[0]), sync.delay(first_two[1])) == (5.0, 2.0)   # still 3 ms apart
    changed = sync.hold_back(sync.pair()[0], -9.0)       # cannot go below 0: the new one waits instead
    assert changed == [sync.pair()[1]] and sync.delay(sync.pair()[1]) == 9.0
    sync.cancel()
    assert {i: sync.delay(i) for i in sync.order} == before


def test_the_window_walks_through_the_pairs_and_ticks_on_them():
    from PySide6.QtWidgets import QApplication, QMessageBox
    from fake_audio import FakeSoundDevice
    from speakerweave import backend
    from speakerweave.ui import state as state_module
    from speakerweave.ui import theme
    folder = tempfile.mkdtemp()
    state_module.config_dir = lambda: folder
    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    backend._sd = lambda: FakeSoundDevice([{"name": "TV", "outputs": 2}, {"name": "Rear", "outputs": 2},
                                           {"name": "Line in", "inputs": 2, "silent": True}])
    from speakerweave.ui.state import AppState
    from speakerweave.ui.window import MainWindow
    state = AppState("")
    s = state.settings
    s.default_output = s.start_sound = s.simhub_link = s.check_updates = False
    s.tour_done = True
    p = state.project = Project(mode="4.0", input_kind="device", input_name="Line in")
    state.engine.project = state.runner.project = state.rgb.project = p
    p.add_device("TV", 2)
    rear = p.add_device("Rear", 2)
    p.set_role(rear.speakers[0], "BL")
    p.set_role(rear.speakers[1], "BR")
    win = MainWindow(state)
    state.scan_devices()
    real_information = QMessageBox.information
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
    try:
        _walk_through(state, win, p)
    finally:
        QMessageBox.information = real_information
    win._quitting = True
    win.close()
    app.processEvents()


def _walk_through(state, win, p):
    from PySide6.QtWidgets import QDialog
    from speakerweave.ui.easy_sync import EasySyncDialog
    dialog = EasySyncDialog(win, EasySync(p, random.Random(2)))
    assert state.runner.running and state.engine.metronome_on       # started just for the clicks
    a, b = dialog.sync.pair()
    assert {t for t, _low in state.engine._metro[1]} == {a, b}
    dialog.right.buttons[0].click()                                  # +5 ms on the new speaker
    assert p.find_speaker(b)[1].delay_ms == 5.0 and "5.0 ms" in dialog.right.delay.text()
    while "finish" not in dialog.next_btn.text():
        dialog.next_btn.click()
    dialog.next_btn.click()
    assert dialog.result() == QDialog.Accepted
    assert not state.engine.metronome_on and not state.runner.running   # back to how it was
    assert min(s.delay_ms for d in p.devices for s in d.speakers) == 0.0

    dialog = EasySyncDialog(win, EasySync(p, random.Random(5)))
    before = {s.id: s.delay_ms for d in p.devices for s in d.speakers}
    dialog.left.buttons[0].click()
    dialog.cancel_btn.click()
    assert {s.id: s.delay_ms for d in p.devices for s in d.speakers} == before

    # steps of 5, 1 and 0.1 ms both ways, and the clicks louder while the window is open
    state.settings.test_boost_db = 6.0
    dialog = EasySyncDialog(win, EasySync(p, random.Random(7)))
    texts = [b.text() for b in dialog.right.buttons]
    assert texts == ["+5 ms", "+1 ms", "+0.1 ms", "\u22125 ms", "\u22121 ms", "\u22120.1 ms"]
    assert abs(state.engine.test_gain - 10 ** (6 / 20)) < 1e-9 and dialog.boost_text.text() == "+6 dB"
    _a, b = dialog.sync.pair()
    spk = p.find_speaker(b)[1]
    start = spk.delay_ms
    for i in (0, 1, 2, 2, 5):                                        # +5 +1 +0.1 +0.1 -0.1
        dialog.right.buttons[i].click()
    assert abs(spk.delay_ms - (start + 6.1)) < 1e-9 and f"{start + 6.1:.1f} ms" in dialog.right.delay.text()
    dialog.right.buttons[3].click()                                  # -5 ms
    assert abs(spk.delay_ms - (start + 1.1)) < 1e-9
    dialog.boost.setValue(9)                                         # louder still, by hand
    assert abs(state.engine.test_gain - 10 ** (9 / 20)) < 1e-9 and state.settings.test_boost_db == 9.0
    dialog.cancel_btn.click()
    assert state.engine.test_gain == 1.0                             # normal again once it closes
    state.settings.test_boost_db = 6.0


def test_test_sounds_get_louder_and_the_pc_sound_does_not():
    import numpy as np
    from speakerweave.engine import Engine
    p = Project(mode="2.0", input_kind="loopback", master_db=-12.0)
    dev = p.add_device("TV", 2)
    for spk in dev.speakers:
        spk.hp_on = spk.lp_on = False
    eng = Engine(p)
    eng.configure(48000.0, 2)
    left = dev.speakers[0]
    eng.set_metronome(100, [(left.id, False)], False)
    quiet = [eng.process(np.zeros((480, 2)))[dev.id][:, left.channel] for _ in range(20)]
    eng.stop_metronome()
    eng2 = Engine(p)
    eng2.configure(48000.0, 2)
    eng2.test_gain = 2.0
    eng2.set_metronome(100, [(left.id, False)], False)
    loud = [eng2.process(np.zeros((480, 2)))[dev.id][:, left.channel] for _ in range(20)]
    assert abs(np.max(np.abs(loud)) / np.max(np.abs(quiet)) - 2.0) < 0.05
    eng2.stop_metronome()
    music = np.full((480, 2), 0.1)
    plain = Engine(p)
    plain.configure(48000.0, 2)
    a = [plain.process(music)[dev.id] for _ in range(5)][-1]
    b = [eng2.process(music)[dev.id] for _ in range(5)][-1]
    assert np.allclose(a, b)                                          # the PC sound is left alone


def test_typing_a_delay_and_sweeping_to_the_right_spot():
    import random as _random
    from PySide6.QtWidgets import QApplication
    from test_hidden_outputs import pump, window
    from speakerweave.ui import easy_sync as ui
    app, state, win = window([{"name": "TV", "outputs": 2}, {"name": "Rear", "outputs": 2}])
    try:
        p = state.project
        p.set_mode("4.0")
        tv, rear = p.add_device("TV", 2), p.add_device("Rear", 2)
        tv.enabled = rear.enabled = True
        p.set_role(rear.speakers[0], "BL")
        p.set_role(rear.speakers[1], "BR")
        for spk in tv.speakers + rear.speakers:
            spk.delay_ms = 7.5                                     # left over from before
        sync = EasySync(p, _random.Random(3), from_zero=True)
        assert all(s.delay_ms == 0.0 for s in tv.speakers + rear.speakers)   # a clean start
        dialog = ui.EasySyncDialog(win, sync)
        a, b = sync.pair()
        dialog.right.delay.setValue(12.3)                          # typed in
        assert sync.delay(b) == 12.3
        dialog.left.delay.setValue(2.0)                            # the matched side moves too
        assert sync.delay(a) == 2.0 and sync.delay(b) == 12.3

        dialog.speed.setCurrentIndex(2)                            # 2 ms a second
        dialog.right.sweep_up.click()
        assert dialog.right.sweep_up.text() == "Stop" and not dialog.right.buttons[0].isEnabled()
        assert not dialog.left.sweep_up.isEnabled()
        for _ in range(10):                                        # a second of sweeping
            dialog._sweep_tick()
        assert abs(sync.delay(b) - 14.3) < 1e-6
        dialog.right.sweep_up.click()                              # Stop: it stays right there
        assert dialog._sweep is None and dialog.right.sweep_up.text() == "Sweep later"
        dialog._sweep_tick()
        assert abs(sync.delay(b) - 14.3) < 1e-6

        dialog.left.sweep_down.click()                             # earlier, down to nothing
        for _ in range(40):
            dialog._sweep_tick()
        assert sync.delay(a) >= 0.0
        dialog.cancel_btn.click()
        assert dialog._sweep is None and not dialog._sweep_timer.isActive()
        assert all(s.delay_ms == 7.5 for s in tv.speakers + rear.speakers)   # Cancel: as before
        QApplication.processEvents()
    finally:
        win.close()
        state.stop()
        pump(app, 0.1)


def test_holding_a_step_button_repeats_and_speeds_up():
    from PySide6.QtWidgets import QApplication, QPushButton
    from speakerweave.ui.easy_sync import HoldRepeat
    QApplication.instance() or QApplication([])
    now = [0.0]
    hits = []
    button = QPushButton("+1 ms")
    hold = HoldRepeat(button, lambda: hits.append(now[0]), clock=lambda: now[0])
    button.setDown(True)
    hold.press()                                     # once, straight away
    assert hits == [0.0]

    def held_until(t, step=0.01):
        while now[0] < t - 1e-9:
            now[0] = round(now[0] + step, 4)
            hold.poll()

    held_until(1.79)
    assert len(hits) == 1                            # nothing more before 1.8 s
    held_until(3.0)
    slow = len(hits) - 1                             # 1.8 to 3 s: every 0.3 s
    held_until(5.0)
    medium = len(hits) - 1 - slow                    # 3 to 5 s: every 0.12 s
    held_until(6.0)
    fast = len(hits) - 1 - slow - medium             # from 5 s: every 0.04 s
    assert 3 <= slow <= 5 and 15 <= medium <= 18 and 23 <= fast <= 26
    assert slow / 1.2 < medium / 2.0 < fast / 1.0  # faster at every stage
    button.setDown(False)
    hold.poll()
    count = len(hits)
    held_until(7.0)
    assert len(hits) == count and not hold.timer.isActive()   # let go: it stops
    button.click()                                   # a plain click is still one step
    assert len(hits) == count + 1
