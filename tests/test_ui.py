"""Clicks through the window off screen, with pretend sound cards behind it."""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from fake_audio import FakeSoundDevice
from speakerweave import backend
from speakerweave.model import speaker_position
from speakerweave.ui import theme
from speakerweave.ui import state as state_module
from speakerweave.ui.state import AppState
from speakerweave.ui.window import MainWindow, ROLE_KEY

_SCRATCH = tempfile.mkdtemp()
state_module.config_dir = lambda: _SCRATCH      # never touch the real saved setup


def make_window():
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("SpeakerWeaveTest")
    theme.apply(app)
    fake = FakeSoundDevice([
        {"name": "TV left", "outputs": 2, "ppm": -200},
        {"name": "TV middle", "outputs": 2},
        {"name": "TV right", "outputs": 2, "ppm": 200},
        {"name": "Amp", "outputs": 6},
        {"name": "Mixer", "inputs": 8, "tones": {0: 300.0, 1: 400.0}},
    ])
    backend._sd = lambda: fake
    state = AppState("")
    win = MainWindow(state)
    win.show()
    for _ in range(5):
        app.processEvents()
    return app, state, win, fake


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


def test_whole_window():
    state_module.config_dir = lambda d=tempfile.mkdtemp(): d   # a fresh, private settings folder
    app, state, win, fake = make_window()
    proj = state.project
    assert [o.name for o in state.outputs] == ["TV left", "TV middle", "TV right", "Amp"]
    assert win.input.count() == 2                       # test signal + Mixer

    # tick the outputs in the list
    for name in ("TV left", "TV middle", "TV right", "Amp"):
        tree_item(win, "new", name).setCheckState(0, Qt.Checked)
        pump(app)
    assert [d.name for d in proj.devices] == ["TV left", "TV middle", "TV right", "Amp"]
    assert len(proj.devices[3].speakers) == 6
    assert tree_item(win, "new", "TV left") is None

    # choose 7.1 and a speaker, make it the subwoofer through the panel
    win.mode.setCurrentIndex(win.mode.findData("7.1"))
    win._mode_changed(0)
    amp = proj.devices[3]
    sub = amp.speakers[3]
    win._tree_clicked(tree_item(win, "spk", "Sub"), 0)
    pump(app)
    assert state.sel_spk == sub.id and win.tabs.currentWidget() is win.speaker_panel
    panel = win.speaker_panel
    assert panel.role.currentData() == "LFE" and panel.hp_on.isChecked() and panel.lp_freq.value() == 75
    panel.role.setCurrentIndex(panel.role.findData("FC"))
    panel._role_changed(0)
    assert sub.role == "FC" and not sub.lp_on and not panel.lp_on.isChecked()
    panel.role.setCurrentIndex(panel.role.findData("LFE"))
    panel._role_changed(0)
    assert sub.lp_on and sub.lp_freq == 75 and panel.lp_on.isChecked()
    panel.lp_freq.setValue(60.0)
    assert sub.lp_freq == 60.0 and "60 Hz" in panel.range_text.text()
    panel.gain.slider.setValue(-12)                     # slider steps are half a dB
    assert sub.gain_db == -6.0
    panel.mute.click()
    assert sub.mute
    panel.mute.click()

    def choose_type(key):
        panel.speaker_type.setCurrentIndex(panel.speaker_type.findData(key))
        panel._type_chosen(0)

    choose_type("full")
    assert not sub.hp_on and not sub.lp_on and sub.range_preset == "full"
    choose_type("shaker")
    assert (sub.hp_freq, sub.lp_freq, sub.lp_slope) == (10, 80, 48)
    assert "ButtKicker" in panel.type_hint.text()
    panel.lp_freq.setValue(95.0)                        # changed by hand
    assert panel.speaker_type.currentData() == "" and "by hand" in panel.type_hint.text()
    choose_type("sub")
    assert sub.hp_freq == 10 and sub.lp_freq == 75 and panel.speaker_type.currentData() == "sub"

    # equaliser: drag a dot, scroll for sharpness, add and remove a band
    graph = panel.graph
    graph.resize(420, 220)
    band = sub.eq[2]
    start = graph._band_pos(band).toPoint()
    QTest.mousePress(graph, Qt.LeftButton, Qt.NoModifier, start)
    target = QPoint(int(graph.fx(60.0)), int(graph.gy(6.0)))
    QTest.mouseMove(graph, target)
    QTest.mouseRelease(graph, Qt.LeftButton, Qt.NoModifier, target)
    assert abs(band.gain_db - 6.0) < 0.6 and 55 < band.freq < 66, (band.gain_db, band.freq)
    assert panel.band_gain.value() == band.gain_db and graph.selected == 2
    panel.band_q.setValue(3.0)
    assert band.q == 3.0
    n = len(sub.eq)
    panel.eq_add.click()
    assert len(sub.eq) == n + 1
    panel.eq_del.click()
    assert len(sub.eq) == n
    panel.eq_copy.click()
    other = amp.speakers[0]
    state.select(amp.id, other.id)
    pump(app)
    panel.eq_paste.click()
    assert other.eq[2].gain_db == band.gain_db and other.lp_on
    panel.eq_flat.click()
    panel.speaker_type.setCurrentIndex(panel.speaker_type.findData("full"))
    panel._type_chosen(0)
    assert all(b.gain_db == 0 for b in other.eq) and not other.lp_on

    # room map: drag the left TV, it follows the mouse and turns to face the listener
    left = proj.devices[0]
    m = win.map
    before = (left.x, left.y)
    p0 = m.to_px(left.x, left.y).toPoint()
    QTest.mousePress(m, Qt.LeftButton, Qt.NoModifier, p0)
    p1 = m.to_px(-1.5, 0.0).toPoint()
    QTest.mouseMove(m, p1)
    QTest.mouseRelease(m, Qt.LeftButton, Qt.NoModifier, p1)
    assert (left.x, left.y) != before and abs(left.x + 1.5) < 0.1 and abs(left.y) < 0.1
    assert left.rotation < -45, left.rotation
    assert state.sel_dev == left.id and win.tabs.currentWidget() is win.device_panel
    assert abs(win.device_panel.x.value() - left.x) < 0.01

    # drag the rim of one speaker sideways: the unit gets wider, the numbers follow
    mid = proj.devices[1]
    state.select("", "")
    mid.x, mid.y, mid.width, mid.rotation = 0.0, -1.5, 1.0, 0.0
    state.touch_layout()
    lsp, rsp = mid.speakers
    centre = m.to_px(*speaker_position(mid, lsp))
    rim = QPoint(int(centre.x() - 15), int(centre.y()))            # just left of the badge
    assert m._hit(rim)[0] == "edge_x"
    QTest.mouseMove(m, rim)
    assert m._hover == (lsp.id, "x")
    QTest.mousePress(m, Qt.LeftButton, Qt.NoModifier, rim)
    goal = m.to_px(-1.0, -1.0).toPoint() - QPoint(15, 0)           # also pulled downwards
    QTest.mouseMove(m, goal)
    QTest.mouseRelease(m, Qt.LeftButton, Qt.NoModifier, goal)
    lx, ly = speaker_position(mid, lsp)
    assert abs(lx + 1.0) < 0.06 and abs(ly + 1.5) < 0.01, (lx, ly)  # sideways only
    rx, ry = speaker_position(mid, rsp)
    assert abs(rx - 0.5) < 0.01 and abs(ry + 1.5) < 0.01            # other end stayed
    assert state.sel_dev == mid.id and state.sel_spk == ""
    assert win.tabs.currentWidget() is win.device_panel
    assert abs(win.device_panel.width_m.value() - mid.width) < 0.006 and mid.width > 1.4
    assert abs(win.device_panel.x.value() - mid.x) < 0.006

    # mirror: now both ends move, front to back the same way, sideways opposite
    win.mirror_btn.click()
    assert proj.mirror
    mid.x, mid.y, mid.width, mid.rotation = 0.0, -1.5, 1.0, 0.0
    state.touch_layout()
    centre = m.to_px(*speaker_position(mid, rsp))
    rim = QPoint(int(centre.x()), int(centre.y() + 15))            # just below the badge
    assert m._hit(rim)[0] == "edge_y"
    QTest.mousePress(m, Qt.LeftButton, Qt.NoModifier, rim)
    goal = m.to_px(0.5, -1.0).toPoint() + QPoint(0, 15)
    QTest.mouseMove(m, goal)
    QTest.mouseRelease(m, Qt.LeftButton, Qt.NoModifier, goal)
    assert abs(mid.y + 1.0) < 0.06 and abs(mid.rotation) < 0.5 and abs(mid.width - 1.0) < 0.01
    assert abs(win.device_panel.y.value() - mid.y) < 0.006
    state.select(mid.id, rsp.id)
    pump(app)
    sp = win.speaker_panel
    assert abs(sp.pos_x.value() - 0.5) < 0.006 and "Mirror is on" in sp.pos_hint.text()
    sp.pos_x.setValue(0.8)                                          # typed in the side panel
    assert abs(mid.width - 1.6) < 0.01 and abs(mid.x) < 0.01
    win.mirror_btn.click()
    assert not proj.mirror
    sp.pos_x.setValue(1.0)
    assert abs(mid.width - 1.8) < 0.01 and abs(mid.x - 0.1) < 0.01

    # aux out: the speakers come loose from the unit and can be dragged alone
    state.select(left.id, "")
    pump(app)
    dp = win.device_panel
    dp.kind.setCurrentIndex(dp.kind.findData("external"))
    dp._kind_changed(0)
    spk = left.speakers[0]
    sx, sy = speaker_position(left, spk)
    p0 = m.to_px(sx, sy).toPoint()
    QTest.mousePress(m, Qt.LeftButton, Qt.NoModifier, p0)
    p1 = m.to_px(-2.0, 1.5).toPoint()
    QTest.mouseMove(m, p1)
    QTest.mouseRelease(m, Qt.LeftButton, Qt.NoModifier, p1)
    assert abs(spk.x + 2.0) < 0.1 and abs(spk.y - 1.5) < 0.1
    assert abs(left.x + 1.5) < 0.1                      # the unit itself stayed

    # roles from positions, delays from distances
    win.assign_btn.click()
    assert spk.role in ("BL", "SL"), spk.role
    win.align_btn.click()
    assert max(s.delay_ms for _, s in proj.all_speakers()) > 0

    # run with the pretend sound cards, test signal first, then the mixer input
    win.start_btn.click()
    pump(app, 1.5)
    assert state.runner.running and not win.banner.isVisible(), win.banner.text()
    assert win.start_btn.text() == "Stop"
    assert max(win.map.levels.values()) > 0.1
    assert "Running" in win.run_label.text()
    state.identify(sub.id)
    assert state.engine.identifying
    state.identify(sub.id, "sweep")
    win.input.setCurrentIndex(1)
    win._input_changed(1)
    pump(app, 1.5)
    assert state.runner.running and proj.input_kind == "device"
    assert state.engine.src_channels == 8
    win.sound_panel.buffer.setValue(80)
    pump(app, 1.0)
    assert state.runner.running and "TV middle" in win.sound_panel.sync.text()
    win.master.setValue(-20)
    assert proj.master_db == -20
    win.start_btn.click()
    pump(app, 0.2)
    assert not state.runner.running and win.start_btn.text() == "Start"

    # switch an output off and remove one
    tree_item(win, "dev", "Amp").setCheckState(0, Qt.Unchecked)
    pump(app)
    assert not amp.enabled
    state.select(amp.id, "")
    win.device_panel.remove.click()
    pump(app)
    assert len(proj.devices) == 3 and tree_item(win, "new", "Amp") is not None

    # updates: found in the background, a newer release becomes a notice on the Errors
    # page and a note by the Errors button. Asked for by hand, it opens the dialog.
    from speakerweave import release, updates
    offered = []
    win.updater.offer = offered.append
    old_repo, old_check = release.UPDATE_REPO, updates.check
    try:
        release.UPDATE_REPO = "someone/speakerweave"
        state.settings.update_note_seen = ""
        updates.check = lambda: updates.ReleaseInfo("v9.9.9", "https://x/Setup.exe",
                                                    notes="Faster and better.")
        win.updater.check(manual=False)
        pump(app, 0.8)
        assert offered == [] and win.updater.info.version == "v9.9.9"
        note = win._update_note
        assert note is not None and note.isVisible() and "9.9.9" in note.findChildren(QLabel)[0].text()
        cards = [f for f in win.errors_page.findings() if f.level == "notice"]
        assert len(cards) == 1 and cards[0].title == "SpeakerWeave 9.9.9 is available"
        assert cards[0].action in ("update", "update_page")
        assert "Faster and better." in cards[0].detail
        assert win.errors_btn.text() == "Errors (1 new)" or "Errors (" in win.errors_btn.text()
        note.later_btn.click()
        assert state.settings.update_note_seen == "9.9.9" and win._update_note is None
        win.updater.check(manual=False)                  # found again: the note stays away
        pump(app, 0.5)
        assert win._update_note is None and win.updater.info is not None
        win.updater.check(manual=True)
        pump(app, 0.5)
        assert [i.version for i in offered] == ["v9.9.9"]
        updates.check = lambda: None                     # installed: the notice goes
        win.updater.check(manual=False)
        pump(app, 0.8)
        assert win.updater.info is None and not win.updater._busy
        assert not [f for f in win.errors_page.findings() if f.level == "notice"]
    finally:
        release.UPDATE_REPO, updates.check = old_repo, old_check
    win.settings_page.updates_box.click()
    assert state.settings.check_updates is False

    # the setup survives a restart
    state.save_now()
    again = AppState("")
    assert again.project.to_json() == proj.to_json()
    win.close()


def test_lights_follow_the_speakers():
    from speakerweave.lights import RGBDevice, RGBZone
    from speakerweave.rgb import RgbController
    from speakerweave.model import Project

    sent = {}

    class FakeConnection:
        changed = False
        devices = [RGBDevice(0, "LED strip", led_count=10, zones=[RGBZone(0, "Strip", 10)]),
                   RGBDevice(1, "Motherboard", led_count=30,
                             zones=[RGBZone(0, "Header 1", 20), RGBZone(1, "Header 2", 10)])]

        def set_leds(self, device, colors):
            sent[(device, None)] = list(colors)

        def set_zone_leds(self, device, zone, colors):
            sent[(device, zone)] = list(colors)

    proj = Project(mode="2.1")
    dev = proj.add_device("Amp", 3)
    a, b, c = dev.speakers
    a.rgb_device, a.rgb_mode = "LED strip", "vu"
    b.rgb_device, b.rgb_zone, b.rgb_mode, b.rgb_color = "Motherboard", "Header 2", "static", "#00ff00"
    rgb = RgbController(proj, lambda spk_id: 1.0 if spk_id == a.id else 0.0)
    rgb.client = FakeConnection()
    assert rgb.targets() == [("LED strip", "", 10), ("Motherboard", "", 30),
                             ("Motherboard", "Header 1", 20), ("Motherboard", "Header 2", 10)]
    frame = rgb.frame(0.0)
    assert set(frame) == {("LED strip", ""), ("Motherboard", "Header 2")}
    assert len(frame[("LED strip", "")]) == 10 and frame[("LED strip", "")][9][2] > 200
    assert frame[("Motherboard", "Header 2")] == [(0, 255, 0)] * 10


if __name__ == "__main__":
    test_lights_follow_the_speakers()
    test_whole_window()
    print("ok")
