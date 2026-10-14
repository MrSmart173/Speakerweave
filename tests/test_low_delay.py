"""A safety buffer of 0 ms: as little delay as the devices allow, with every output in line."""
import os
import random
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from speakerweave.backend import AudioRunner
from speakerweave.engine import AdaptiveFifo, Engine
from speakerweave.model import Project

SR = 48000.0
BLOCK = 480


def run(fifo, read_frames, seconds=20.0, jitter_ms=2.0, seed=1):
    """Our blocks arrive every 10 ms, the device takes read_frames at its own pace,
    both a little uneven, the way Windows hands them out."""
    rng = random.Random(seed)
    events = []
    t = 0.0
    while t < seconds:
        events.append((t + rng.uniform(0, jitter_ms) / 1000.0, "w"))
        t += BLOCK / SR
    t = 0.0037
    while t < seconds:
        events.append((t + rng.uniform(0, jitter_ms) / 1000.0, "r"))
        t += read_frames / SR
    block = np.full((BLOCK, fifo.channels), 0.1, dtype=np.float32)
    dry_after_start = 0
    for when, kind in sorted(events):
        if kind == "w":
            fifo.write(block)
            fifo.set_target(max(fifo.target, fifo.need))      # what the runner does after each block
        else:
            out = fifo.read(read_frames)
            if when > 2.0 and not out.any():
                dry_after_start += 1
    return dry_after_start


def test_zero_ms_keeps_only_the_room_a_device_needs_and_never_runs_dry():
    fifo = AdaptiveFifo(2, SR, 0.0, block=BLOCK)
    assert fifo.need == BLOCK + BLOCK // 2 + int(0.003 * SR)
    assert fifo.target == fifo.need and fifo.target * 1000 / SR == 18.0
    assert run(fifo, BLOCK) == 0 and fifo.underruns == 0 and fifo.resyncs == 0
    chosen = AdaptiveFifo(2, SR, 60.0, block=BLOCK)
    assert chosen.target == int(0.06 * SR)           # a bigger buffer chosen by hand still counts


def test_uneven_timing_and_big_device_blocks_play_without_gaps():
    for read, jitter in ((441, 5), (1024, 8), (1920, 12)):
        fifo = AdaptiveFifo(2, SR, 0.0, block=BLOCK)
        assert run(fifo, read, jitter_ms=jitter, seconds=10.0) == 0, read
        assert fifo.resyncs == 0 and fifo._max_read == max(read, BLOCK)


def test_a_device_that_runs_dry_while_sound_flows_gets_more_room():
    fifo = AdaptiveFifo(2, SR, 0.0, block=BLOCK)
    one = np.ones((BLOCK, 2), dtype=np.float32)
    for _ in range(4):
        fifo.write(one)
    fifo.read(BLOCK)
    before = fifo.need
    fifo.write(one)
    for _ in range(6):
        fifo.read(BLOCK)                             # it takes faster than the sound arrives
    assert fifo.underruns >= 1 and fifo.need > before


def test_every_output_gets_the_same_delay():
    p = Project(buffer_ms=0.0)
    runner = AudioRunner(p, Engine(p))
    usb = AdaptiveFifo(2, SR, 0.0, block=BLOCK)
    bt = AdaptiveFifo(2, SR, 0.0, block=BLOCK)
    bt._max_read = 1920                              # a Bluetooth speaker taking 40 ms at a time
    runner.fifos = {"usb": usb, "bt": bt}
    runner._share_target()
    bt._margin += int(0.01 * SR)                     # it needed 10 ms more room at some point
    runner._share_target()
    assert usb.target == bt.target == bt.need
    assert abs(runner.delay_ms() - (bt.need + 1920 / 2 + BLOCK) * 1000 / SR) < 1e-6
    p.buffer_ms = 150.0
    runner._share_target()
    assert usb.target == bt.target == int(0.15 * SR)


def test_old_setups_move_from_60_ms_to_0_and_chosen_values_stay():
    assert Project().buffer_ms == 0.0
    old = Project.from_json('{"buffer_ms": 60.0, "devices": []}')
    assert old.buffer_ms == 0.0
    kept = Project.from_json(Project(buffer_ms=60.0).to_json())
    assert kept.buffer_ms == 60.0
    path = os.path.join(tempfile.mkdtemp(), "s.json")
    Project(buffer_ms=35.0).save(path)
    assert Project.load(path).buffer_ms == 35.0


def test_clicking_a_speaker_keeps_the_sound_tab_open():
    from PySide6.QtWidgets import QApplication
    from fake_audio import FakeSoundDevice
    from speakerweave import backend
    from speakerweave.ui import state as state_module
    from speakerweave.ui import theme
    folder = tempfile.mkdtemp()
    state_module.config_dir = lambda: folder
    from speakerweave.ui.state import AppState
    from speakerweave.ui.window import MainWindow
    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    backend._sd = lambda: FakeSoundDevice([{"name": "Speakers", "outputs": 2}])
    state = AppState("")
    s = state.settings
    s.default_output = s.start_sound = s.simhub_link = s.check_updates = False
    s.tour_done = True
    win = MainWindow(state)
    dev = state.project.add_device("Speakers", 2)
    state.touch_streams()
    win.tabs.setCurrentWidget(win.sound_panel)
    state.select(dev.id, dev.speakers[1].id)
    assert win.tabs.currentWidget() is win.sound_panel
    win.tabs.setCurrentWidget(win.extras_panel)
    state.select(dev.id, dev.speakers[0].id)
    assert win.tabs.currentWidget() is win.extras_panel
    win.tabs.setCurrentWidget(win.device_panel)       # Speaker and Output still follow the click
    state.select(dev.id, dev.speakers[1].id)
    assert win.tabs.currentWidget() is win.speaker_panel
    state.select(dev.id, "")
    assert win.tabs.currentWidget() is win.device_panel
    win._quitting = True
    win.close()
    app.processEvents()
