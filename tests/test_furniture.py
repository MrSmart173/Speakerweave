"""Desks and sim rigs on the room map: three desks, a racing rig with its shifter and
handbrake where you want them, and a flight rig, behind a switch in the settings."""
import json
import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from speakerweave import furniture
from speakerweave.furniture import Furniture
from speakerweave.model import Project


def test_every_piece_is_placed_so_you_sit_at_it():
    for kind in furniture.KINDS:
        piece = furniture.new(kind, 0.3, 0.8)
        sx, sy = furniture.seat(piece)
        assert abs(sx - 0.3) < 1e-6 and abs(sy - 0.8) < 1e-6, kind
        assert piece.rotation == 0.0
        # the piece is in front of you, and you are not standing on a desk top
        if not piece.is_rig:
            assert not furniture.contains(piece, 0.3, 0.8), kind
            assert furniture.contains(piece, 0.3, 0.8 - 0.6), kind
        else:
            assert furniture.contains(piece, 0.3, 0.8)                  # you sit in the rig
    assert set(furniture.DESKS) == {"desk", "desk_u", "desk_corner"}
    assert set(furniture.RIGS) == {"racing", "flight"}


def test_the_desk_shapes():
    plain = furniture.new("desk")
    assert len(furniture.desk_outline(plain)) == 4
    u = furniture.new("desk_u")
    outline = furniture.desk_outline(u)
    assert len(outline) == 8
    sx, sy = furniture.seat_local(u)
    # the sides come straight out towards you, either side of where you sit
    assert furniture.contains(u, *furniture.to_world(u, -u.width / 2 + 0.05, sy))
    assert furniture.contains(u, *furniture.to_world(u, u.width / 2 - 0.05, sy))
    assert not furniture.contains(u, *furniture.to_world(u, 0.0, sy))
    corner = furniture.new("desk_corner")
    right = furniture.desk_outline(corner)
    corner.corner_side = "left"
    left = furniture.desk_outline(corner)
    assert sorted(round(-x, 6) for x, _y in left) == sorted(round(x, 6) for x, _y in right)
    assert max(x for x, _y in right) > 0 and any(y > corner.depth / 2 + 0.3 for _x, y in right)


def test_the_racing_rig_shifter_and_handbrake():
    rig = furniture.new("racing")
    parts = furniture.rig_parts(rig)
    for name in ("frame", "seat", "wheelbase", "wheel", "pedals", "shifter", "mount"):
        assert name in parts, name
    assert len(parts["pedals"]) == 3 and "handbrake" not in parts
    assert parts["shifter"][0][1] > furniture.RIG_W / 2                 # outside the frame, right
    rig.shifter_side = "left"
    assert furniture.rig_parts(rig)["shifter"][0][3] < -furniture.RIG_W / 2
    rig.handbrake = True
    parts = furniture.rig_parts(rig)
    assert "handbrake" in parts and parts["handbrake"][0][3] < -furniture.RIG_W / 2
    shifter_back = parts["shifter"][0][4]
    assert parts["handbrake"][0][2] >= shifter_back - 0.01                # behind the shifter
    rig.shifter = False
    parts = furniture.rig_parts(rig)
    assert "shifter" not in parts and "handbrake" in parts and "mount" in parts
    rig.handbrake = False
    assert "mount" not in furniture.rig_parts(rig)                        # nothing to hold


def test_the_flight_rig_controls():
    rig = furniture.new("flight")
    for controls, wanted in (("hotas", {"stick", "throttle", "mount"}), ("centre", {"stick", "throttle"}),
                             ("yoke", {"yoke", "throttle", "deck"})):
        rig.controls = controls
        parts = furniture.rig_parts(rig)
        assert wanted <= set(parts), controls
        assert "wheel" not in parts and len(parts["pedals"]) == 3        # two rudder pedals, a bar


def test_kept_in_the_setup_and_cleaned_up():
    p = Project()
    p.furniture.append(furniture.new("racing", 0.0, 0.5))
    p.furniture[0].shifter_side, p.furniture[0].handbrake = "left", True
    again = Project.from_json(p.to_json())
    assert again.furniture[0] == p.furniture[0]
    data = json.loads(p.to_json())
    data["furniture"] = [{"kind": "spaceship", "width": 99, "rotation": 540, "shifter_side": "up",
                          "controls": "joystick", "x": "abc"}, "nonsense"]
    odd = Project.from_json(json.dumps(data)).furniture
    assert len(odd) == 1
    f = odd[0]
    assert f.kind == "desk" and f.width == 4.0 and f.rotation == -180.0 and f.shifter_side == "right"
    assert f.controls == "hotas" and f.x == 0.0
    del data["furniture"]
    assert Project.from_json(json.dumps(data)).furniture == []           # older setups


def test_turning_and_local_directions():
    piece = Furniture(kind="desk", x=1.0, y=2.0, rotation=90.0)
    x, y = furniture.to_world(piece, 0.0, -1.0)                           # its front, turned right
    assert abs(x - 2.0) < 1e-9 and abs(y - 2.0) < 1e-9
    lx, ly = furniture.to_local(piece, x, y)
    assert abs(lx) < 1e-9 and abs(ly + 1.0) < 1e-9


def test_on_the_room_map(monkeypatch):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication
    from test_hidden_outputs import pump, window
    app, state, win = window([{"name": "Speakers", "outputs": 2}])
    try:
        state.save_settings = lambda: None
        m = win.map
        p = state.project
        win.workspaces.open("room")
        pump(app, 0.1)
        assert not state.settings.furniture_on                           # off until switched on
        rig = furniture.new("racing", p.listener_x, p.listener_y)
        p.furniture.append(rig)
        middle = m.to_px(rig.x, rig.y)
        assert m._hit(middle) is None or m._hit(middle)[0] != "furniture"
        def menu_at(pos):
            menu = m.furniture_menu_at(QPointF(pos))
            return None if menu is None else [a.text() for a in menu.actions()]
        assert menu_at(QPointF(20, 60)) is None                          # no add menu either

        win.settings_page.furniture.setChecked(True)
        assert state.settings.furniture_on
        p.furniture = []
        assert menu_at(QPointF(20, 60)) == ["Add a desk", "Add a sim rig"]
        rig = m.add_furniture("racing")
        assert m.sel_furniture == rig.id and rig in p.furniture
        sx, sy = furniture.seat(rig)
        assert abs(sx - p.listener_x) < 1e-6 and abs(sy - p.listener_y) < 1e-6
        pump(app, 0.2)
        m.grab()                                                          # it draws
        # the right click menu: shifter, its side, the handbrake
        middle = m.to_px(*furniture.to_world(rig, 0.0, -0.3))
        assert m._hit(middle)[0] == "furniture"
        texts = menu_at(middle)
        for wanted in ("Shifter", "Shifter and handbrake on the left", "Shifter and handbrake on the right",
                       "Handbrake", "Size and options...", "Sit me in it", "Remove from the map"):
            assert wanted in texts, wanted
        m.change_furniture(rig, shifter_side="left", handbrake=True)
        assert rig.shifter_side == "left" and rig.handbrake
        # dragging the rig you sit in brings you along
        before = (p.listener_x, p.listener_y)
        from PySide6.QtTest import QTest
        start = m.to_px(*furniture.to_world(rig, 0.0, -0.5))
        QTest.mousePress(m, Qt.LeftButton, Qt.NoModifier, start.toPoint())
        QTest.mouseMove(m, (start + QPointF(60, 0)).toPoint())
        QTest.mouseRelease(m, Qt.LeftButton, Qt.NoModifier, (start + QPointF(60, 0)).toPoint())
        assert p.listener_x > before[0] + 0.05 and abs(p.listener_y - before[1]) < 0.06
        sx, sy = furniture.seat(rig)
        assert math.hypot(sx - p.listener_x, sy - p.listener_y) < 0.02
        # turning it turns it round you
        here = (p.listener_x, p.listener_y)
        m.turn_furniture(rig, 30.0)
        assert rig.rotation == 30.0 and (p.listener_x, p.listener_y) == here
        sx, sy = furniture.seat(rig)
        assert math.hypot(sx - here[0], sy - here[1]) < 0.01
        # a desk you do not sit in stays put without you
        desk = m.add_furniture("desk_u")
        desk.x += 1.0
        m.change_furniture(desk, width=1.8)
        assert desk.width == 1.8 and (p.listener_x, p.listener_y) == here
        # the size and options dialog
        from speakerweave.ui.furniture_dialog import FurnitureDialog
        dialog = FurnitureDialog(m, desk)
        dialog.fields["width"].setValue(150)
        dialog.fields["wing"].setValue(90)
        dialog.fields["rotation"].setValue(-20)
        dialog._apply()
        assert desk.width == 1.5 and desk.wing == 0.9 and desk.rotation == -20.0
        dialog = FurnitureDialog(m, rig)
        assert set(dialog.fields) == {"shifter", "handbrake", "shifter_side", "rotation"}
        dialog.fields["shifter"].setChecked(False)
        dialog._apply()
        assert not rig.shifter
        # Delete removes the selected one
        m.sel_furniture = desk.id
        m.setFocus()
        QApplication.sendEvent(m, QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier))
        assert desk not in p.furniture and rig in p.furniture
        # switched off: kept in the setup, not drawn and not in the way
        win.settings_page.furniture.setChecked(False)
        assert m._hit(m.to_px(rig.x, rig.y)) is None or m._hit(m.to_px(rig.x, rig.y))[0] != "furniture"
        assert rig in p.furniture
        p.furniture = []
    finally:
        state.settings.furniture_on = False
        win.state.runner.stop()
        win.close()
