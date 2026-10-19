"""Zooming the room map: speakers close to you (a monitor half a metre away) can be spread
out on the map while every distance stays what it really is."""
import json
import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QWheelEvent

from speakerweave.model import Project, speaker_distance, speaker_position
from speakerweave.ui import roommap
from test_hidden_outputs import pump, window


def desk_setup(state):
    """A monitor with speakers 45 cm in front of you, as on a desk."""
    p = state.project
    p.set_mode("2.0")
    dev = p.add_device("VG258 (NVIDIA High Definition Audio)", 2)
    dev.width = 0.55
    dev.x, dev.y = p.listener_x, p.listener_y - 0.45
    dev.enabled = True
    state.structureChanged.emit()
    return dev


def wheel(widget, where: QPointF, notches: int, mods=Qt.NoModifier):
    ev = QWheelEvent(where, widget.mapToGlobal(where), QPoint(0, 0), QPoint(0, 120 * notches),
                     Qt.NoButton, mods, Qt.NoScrollPhase, False)
    widget.wheelEvent(ev)


def test_zoom_spreads_close_speakers_out_and_keeps_the_distances():
    app, state, win = window([{"name": "VG258 (NVIDIA High Definition Audio)", "outputs": 2}])
    try:
        dev = desk_setup(state)
        m = win.map
        win.resize(1400, 860)
        pump(app, 0.05)
        p = state.project
        spk = dev.speakers[0]
        true_m = speaker_distance(p, dev, spk)
        assert p.map_auto and m.fit_btn.isChecked()                          # fits itself to start with
        m.set_zoom(1.0)                                                       # by hand: the whole room
        assert not p.map_auto and not m.fit_btn.isChecked()

        def on_screen():
            a = m.to_px(p.listener_x, p.listener_y)
            b = m.to_px(*speaker_position(dev, spk))
            return math.hypot(a.x() - b.x(), a.y() - b.y())

        near = on_screen()
        m.set_zoom(3.0)
        assert m.zoom == 3.0 and abs(on_screen() / near - 3.0) < 1e-6        # 3 times further apart
        assert speaker_distance(p, dev, spk) == true_m                       # the real distance stays
        # zoomed in, the view closes in on you: you are in the middle of the map
        you = m.to_px(p.listener_x, p.listener_y)
        assert abs(you.x() - m.width() / 2) < 1 and abs(you.y() - m.height() / 2) < 1
        # and a point clicked on the map still lands where it is drawn
        x, y = m.to_m(m.to_px(0.123, -0.456))
        assert abs(x - 0.123) < 1e-9 and abs(y + 0.456) < 1e-9

        # the guide ring follows a desk setup instead of staying a metre and more away
        assert p.map_zoom == 3.0
        assert m.zoom_label.text() == "300%"

        m.set_zoom(99)
        assert m.zoom == roommap.ZOOM_MAX and not m.zoom_in_btn.isEnabled()
        m.zoom_label.click()                                                  # back to the whole room
        assert m.zoom == 1.0 and not m.zoom_out_btn.isEnabled()

        m.fit_btn.click()
        assert p.map_auto and m.zoom > 2.5                                    # a desk fills the map
        for x, y in m._things():
            pt = m.to_px(x, y)
            assert 0 < pt.x() < m.width() and 0 < pt.y() < m.height()

        shot = os.environ.get("SPEAKERWEAVE_SHOT")
        if shot:
            win.grab().save(shot)
            m.set_zoom(1.0)
            pump(app, 0.05)
            win.grab().save(shot.replace(".png", "_whole_room.png"))
    finally:
        win.close()
        state.stop()
        pump(app, 0.1)


def test_wheel_and_keys_zoom_and_the_wheel_still_turns_a_unit():
    app, state, win = window([{"name": "VG258 (NVIDIA High Definition Audio)", "outputs": 2}])
    try:
        dev = desk_setup(state)
        m = win.map
        win.resize(1400, 860)
        pump(app, 0.05)
        m.set_zoom(1.0)
        wheel(m, QPointF(40, m.height() - 60), 2)                            # an empty spot
        assert abs(m.zoom - roommap.WHEEL_STEP ** 2) < 0.01
        wheel(m, QPointF(40, m.height() - 60), -5)
        assert m.zoom == 1.0
        before = dev.rotation
        wheel(m, m.to_px(dev.x, dev.y), 1)                                    # over the monitor: turns it
        assert dev.rotation != before and m.zoom == 1.0
        wheel(m, m.to_px(dev.x, dev.y), 1, Qt.ControlModifier)                # Ctrl: zooms instead
        assert m.zoom > 1.0
        m.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Plus, Qt.NoModifier, "+"))
        assert m.zoom > roommap.WHEEL_STEP
        m.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_0, Qt.NoModifier, "0"))
        assert m.zoom == 1.0
    finally:
        win.close()
        state.stop()
        pump(app, 0.1)


def test_every_setup_keeps_its_own_zoom():
    p = Project()
    p.map_zoom = 2.5
    again = Project.from_json(p.to_json())
    assert again.map_zoom == 2.5
    old = json.loads(p.to_json())
    del old["map_zoom"]                                                       # a setup saved before
    assert Project.from_json(json.dumps(old)).map_zoom == 1.0


def test_the_map_fits_itself_to_any_window_size_and_scrolls_when_too_small():
    app, state, win = window([{"name": "VG258 (NVIDIA High Definition Audio)", "outputs": 2}])
    try:
        dev = desk_setup(state)
        m = win.map
        p = state.project
        sizes = []
        for w, h in ((1700, 1000), (1400, 860), (1100, 700), (900, 560)):
            win.resize(w, h)
            pump(app, 0.1)
            assert p.map_auto
            for x, y in m._things():                                          # everything stays in view
                pt = m.to_px(x, y)
                assert 0 < pt.x() < m.width() and 0 < pt.y() < m.height(), (w, h)
            s, _cx, _cy = m._geom()
            sizes.append(s)
        assert sizes[0] > sizes[-1]                                           # a bigger window, a bigger map
        # 45 cm never shrinks to a crowd of badges: at least about 100 pixels from you
        assert all(0.45 * s > 100 for s in sizes)
        # too small for everything: scroll bars instead of squashing
        bars = win.scroller.horizontalScrollBar(), win.scroller.verticalScrollBar()
        assert all(bar.isVisible() for bar in bars)
        assert win.scroller.widget().width() >= win.scroller.widget().minimumSizeHint().width() - 4
        win.resize(1700, 1000)
        pump(app, 0.1)
        assert not any(bar.isVisible() for bar in bars)

        # dragging never zooms under the mouse, letting go fits again
        m._drag = ("device", dev, None, 0.0, 0.0)
        before = m.zoom
        dev.y -= 1.0
        state.touch_layout()
        assert m.zoom == before
        m._drag = None
        state.touch_layout()
        assert m.zoom < before

        # a map with only you on it is not zoomed right in
        p.devices.clear()
        state.structureChanged.emit()
        s, _cx, _cy = m._geom()
        assert 1.0 * s < m.height()                                           # a metre still fits
    finally:
        win.close()
        state.stop()
        pump(app, 0.1)
