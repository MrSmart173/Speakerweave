"""Tap along: each speaker's delay measured by tapping to its clicks, then lined up."""
import os
import random
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from speakerweave import engine as engine_module
from speakerweave.engine import Engine
from speakerweave.model import Project
from speakerweave.ui import tap_sync


def test_clicks_are_timed_by_the_pcs_clock_even_when_blocks_come_in_bursts(monkeypatch):
    p = Project(mode="2.0", master_db=0.0)
    dev = p.add_device("TV", 2)
    eng = Engine(p)
    eng.configure(192000.0, 2)
    clock = [500.0]
    monkeypatch.setattr(engine_module.time, "perf_counter", lambda: clock[0])
    eng.set_metronome(75, [(dev.speakers[0].id, False)], False)
    block = np.zeros((480, 2))
    for packet in range(400):                        # 4 seconds of 10 ms packets
        clock[0] = 500.0 + (packet + 1) * 0.010 + random.Random(packet).uniform(0, 0.004)
        for _ in range(4):                           # four blocks at once, then nothing
            eng.process(block)
    times = list(eng.click_times)
    gaps = np.diff(times)
    assert len(times) >= 4 and np.allclose(gaps, 0.8, atol=0.0005)   # exactly a beat apart


def test_a_press_lands_where_it_was_made():
    clicks = [10.0, 10.8, 11.6]
    assert abs(tap_sync.nearest_offset_ms(11.69, clicks) - 90.0) < 1e-6
    assert abs(tap_sync.nearest_offset_ms(12.35, clicks) + 50.0) < 1e-6     # before the next one
    assert tap_sync.measured([90.0] * 3) is None                         # too few taps
    ms, spread = tap_sync.measured([88, 92, 90, 400, 91, 89, 90])        # one slip of the finger
    assert ms == 90 and spread <= 1


def test_tapping_to_two_speakers_lines_them_up(monkeypatch):
    from test_hidden_outputs import pump, window
    app, state, win = window([{"name": "TV", "outputs": 2}, {"name": "Monitor", "outputs": 2}])
    try:
        p = state.project
        p.set_mode("2.0")
        tv, mon = p.add_device("TV", 2), p.add_device("Monitor", 2)
        tv.enabled = mon.enabled = True
        p.set_role(mon.speakers[0], "FL")
        p.set_role(mon.speakers[1], "FR")
        tv.speakers[0].delay_ms = 9.0                                   # old, set before
        played = []
        monkeypatch.setattr(state, "play_clicks", lambda targets, bpm=0: played.append((targets, bpm)))
        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: QMessageBox.Ok))
        speakers = tap_sync.tap_speakers(p)
        dialog = tap_sync.TapSyncDialog(win, speakers)
        assert all(s.delay_ms == 0.0 for d in (tv, mon) for s in d.speakers)   # a clean start
        assert played[-1] == ([speakers[0]], tap_sync.BPM)
        assert abs(state.engine.test_gain - 10 ** (state.settings.test_boost_db / 20)) < 1e-9
        assert not dialog.use_btn.isEnabled()

        lag = {tv.speakers[0].id: 0.120, mon.speakers[0].id: 0.045}     # how late each really is
        rng = random.Random(4)
        for row, spk_id in enumerate((tv.speakers[0].id, mon.speakers[0].id)):
            dialog.list.setCurrentRow([s for s, _low in speakers].index(spk_id))
            assert played[-1][0] == [(spk_id, False)]
            state.engine.click_times.extend([100.0 + 0.8 * k for k in range(8)])
            for k in range(8):
                dialog.tap(at=100.0 + 0.8 * k + lag[spk_id] + rng.uniform(-0.008, 0.008))
        results = dialog.results()
        assert abs(results[tv.speakers[0].id]) < 0.05                 # the slowest: 0 ms
        assert abs(results[mon.speakers[0].id] - 75.0) < 8.0          # waits for the TV
        assert dialog.use_btn.isEnabled() and "ms" in dialog.list.item(0).text()

        shot = os.environ.get("SPEAKERWEAVE_SHOT")
        if shot:
            dialog.show()
            pump(app, 0.2)
            dialog.grab().save(shot)

        dialog.use_btn.click()
        assert abs(mon.speakers[0].delay_ms - results[mon.speakers[0].id]) < 1e-9
        assert tv.speakers[0].delay_ms == results[tv.speakers[0].id]
        assert mon.speakers[1].delay_ms == 0.0                          # not measured: as it was
        assert state.engine.test_gain == 1.0                            # normal volume again

        tv.speakers[0].delay_ms = 33.0
        dialog = tap_sync.TapSyncDialog(win, speakers)
        dialog.cancel_btn.click()
        assert tv.speakers[0].delay_ms == 33.0                          # Cancel: as it was
    finally:
        monkeypatch.undo()
        win.close()
        state.stop()
        pump(app, 0.1)
