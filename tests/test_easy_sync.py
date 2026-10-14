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
