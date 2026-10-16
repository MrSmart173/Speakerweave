"""Microphones on the room map: listed, ticked onto the map, dragged round the setup, saved,
and glowing with what they hear."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from speakerweave.mics import is_microphone
from speakerweave.model import Project

DEVICES = [{"name": "Speakers (Realtek)", "outputs": 2},
           {"name": "Microphone (Yeti Stereo Microphone)", "inputs": 2, "tones": {0: 300.0}},
           {"name": "Headset Microphone (Arctis 7)", "inputs": 1, "tones": {}},
           {"name": "CABLE Output (VB-Audio Virtual Cable)", "inputs": 8, "tones": {}},
           {"name": "Stereo Mix (Realtek(R) Audio)", "inputs": 2, "tones": {}}]


def test_only_real_microphones_count():
    assert is_microphone("Microphone (Yeti Stereo Microphone)")
    assert not is_microphone("CABLE Output (VB-Audio Virtual Cable)")
    assert not is_microphone("Stereo Mix (Realtek(R) Audio)")


def test_microphones_are_kept_in_the_setup():
    p = Project()
    mic = p.add_mic("Microphone (Yeti Stereo Microphone)")
    mic.label, mic.x = "Desk mic", 1.25
    again = Project.from_json(p.to_json())
    assert again.mics[0].title == "Desk mic" and again.mics[0].x == 1.25
    second = again.add_mic("Headset Microphone (Arctis 7)")
    assert (second.x, second.y) != (again.mics[0].x, again.mics[0].y)       # not on top of it
    again.remove_mic(mic.id)
    assert [m.name for m in again.mics] == ["Headset Microphone (Arctis 7)"]


def test_tick_drag_and_hear(monkeypatch):
    from test_hidden_outputs import pump, window
    app, state, win = window(DEVICES)
    try:
        state.scan_devices()
        win._rebuild_tree()
        head = next(win.tree.topLevelItem(i) for i in range(win.tree.topLevelItemCount())
                    if win.tree.topLevelItem(i).text(0) == "Microphones")
        names = [head.child(i).text(0) for i in range(head.childCount())]
        assert names == ["Microphone (Yeti Stereo Microphone)", "Headset Microphone (Arctis 7)"]
        head.child(0).setCheckState(0, Qt.Checked)                 # tick: onto the map
        pump(app, 0.1)
        mic = state.project.mics[0]
        assert mic.name == "Microphone (Yeti Stereo Microphone)" and win.map.sel_mic == mic.id
        assert state.mic_meters.open_count == 1
        pump(app, 0.4)                                              # it hears its tone
        win._tick_meters()
        assert win.map.mic_levels.get(mic.id, 0.0) > 0.3

        start = win.map.to_px(mic.x, mic.y)                         # drag it to a new spot
        goal = win.map.to_px(mic.x + 1.0, mic.y + 0.5)
        QTest.mousePress(win.map, Qt.LeftButton, Qt.NoModifier, start.toPoint())
        ev_pos = goal.toPoint()
        QTest.mouseMove(win.map, ev_pos)
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QEvent
        move = QMouseEvent(QEvent.MouseMove, QPointF(ev_pos), QPointF(ev_pos), Qt.NoButton,
                           Qt.LeftButton, Qt.NoModifier)
        win.map.mouseMoveEvent(move)
        QTest.mouseRelease(win.map, Qt.LeftButton, Qt.NoModifier, ev_pos)
        assert abs(mic.x - (state.project.listener_x + 1.0)) < 0.15
        shot = os.environ.get("SPEAKERWEAVE_SHOT")
        if shot:
            state.add_mic("Headset Microphone (Arctis 7)")
            win._rebuild_tree()
            win._tick_meters()
            win.grab().save(shot)
        mic.enabled = False                                         # untick: it closes
        state.mics_changed()
        assert state.mic_meters.open_count <= 1 and mic.id not in state.mic_meters._streams
        state.remove_mic(mic.id)
        assert mic not in state.project.mics
    finally:
        state.mic_meters.close_all()
        win.close()
        state.stop()
        pump(app, 0.1)
