"""The speakers follow the Windows volume and mute of the device SpeakerWeave listens to
(volume keys, a mouse volume wheel, headset buttons)."""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from speakerweave.engine import Engine
from speakerweave.model import Project
from speakerweave.winvolume import VolumeFollower


class FakeDevice:
    """A Windows output whose volume the test turns."""
    def __init__(self):
        self.gain, self.muted, self.percent = 1.0, False, 100.0
        self.opened, self.closed = [], 0

    def open(self, _com, name):
        if name == "Missing":
            raise LookupError(name)
        self.opened.append(name)
        return self

    def read(self):
        return self.gain, self.muted, self.percent

    def close(self):
        self.closed += 1


def wait_for(check, seconds=2.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.01)
    return False


def test_the_follower_reports_volume_and_mute_changes():
    dev, seen = FakeDevice(), []
    follower = VolumeFollower(lambda *v: seen.append(v), open_device=dev.open)
    try:
        follower.follow("CABLE Input (VB-Audio Virtual Cable)")
        assert wait_for(lambda: follower.following)
        dev.gain, dev.percent = 0.1, 40.0                  # the mouse wheel turns it down
        assert wait_for(lambda: seen and seen[-1] == (0.1, False, 40.0))
        dev.muted = True
        assert wait_for(lambda: seen[-1][1] is True)
        follower.follow("")                                  # nothing to follow: full volume again
        assert wait_for(lambda: seen[-1] == (1.0, False, 100.0) and dev.closed == 1)
        follower.follow("Missing")                           # cannot be opened: full volume, retried
        time.sleep(0.15)
        assert follower.following == "" and follower.gain == 1.0
    finally:
        follower.stop()


def test_the_engine_plays_at_the_windows_volume():
    p = Project(mode="2.0", input_kind="device", input_name="Line in", master_db=0.0)
    tv = p.add_device("TV", 2)
    for spk in tv.speakers:
        spk.hp_on = spk.lp_on = False
    eng = Engine(p)
    eng.configure(48000.0, 2)
    block = np.full((480, 2), 0.5, dtype=np.float32)
    for _ in range(40):
        full = eng.process(block)[tv.id]
    eng.windows_gain = 0.1
    for _ in range(40):
        quiet = eng.process(block)[tv.id]
    assert abs(float(quiet[-1, 0]) / float(full[-1, 0]) - 0.1) < 0.01
    eng.windows_gain = 0.0                                   # Windows muted
    for _ in range(10):
        out = eng.process(block)[tv.id]
    assert np.abs(out[-100:]).max() < 1e-6


def test_the_app_follows_only_the_device_it_listens_to_and_can_be_switched_off():
    from PySide6.QtWidgets import QApplication
    from fake_audio import FakeSoundDevice
    from speakerweave import backend
    from speakerweave.ui import state as state_module
    folder = tempfile.mkdtemp()
    state_module.config_dir = lambda: folder
    QApplication.instance() or QApplication([])
    backend._sd = lambda: FakeSoundDevice([{"name": "TV", "outputs": 2}])
    from speakerweave.ui.state import AppState
    state = AppState("")
    dev = FakeDevice()
    state.winvol = VolumeFollower(state._windows_volume, open_device=dev.open)
    try:
        state.project.input_kind, state.project.input_name = "loopback", "CABLE Input [Loopback]"
        state.follow_windows_volume()
        assert state.windows_volume_device() == "CABLE Input"
        assert wait_for(lambda: dev.opened == ["CABLE Input"])
        dev.gain, dev.percent = 0.25, 55.0
        assert wait_for(lambda: state.engine.windows_gain == 0.25)
        assert wait_for(lambda: state.windows_volume_text() == "Windows 55%")
        dev.muted = True
        assert wait_for(lambda: state.engine.windows_gain == 0.0)
        assert state.windows_volume_text() == "Windows muted"
        state.settings.follow_windows_volume = False
        state.follow_windows_volume()
        assert state.engine.windows_gain == 1.0 and state.windows_volume_text() == ""
        state.settings.follow_windows_volume = True
        state.project.input_kind = "test"                    # the test signal is not Windows' sound
        state.follow_windows_volume()
        assert state.engine.windows_gain == 1.0
    finally:
        state.winvol.stop()
