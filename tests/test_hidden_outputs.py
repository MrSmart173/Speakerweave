"""Hiding outputs in the list, and being told when a hidden one is plugged in again."""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from fake_audio import FakeSoundDevice
from speakerweave import backend, hidden
from speakerweave.model import Project
from speakerweave.settings import AppSettings
from speakerweave.ui import state as state_module
from speakerweave.ui import theme

_SCRATCH = tempfile.mkdtemp()
state_module.config_dir = lambda: _SCRATCH


def pump(app, seconds=0.0):
    end = time.monotonic() + seconds
    app.processEvents()
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def test_a_hidden_output_leaves_every_setup_and_comes_back_as_it_was():
    settings, p = AppSettings(), Project()
    dock = p.add_device("USB3 TO HDMI", 2)
    dock.x, dock.label = 1.7, "Dock"
    dock.speakers[0].gain_db = -4.0
    tv = p.add_device("LG TV", 2)
    hidden.hide(settings, p, "USB3 TO HDMI", present=["LG TV"])
    assert [d.name for d in p.devices] == ["LG TV"]
    entry = settings.hidden_outputs["USB3 TO HDMI"]
    assert entry["device"]["label"] == "Dock" and entry["enabled"] and not entry["seen"]

    other = Project()                                   # another setup with the same output
    other.add_device("USB3 TO HDMI", 2).x = -2.0
    assert hidden.pull_hidden(settings, other) == ["USB3 TO HDMI"] and other.devices == []
    assert settings.hidden_outputs["USB3 TO HDMI"]["device"]["x"] == -2.0   # the latest is kept

    again = AppSettings.load(_save(settings))           # survives the settings file
    assert again.hidden_outputs["USB3 TO HDMI"]["device"]["x"] == -2.0
    dev = hidden.unhide(settings, p, "USB3 TO HDMI", activate=True)
    assert dev is not None and dev.enabled and dev.x == -2.0 and dev in p.devices
    assert "USB3 TO HDMI" not in settings.hidden_outputs and tv in p.devices

    hidden.hide(settings, p, "Speakers (Spare)", present=["Speakers (Spare)"])   # never in the setup
    assert settings.hidden_outputs["Speakers (Spare)"]["seen"]
    assert hidden.unhide(settings, p, "Speakers (Spare)") is None


def _save(settings):
    path = os.path.join(tempfile.mkdtemp(), "settings.json")
    settings.save(path)
    return path


def test_only_a_return_is_announced_and_quiet_ones_never():
    settings, p = AppSettings(), Project()
    hidden.hide(settings, p, "Dock", present=[])
    hidden.hide(settings, p, "Old TV", present=[])
    assert hidden.found_again(settings, []) == []
    assert hidden.found_again(settings, ["Dock (USB Audio)"]) == ["Dock"]     # names may be longer
    assert hidden.found_again(settings, ["Dock (USB Audio)"]) == []           # still there: once
    settings.hidden_outputs["Old TV"]["quiet"] = True
    assert hidden.found_again(settings, ["Old TV"]) == []
    hidden.found_again(settings, [])                                         # unplugged
    assert hidden.found_again(settings, ["Dock"]) == ["Dock"]                 # and back: again


def window(outputs):
    from speakerweave.ui.state import AppState
    from speakerweave.ui.window import MainWindow
    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    backend._sd = lambda: FakeSoundDevice(outputs)
    state = AppState("")
    s = state.settings
    s.default_output = s.start_sound = s.simhub_link = s.check_updates = s.watch_devices = False
    s.tour_done = True
    s.hidden_outputs = {}
    state.project = Project(input_kind="test")
    state.engine.project = state.runner.project = state.rgb.project = state.project
    win = MainWindow(state)
    win.resize(1300, 850)
    win.show()
    pump(app, 0.4)
    return app, state, win


def folder(win):
    for i in range(win.tree.topLevelItemCount()):
        item = win.tree.topLevelItem(i)
        data = item.data(0, Qt.UserRole)
        if data and data[0] == "hiddenfolder":
            return item, i == win.tree.topLevelItemCount() - 1
    return None, False


def test_hide_flash_and_the_three_answers():
    app, state, win = window([{"name": "Speakers", "outputs": 2}, {"name": "Monitor", "outputs": 2}])
    p = state.project
    dock = p.add_device("USB3 TO HDMI", 2)            # in the setup, but not plugged in
    state.touch_streams()
    pump(app, 0.1)
    assert folder(win)[0] is None
    win.hide_output("USB3 TO HDMI")
    win.hide_output("Monitor")                       # plugged in, never used
    pump(app, 0.1)
    head, at_bottom = folder(win)
    assert head is not None and at_bottom and head.text(0) == "Hidden by user (2)"
    assert dock not in p.devices
    texts = [head.child(i).text(0) for i in range(head.childCount())]
    assert any("not connected" in t for t in texts) and len(texts) == 2
    spare = [win.tree.topLevelItem(i).text(0) for i in range(win.tree.topLevelItemCount())]
    assert not any("Monitor" == t for t in spare)

    # the dock is plugged in: its folder flashes and the note asks what to do
    backend._sd = lambda: FakeSoundDevice([{"name": "Speakers", "outputs": 2},
                                           {"name": "Monitor", "outputs": 2},
                                           {"name": "USB3 TO HDMI", "outputs": 2}])
    state.scan_devices()
    pump(app, 0.6)
    assert win._found_queue == ["USB3 TO HDMI"] and win._flash_timer.isActive()
    note = win._found_note
    assert note is not None and note.isVisible() and win.rect().contains(note.geometry())
    assert note.layout().itemAt(0).widget().text() == "This device has been found again"
    QTest.mouseClick(note.activate_btn, Qt.LeftButton)
    pump(app, 0.2)
    back = next(d for d in p.devices if d.name == "USB3 TO HDMI")
    assert back.enabled and back.id == dock.id and not win._flash_timer.isActive()
    assert "USB3 TO HDMI" not in state.settings.hidden_outputs

    # hidden again, unplugged, plugged in: Ignore keeps it hidden but asks next time
    win.hide_output("USB3 TO HDMI")
    for plugged in (False, True):
        backend._sd = lambda plugged=plugged: FakeSoundDevice(
            [{"name": "Speakers", "outputs": 2}] + ([{"name": "USB3 TO HDMI", "outputs": 2}] if plugged else []))
        state.scan_devices()
        pump(app, 0.4)
    QTest.mouseClick(win._found_note.ignore_btn, Qt.LeftButton)
    pump(app, 0.2)
    entry = state.settings.hidden_outputs["USB3 TO HDMI"]
    assert not entry["quiet"] and win._found_note is None

    # Ignore and don't show again: never asked again
    for plugged in (False, True):
        backend._sd = lambda plugged=plugged: FakeSoundDevice(
            [{"name": "Speakers", "outputs": 2}] + ([{"name": "USB3 TO HDMI", "outputs": 2}] if plugged else []))
        state.scan_devices()
        pump(app, 0.4)
    QTest.mouseClick(win._found_note.never_btn, Qt.LeftButton)
    pump(app, 0.2)
    assert state.settings.hidden_outputs["USB3 TO HDMI"]["quiet"]
    for plugged in (False, True):
        backend._sd = lambda plugged=plugged: FakeSoundDevice(
            [{"name": "Speakers", "outputs": 2}] + ([{"name": "USB3 TO HDMI", "outputs": 2}] if plugged else []))
        state.scan_devices()
        pump(app, 0.4)
    assert win._found_note is None and win._found_queue == []

    # right click "Show this output again" puts the spare monitor back with the others
    win.unhide_output("Monitor")
    assert "Monitor" not in state.settings.hidden_outputs
    win._quitting = True
    win.close()
    pump(app, 0.1)
