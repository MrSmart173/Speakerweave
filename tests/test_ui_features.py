"""The Controls and Settings pages, actions, the speaker library in the window,
test sounds and the Bluetooth window, clicked through off screen."""
import os
import sys
import tempfile
import time
import urllib.request

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from fake_audio import FakeSoundDevice
from speakerweave import backend
from speakerweave.model import Project
from speakerweave.ui import state as state_module
from speakerweave.ui import theme

_SCRATCH = tempfile.mkdtemp()
state_module.config_dir = lambda: _SCRATCH

from speakerweave.ui.state import AppState            # noqa: E402
from speakerweave.ui.window import MainWindow, ROLE_KEY  # noqa: E402


def pump(app, seconds=0.0):
    end = time.monotonic() + seconds
    app.processEvents()
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def tree_item(win, kind, name):
    def walk(item):
        data = item.data(0, ROLE_KEY)
        if data and data[0] == kind and name in item.text(0):
            return item
        for i in range(item.childCount()):
            found = walk(item.child(i))
            if found:
                return found
        return None
    for i in range(win.tree.topLevelItemCount()):
        found = walk(win.tree.topLevelItem(i))
        if found:
            return found
    return None


def free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_new_pages_and_actions():
    import sdl2
    state_module.config_dir = lambda d=tempfile.mkdtemp(): d   # a fresh, private settings folder
    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    fake = FakeSoundDevice([
        {"name": "LG TV SSCR2 (NVIDIA High Definition Audio)", "outputs": 2},
        {"name": "Speakers (Realtek(R) Audio)", "outputs": 2, "ppm": 80},
        {"name": "CABLE Input (VB-Audio Virtual Cable)", "outputs": 8},
        {"name": "Mixer", "inputs": 2, "silent": True},
    ])
    backend._sd = lambda: fake
    state = AppState("")
    state.settings.remote_port = free_port()
    win = MainWindow(state)
    win.show()
    pump(app, 0.3)
    proj = state.project

    # recognised outputs get their preset, virtual devices are refused
    tree_item(win, "new", "LG TV").setCheckState(0, Qt.Checked)
    pump(app)
    tv = proj.devices[0]
    assert tv.model == "tv" and all(s.hp_on and s.hp_freq == 100 for s in tv.speakers)
    tree_item(win, "new", "CABLE Input").setCheckState(0, Qt.Checked)
    pump(app, 0.1)
    assert len(proj.devices) == 1 and tree_item(win, "new", "CABLE Input") is not None
    tree_item(win, "new", "Speakers (Realtek").setCheckState(0, Qt.Checked)
    pump(app)
    card = proj.devices[1]
    assert card.model == "pc_output" and card.kind == "external"

    # pick the speakers on the jack from the library
    state.select(card.id, "")
    pump(app)
    dp = win.device_panel
    assert "Choose which" in dp.recognised.text()
    dp.model.setCurrentIndex(dp.model.findData("yamaha_hs5"))
    dp._model_chosen(0)
    assert card.model == "yamaha_hs5" and all(s.hp_freq == 55 for s in card.speakers)
    assert "woofer size" in dp.model_note.text()

    # actions, the way keys, buttons and links trigger them
    run = win.actions.run
    db = proj.master_db
    run("volume_up")
    assert proj.master_db == db + 2 and win.master.value() == round(db + 2)
    run("volume_down")
    run("mute")
    assert proj.muted and win.master_text.text() == "Muted"
    run("volume_up")                                    # turning it up unmutes
    assert not proj.muted
    mode = (proj.mode, proj.surround_rear)
    run("next_mode")
    assert (proj.mode, proj.surround_rear) != mode
    assert win.mode.currentData() == proj.mode + (" rear" if proj.surround_rear else "")
    run("prev_mode")
    assert (proj.mode, proj.surround_rear) == mode
    bass = proj.bass_redirect
    run("toggle_bass")
    assert proj.bass_redirect != bass
    run(f"mute_output:{tv.id}")
    assert all(s.mute for s in tv.speakers)
    run(f"mute_output:{tv.id}")
    assert not any(s.mute for s in tv.speakers)
    saved = os.path.join(_SCRATCH, "racing.json")
    other = Project(mode="2.1")
    other.add_device("Speakers (Realtek(R) Audio)", 2)
    other.save(saved)
    run("slot_1")
    assert proj is state.project                        # empty slot: nothing changes
    win.controls_page._set_slot(0, saved)
    run("slot_1")
    assert state.project.mode == "2.1"
    proj = state.project

    # a button on a wheel triggers an action
    index = sdl2.SDL_JoystickAttachVirtual(sdl2.SDL_JOYSTICK_TYPE_WHEEL, 2, 24, 0)
    try:
        info = next(d for d in win.pads.devices() if d.buttons == 24)
        page = win.controls_page
        page.bind("mute", {"kind": "pad", "guid": info.guid, "device": info.name, "input": "b5",
                           "text": f"Button 6 on {info.name}"})
        joy = next(j for j, *_r in win.pads._open.values() if sdl2.SDL_JoystickNumButtons(j) == 24)
        win._poll_pads()
        sdl2.SDL_JoystickSetVirtualButton(joy, 5, 1)
        win._poll_pads()
        assert proj.muted
        sdl2.SDL_JoystickSetVirtualButton(joy, 5, 0)
        win._poll_pads()
        sdl2.SDL_JoystickSetVirtualButton(joy, 5, 1)
        win._poll_pads()
        assert not proj.muted
    finally:
        sdl2.SDL_JoystickDetachVirtual(index)

    # a key (outside Windows it works while the window is active)
    page.bind("volume_down", {"kind": "key", "vk": 0, "mods": 0, "qt": "F9", "text": "F9"})
    assert win.hotkeys.failed == [] and len(win.hotkeys._shortcuts) == 1
    db = proj.master_db
    win.hotkeys._shortcuts[0].activated.emit()
    assert proj.master_db == db - 2
    assert any(b["action"] == "mute" for b in state.settings.bindings)

    # Stream Deck links
    page.remote_on.setChecked(True)
    assert win.remote.running
    with urllib.request.urlopen(win.remote.url("toggle_upmix"), timeout=3) as reply:
        assert reply.status == 200
    upmix = proj.upmix
    pump(app, 0.2)
    assert proj.upmix != upmix
    page.remote_on.setChecked(False)
    assert win.remote.running                   # the SimHub link still answers
    state.settings.simhub_link = False
    win.apply_remote()
    assert not win.remote.running

    # Settings page
    win.show_page(2)
    sp = win.settings_page
    assert not sp.start_windows.isEnabled() and sp.windows_hint.isVisible()
    sp.meters.setChecked(False)
    assert state.settings.show_meters is False
    sp.close_tray.setChecked(False)
    win.show_page(0)
    assert win.nav.checkedId() == 0

    # a test sound starts the sound on its own and stops it again, even with a silent source
    proj.input_kind, proj.input_name = "device", "Mixer"
    assert not state.runner.running
    spk = proj.devices[0].speakers[0]
    state.identify(spk.id, "noise")
    assert state.runner.running
    pump(app, 1.0)
    played = np.concatenate(fake.streams["Speakers (Realtek(R) Audio)"].recorded)
    assert np.abs(played[:, 0]).max() > 0.01 and np.abs(played[:, 1]).max() == 0
    pump(app, 1.6)
    assert not state.runner.running

    # right click menu choices
    win.map._set_role(spk, "FC")
    assert spk.role == "FC"
    win.map._toggle(spk, "solo")
    assert spk.solo

    # Bluetooth window (outside Windows it explains it cannot list)
    from speakerweave.ui.bluetooth_dialog import BluetoothDialog
    dialog = BluetoothDialog(win)
    dialog.show()
    pump(app, 0.5)
    assert "only available on Windows" in dialog.status.text() or "paired" in dialog.status.text()
    dialog.close()
    win.close()


def test_mode_list_side_rear_and_custom_positions():
    state_module.config_dir = lambda d=tempfile.mkdtemp(): d
    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    fake = FakeSoundDevice([
        {"name": "Speakers (Realtek(R) Audio)", "outputs": 6},
        {"name": "Mixer", "inputs": 2, "silent": True},
    ])
    backend._sd = lambda: fake
    state = AppState("")
    state.settings.remote_port = free_port()
    win = MainWindow(state)
    win.show()
    pump(app, 0.2)
    proj = state.project
    texts = [win.mode.itemText(i) for i in range(win.mode.count())]
    assert any("5.1" in t and "RL RR" in t for t in texts)
    assert any("5.1" in t and "SL SR" in t for t in texts)
    assert texts[-1] == "Custom..."

    # 5.1 with the surround pair behind you
    win.mode.setCurrentIndex(win.mode.findData("5.1 rear"))
    win._mode_changed(0)
    assert proj.mode == "5.1" and proj.surround_rear
    assert proj.mode_roles() == ["FL", "FR", "FC", "LFE", "BL", "BR"]

    # the positions picker: front pair, rear pair and two subwoofers
    from speakerweave.ui.positions_dialog import PositionsDialog
    dialog = PositionsDialog(win, proj)
    assert dialog.buttons["BL"].isChecked() and not dialog.buttons["SL"].isChecked()
    dialog.buttons["FC"].setChecked(False)
    dialog.subs.setValue(2)
    assert "Custom" in dialog.summary.text()
    for button in dialog.buttons.values():
        button.setChecked(False)
    assert not dialog.box.button(dialog.box.StandardButton.Ok).isEnabled()
    for role in ("FL", "FR", "BL", "BR"):
        dialog.buttons[role].setChecked(True)
    assert dialog.roles() == ["FL", "FR", "BL", "BR", "LFE", "LFE2"]
    win.apply_positions(dialog.roles())
    pump(app, 0.1)
    assert proj.mode == "custom" and proj.mode_roles() == ["FL", "FR", "LFE", "LFE2", "BL", "BR"]
    assert win.mode.currentIndex() == win.mode.count() - 1
    assert "Custom" in win.mode.currentText()
    # a choice that matches a standard mode becomes that mode
    win.apply_positions(["FL", "FR", "SL", "SR", "LFE"])
    assert (proj.mode, proj.surround_rear) == ("4.1", False)
    assert win.mode.currentData() == "4.1" and win.mode.itemText(win.mode.count() - 1) == "Custom..."
    dialog.close()
    win.close()


def test_setups_are_saved_in_documents_not_where_the_app_is_installed(monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from speakerweave.settings import AppSettings
    from speakerweave.ui import state as state_module
    docs = tempfile.mkdtemp()
    monkeypatch.setattr(state_module, "documents_dir", lambda: docs)
    settings = AppSettings()
    first = state_module.setups_dir(settings)
    assert first == os.path.join(docs, "SpeakerWeave setups") and os.path.isdir(first)
    other = tempfile.mkdtemp()
    state_module.remember_setup_folder(settings, os.path.join(other, "Desk.json"))
    assert state_module.setups_dir(settings) == other               # the folder used last time
    settings.last_setup_folder = os.path.join(other, "gone")
    assert state_module.setups_dir(settings) == first               # unless it is gone

    app = QApplication.instance() or QApplication([])
    backend._sd = lambda: FakeSoundDevice([{"name": "Speakers", "outputs": 2}])
    state = AppState("")
    state.settings.default_output = state.settings.start_sound = state.settings.simhub_link = False
    state.settings.tour_done = True
    state.settings.last_setup_folder = ""
    win = MainWindow(state)
    asked = []

    def fake_save(parent, title, start, kinds):
        asked.append(start)
        return os.path.join(other, "Elis Desk test 1"), kinds
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(fake_save))
    win._save_setup()
    assert asked[0] == os.path.join(first, "My speakers.json")
    assert os.path.isfile(os.path.join(other, "Elis Desk test 1.json"))     # .json added
    assert state.settings.last_setup_folder == other
    win._quitting = True
    win.close()
    app.processEvents()


def test_a_folder_windows_will_not_let_us_write_to_is_never_used(monkeypatch):
    """Program Files, or Documents behind Windows' ransomware protection: the Save window
    does not start there, and a save that Windows refuses lands in SpeakerWeave's own folder."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from speakerweave.model import Project
    from speakerweave.settings import AppSettings
    from speakerweave.ui import state as state_module
    from speakerweave.ui.state import AppState
    from speakerweave.ui.window import MainWindow

    docs, locked, own = tempfile.mkdtemp(), tempfile.mkdtemp(), tempfile.mkdtemp()
    monkeypatch.setattr(state_module, "documents_dir", lambda: docs)
    monkeypatch.setattr(state_module, "config_dir", lambda: own)
    real_can_write = state_module.can_write
    blocked = {locked, os.path.join(docs, "SpeakerWeave setups")}
    monkeypatch.setattr(state_module, "can_write",
                        lambda folder: folder not in blocked and real_can_write(folder))
    settings = AppSettings(last_setup_folder=locked)
    assert state_module.setups_dir(settings) == os.path.join(own, "Setups")    # neither is used
    state_module.remember_setup_folder(settings, os.path.join(locked, "x.json"))
    assert settings.last_setup_folder == locked and state_module.setups_dir(settings) != locked

    app = QApplication.instance() or QApplication([])
    backend._sd = lambda: FakeSoundDevice([{"name": "Speakers", "outputs": 2}])
    state = AppState("")
    state.settings.default_output = state.settings.start_sound = state.settings.simhub_link = False
    state.settings.tour_done = True
    win = MainWindow(state)
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a: (os.path.join(locked, "Desk.json"), "")))
    told = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: told.append(a[2])))
    real_save = Project.save

    def refusing_save(self, path):
        if os.path.dirname(path) == locked:
            raise PermissionError(13, "Access is denied", path)
        real_save(self, path)
    monkeypatch.setattr(Project, "save", refusing_save)
    win._save_setup()
    saved = os.path.join(own, "Setups", "Desk.json")
    assert os.path.isfile(saved) and "saved in" in told[0]
    assert state.settings.last_setup_folder == os.path.join(own, "Setups")
    win._quitting = True
    win.close()
    app.processEvents()
