"""The sound path: stereo spread on a 7.1 source, the Windows output following
the sound, settings from older versions, the sound check and the Errors page."""
import json
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from PySide6.QtWidgets import QApplication

from fake_audio import FakeSoundDevice
from speakerweave import backend, soundcheck
from speakerweave.engine import Engine
from speakerweave.model import Project
from speakerweave.settings import AppSettings
from speakerweave.ui import state as state_module
from speakerweave.ui import theme


def pump(app, seconds=0.0):
    end = time.monotonic() + seconds
    app.processEvents()
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def five_one_room():
    p = Project(mode="5.1", input_kind="loopback", input_name="CABLE Input [Loopback]", master_db=0.0)
    card = p.add_device("Card", 6)
    for spk, role in zip(card.speakers, ["FL", "FR", "FC", "LFE", "SL", "SR"]):
        p.set_role(spk, role)
    for spk in card.speakers:
        spk.lp_on = spk.hp_on = False
    p.bass_redirect = False
    return p, card


def test_stereo_on_a_71_source_is_spread_and_surround_goes_direct():
    p, card = five_one_room()
    eng = Engine(p)
    eng.configure(48000.0, 8)
    t = np.arange(4800) / 48000.0
    stereo = np.zeros((4800, 8))
    stereo[:, 0] = stereo[:, 1] = 0.3 * np.sin(2 * np.pi * 300 * t)
    for _ in range(3):
        out = eng.process(stereo)[card.id]
    assert not eng.surround_now
    assert np.abs(out[:, 4]).max() > 0.05 and np.abs(out[:, 5]).max() > 0.05   # rears get the music
    # a game sends a sound on the side left channel: from now on every channel goes direct
    game = stereo.copy()
    game[:, 6] = 0.3 * np.sin(2 * np.pi * 500 * t)          # 7.1 order: SL is channel 7
    eng.process(game)
    out = eng.process(game)[card.id]
    assert eng.surround_now
    music_in_rears = eng.process(stereo)[card.id]           # held for a few seconds
    assert eng.surround_now and np.abs(music_in_rears[:, 5]).max() < 1e-6
    assert np.abs(out[:, 4]).max() > 0.1
    assert set(eng.output_peaks) == {card.id} and len(eng.output_peaks[card.id]) == 6


def test_settings_from_older_versions_start_the_sound_by_themselves():
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "settings.json")
    with open(path, "w") as fh:
        json.dump({"start_sound": False, "theme": "ember"}, fh)
    s = AppSettings.load(path)
    assert s.start_sound and s.theme == "ember" and s.version == 2
    s.start_sound = False
    s.save(path)
    assert AppSettings.load(path).start_sound is False      # a later choice is kept


def test_sound_check_reports_setup_problems():
    from types import SimpleNamespace as NS
    p, card = five_one_room()
    p.input_name = "CABLE Input (VB-Audio Virtual Cable) [Loopback]"
    gone = p.add_device("USB3 TO HDMI", 2)
    outputs = [NS(name="Card", outputs=2, samplerate=48000.0),
               NS(name="CABLE Input (VB-Audio Virtual Cable)", outputs=2, samplerate=48000.0)]
    loops = [NS(name="CABLE Input (VB-Audio Virtual Cable) [Loopback]", inputs=2, samplerate=48000.0)]
    report = soundcheck.Report()
    soundcheck.check_setup(p, outputs, loops, report, "Card", running=True)
    titles = {f.title: f for f in report.findings}
    assert titles["Windows is not playing into the device SpeakerWeave listens to"].action == "claim"
    assert titles["USB3 TO HDMI is not connected"].action == f"untick:{gone.id}"
    assert titles["Card only has 2 channels open"].area == "surround"
    stereo = [f for f in report.findings if f.title.startswith("Windows sends only stereo")]
    assert stereo and stereo[0].action == "surround"
    report = soundcheck.Report()
    soundcheck.check_setup(p, outputs, loops, report, "Card", running=False)
    assert any(f.action == "start" for f in report.findings)
    assert not any(f.action == "claim" for f in report.findings)
    assert "[WARNING]" in report.text()


def test_full_sound_check_runs_on_pretend_devices():
    fake = FakeSoundDevice([{"name": "Card", "outputs": 6},
                            {"name": "Line in", "inputs": 2, "tones": {0: 440, 1: 660}}])
    fake.get_portaudio_version = lambda: (1, "pretend")
    backend._sd = lambda: fake
    p, card = five_one_room()
    p.input_kind, p.input_name = "device", "Line in"
    report = soundcheck.run(p)
    assert any(f.level == "ok" and "receives the sound" in f.title for f in report.findings), \
        report.text()
    assert not p.muted                                      # the real setup is never touched


def test_errors_page_lists_and_fixes():
    state_module.config_dir = lambda d=tempfile.mkdtemp(): d
    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    fake = FakeSoundDevice([{"name": "Card", "outputs": 6},
                            {"name": "Line in", "inputs": 2, "silent": True}])
    backend._sd = lambda: fake
    from speakerweave.ui.state import AppState
    from speakerweave.ui.window import MainWindow
    state = AppState("")
    state.settings.start_sound = False
    state.settings.default_output = False
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); state.settings.remote_port = s.getsockname()[1]
    s.close()
    win = MainWindow(state)
    win.show()
    pump(app, 0.3)
    p = state.project
    p.input_kind, p.input_name = "device", "Line in"
    card = p.add_device("Card", 6)
    gone = p.add_device("USB3 TO HDMI", 2)
    state.touch_streams()
    page = win.errors_page
    page.refresh()
    titles = [f.title for f in page.findings()]
    assert "USB3 TO HDMI is not connected" in titles and "The sound is stopped" in titles
    assert win.errors_btn.text() == "Errors"            # warnings only, no count
    page.do_action(f"untick:{gone.id}")
    assert not gone.enabled
    page.do_action("start")
    assert state.runner.running
    pump(app, 0.3)
    titles = [f.title for f in page.findings()]
    assert "The sound is stopped" not in titles
    # starting with a device that is switched off shows on the Errors page, not as a banner
    gone.enabled = True
    state.start()
    pump(app, 0.1)
    assert not win.banner.isVisible()
    state.stop()
    p.devices.remove(card)
    p.devices.remove(gone)
    state.touch_streams()
    page.refresh()
    assert any(f.title == "No sound output is ticked" for f in page.findings())
    assert win.errors_btn.text() == "Errors (1)"
    win.close()
