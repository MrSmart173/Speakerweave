"""The room map: drag screens, speakers and yourself to where they really are."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QMenu, QPushButton, QToolTip, QWidget

from ..model import (OFF, ROLE_ANGLES, ROLE_COLORS, ROLE_NAMES, ROLE_SHORT, can_move_alone, is_shape,
                     is_sub, face_listener, move_speaker, set_attached, shape_role, speaker_angle,
                     speaker_distance, speaker_position)
from . import theme

PAD = 44          # pixels around the room
R = 13.0          # speaker badge radius in pixels
SNAP = 0.05       # metres
EDGE_IN = 5.0     # the rim of a speaker badge reacts this far inside its edge
EDGE_OUT = 13.0   # ... and this far outside it


def _dist(a: QPointF, b: QPointF) -> float:
    return math.hypot(a.x() - b.x(), a.y() - b.y())


class RoomMap(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.levels: dict[str, float] = {}
        self.clipped: set[str] = set()
        self.test_role = ""
        self._drag = None           # (kind, device, speaker, offset x, offset y)
        self._hover = None          # (speaker id, "x" | "y" | "") under the mouse
        self.setMinimumSize(440, 380)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        for sig in (state.structureChanged, state.selectionChanged, state.layoutChanged):
            sig.connect(self.update)
        state.speakerChanged.connect(lambda _id: self.update())
        # the attach toggle of the selected output, in the top right corner of the map
        self.attach_btn = QPushButton("Speakers attached", self)
        self.attach_btn.setCheckable(True)
        self.attach_btn.setToolTip("On: the speakers sit on the unit (or in their surround shape) and "
                                   "move with it.\nOff: each speaker has its own spot. Turning it "
                                   "back off brings each speaker back to where it was.")
        self.attach_btn.hide()
        self.attach_btn.toggled.connect(self._attach_toggled)
        for sig in (state.selectionChanged, state.structureChanged, state.layoutChanged):
            sig.connect(self._place_attach)

    # ------------------------------------------------------------ attach toggle
    def _place_attach(self) -> None:
        dev = self.state.selected_device()
        if dev is None:
            self.attach_btn.hide()
            return
        self.attach_btn.blockSignals(True)
        self.attach_btn.setChecked(dev.kind == "builtin")
        self.attach_btn.blockSignals(False)
        self.attach_btn.setText("Speakers attached" if dev.kind == "builtin" else "Speakers loose")
        self.attach_btn.adjustSize()
        self.attach_btn.move(self.width() - self.attach_btn.width() - 10, 8)
        self.attach_btn.show()

    def _attach_toggled(self, on: bool) -> None:
        dev = self.state.selected_device()
        if dev is None:
            return
        self.set_device_attached(dev, on)

    def set_device_attached(self, dev, on: bool) -> None:
        set_attached(dev, on)
        if on and self.state.sel_spk:
            self.state.select(dev.id, "")     # an attached speaker moves with its unit
        self.state.touch_layout()
        self.state.structureChanged.emit()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._place_attach()

    # ------------------------------------------------------------ geometry
    def _geom(self):
        p = self.state.project
        w = max(50.0, self.width() - 2 * PAD)
        h = max(50.0, self.height() - 2 * PAD)
        scale = max(8.0, min(w / max(p.room_w, 0.5), h / max(p.room_h, 0.5)))
        return scale, self.width() / 2.0, self.height() / 2.0

    def to_px(self, x: float, y: float) -> QPointF:
        s, cx, cy = self._geom()
        return QPointF(cx + x * s, cy + y * s)

    def to_m(self, pos: QPointF) -> tuple[float, float]:
        s, cx, cy = self._geom()
        return (pos.x() - cx) / s, (pos.y() - cy) / s

    def _clamp(self, x: float, y: float, snap: bool) -> tuple[float, float]:
        p = self.state.project
        if snap:
            x, y = round(x / SNAP) * SNAP, round(y / SNAP) * SNAP
        x = min(max(x, -p.room_w / 2), p.room_w / 2)
        y = min(max(y, -p.room_h / 2), p.room_h / 2)
        return round(x, 3), round(y, 3)

    def _body(self, dev) -> tuple[float, float]:
        """Size of a unit on screen (along its length, across)."""
        s, _, _ = self._geom()
        return max(46.0, dev.width * s + 2 * R + 6), max(18.0, 0.12 * s)

    def _shape(self, dev) -> QPolygonF:
        """The outline of a surround system: its main speakers in order around
        the middle (the subwoofers sit outside it)."""
        mains = [s for s in dev.speakers if not is_sub(shape_role(s))]
        pts = [self.to_px(*speaker_position(dev, s)) for s in mains]
        if not pts:
            return QPolygonF()
        cx = sum(p.x() for p in pts) / len(pts)
        cy = sum(p.y() for p in pts) / len(pts)
        pts.sort(key=lambda p: math.atan2(p.x() - cx, -(p.y() - cy)))
        return QPolygonF(pts)

    def _shape_centre(self, dev) -> QPointF:
        if dev.kind == "builtin":
            return self.to_px(dev.x, dev.y)
        poly = self._shape(dev)
        if poly.isEmpty():
            return self.to_px(dev.x, dev.y)
        return QPointF(sum(p.x() for p in poly) / len(poly), sum(p.y() for p in poly) / len(poly))

    def _back(self, dev) -> QPointF:
        a = math.radians(dev.rotation)
        return QPointF(math.sin(a), -math.cos(a))

    def _handle(self, dev) -> QPointF:
        """Where the turn handle of a unit is."""
        if is_shape(dev):
            s, _, _ = self._geom()
            c, b = self.to_px(dev.x, dev.y), self._back(dev)
            d = dev.width / 2 * s + R + 26
            return QPointF(c.x() + b.x() * d, c.y() + b.y() * d)
        _, h = self._body(dev)
        c, b = self.to_px(dev.x, dev.y), self._back(dev)
        d = h / 2 + 24
        return QPointF(c.x() + b.x() * d, c.y() + b.y() * d)

    def _local(self, dev, pos: QPointF) -> tuple[float, float]:
        """A screen point in the unit's own axes (along, across)."""
        c = self.to_px(dev.x, dev.y)
        a = math.radians(dev.rotation)
        dx, dy = pos.x() - c.x(), pos.y() - c.y()
        return dx * math.cos(a) + dy * math.sin(a), -dx * math.sin(a) + dy * math.cos(a)

    def _edge_axis(self, dev, spk, pos: QPointF) -> str:
        """"x" or "y" if pos is on the left / right or top / bottom rim of a
        speaker badge that can be moved on its own, otherwise ""."""
        if not can_move_alone(dev, spk):
            return ""
        c = self.to_px(*speaker_position(dev, spk))
        dx, dy = pos.x() - c.x(), pos.y() - c.y()
        d = math.hypot(dx, dy)
        if not (R - EDGE_IN <= d <= R + EDGE_OUT):
            return ""
        if abs(dx) >= abs(dy) * 1.6:
            return "x"
        if abs(dy) >= abs(dx) * 1.6:
            return "y"
        return ""

    def _hit(self, pos: QPointF):
        proj = self.state.project
        sel = self.state.selected_device()
        if sel is not None and sel.kind == "builtin" and not is_shape(sel) \
                and _dist(pos, self._handle(sel)) <= 11:
            return ("turn", sel, None)
        # the middle of a badge wins over the rim of a neighbour
        for dev in reversed(proj.devices):
            for spk in reversed(dev.speakers):
                if _dist(pos, self.to_px(*speaker_position(dev, spk))) < R - EDGE_IN:
                    return ("speaker", dev, spk)
        for dev in reversed(proj.devices):
            for spk in reversed(dev.speakers):
                axis = self._edge_axis(dev, spk, pos)
                if axis:
                    return ("edge_" + axis, dev, spk)
        for dev in reversed(proj.devices):
            for spk in reversed(dev.speakers):
                if _dist(pos, self.to_px(*speaker_position(dev, spk))) <= R + 3:
                    return ("speaker", dev, spk)
        if _dist(pos, self.to_px(proj.listener_x, proj.listener_y)) <= 15:
            return ("listener", None, None)
        for dev in reversed(proj.devices):
            if is_shape(dev):
                if self._shape(dev).containsPoint(pos, Qt.OddEvenFill):
                    return ("device", dev, None)
                continue
            w, h = self._body(dev)
            lx, ly = self._local(dev, pos)
            if abs(lx) <= w / 2 + 3 and abs(ly) <= h / 2 + 5:
                return ("device", dev, None)
        return None

    # ------------------------------------------------------------ mouse
    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        pos = ev.position()
        hit = self._hit(pos)
        if hit is None:
            self.state.select("", "")
            return
        kind, dev, spk = hit
        mx, my = self.to_m(pos)
        if kind == "listener":
            p = self.state.project
            self._drag = ("listener", None, None, mx - p.listener_x, my - p.listener_y)
        elif kind == "turn":
            self._drag = ("turn", dev, None, 0.0, 0.0)
        elif kind in ("edge_x", "edge_y"):
            # A unit stays selected as a whole, so its position numbers stay in view
            # on the Output tab while one end is pulled. A loose speaker has its own.
            if dev.kind == "external":
                self.state.select(dev.id, spk.id)
            else:
                self.state.select(dev.id, "")
            sx, sy = speaker_position(dev, spk)
            self._drag = (kind, dev, spk, mx - sx, my - sy)
            self._hover = (spk.id, kind[-1])
            self.setCursor(Qt.SizeHorCursor if kind == "edge_x" else Qt.SizeVerCursor)
            self.update()
            return
        elif kind == "speaker":
            self.state.select(dev.id, spk.id)
            if dev.kind == "external":
                self._drag = ("speaker", dev, spk, mx - spk.x, my - spk.y)
            else:
                self._drag = ("device", dev, None, mx - dev.x, my - dev.y)
        else:
            self.state.select(dev.id, "")
            self._drag = ("device", dev, None, mx - dev.x, my - dev.y)
        self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self._drag is None:
            hit = self._hit(pos)
            hover = None
            if hit and hit[0] in ("edge_x", "edge_y"):
                self.setCursor(Qt.SizeHorCursor if hit[0] == "edge_x" else Qt.SizeVerCursor)
                hover = (hit[2].id, hit[0][-1])
            else:
                self.setCursor(Qt.OpenHandCursor if hit else Qt.ArrowCursor)
                if hit and hit[0] == "speaker" and can_move_alone(hit[1], hit[2]):
                    hover = (hit[2].id, "")
            if hover != self._hover:
                self._hover = hover
                self.update()
            return
        kind, dev, spk, ox, oy = self._drag
        proj = self.state.project
        snap = not (ev.modifiers() & Qt.ShiftModifier)
        mx, my = self.to_m(pos)
        if kind == "listener":
            proj.listener_x, proj.listener_y = self._clamp(mx - ox, my - oy, snap)
        elif kind == "speaker":
            x, y = self._clamp(mx - ox, my - oy, snap)
            move_speaker(dev, spk, x, y, proj.mirror)
        elif kind in ("edge_x", "edge_y"):
            x, y = self._clamp(mx - ox, my - oy, snap)
            now_x, now_y = speaker_position(dev, spk)
            if kind == "edge_x":
                y = now_y               # sideways only
            else:
                x = now_x               # front to back only
            move_speaker(dev, spk, x, y, proj.mirror)
        elif kind == "device":
            old_x, old_y = dev.x, dev.y
            dev.x, dev.y = self._clamp(mx - ox, my - oy, snap)
            if is_shape(dev) and dev.kind == "external":
                # a loose surround system still moves as one when its shape is dragged
                for each in dev.speakers:
                    each.x, each.y = round(each.x + dev.x - old_x, 3), round(each.y + dev.y - old_y, 3)
            elif proj.auto_face and dev.kind == "builtin":
                face_listener(proj, dev)
        elif kind == "turn":
            c = self.to_px(dev.x, dev.y)
            angle = math.degrees(math.atan2(pos.x() - c.x(), -(pos.y() - c.y())))
            dev.rotation = round(angle / 5.0) * 5.0 if snap else round(angle, 1)
        self.state.touch_layout()

    def mouseReleaseEvent(self, ev):
        if self._drag is not None:
            self._drag = None
            self._hover = None
            self.setCursor(Qt.OpenHandCursor)
            self.state.touch_layout()

    def leaveEvent(self, _ev):
        if self._hover is not None and self._drag is None:
            self._hover = None
            self.update()

    def contextMenuEvent(self, ev):
        hit = self._hit(QPointF(ev.pos()))
        if hit is None or hit[1] is None:
            return
        kind, dev, spk = hit
        state = self.state
        menu = QMenu(self)
        if spk is not None:
            state.select(dev.id, spk.id)
            menu.addSection(f"{spk.name} of {dev.title}")
            from .panels import fill_sound_menu
            menu.addAction("Play a short noise on this speaker", lambda: state.identify(spk.id, "noise"))
            play = menu.addMenu("Play another test sound on it")
            fill_sound_menu(play, state, lambda k: state.identify(spk.id, k))
            menu.addSeparator()
            roles = menu.addMenu("Plays")
            for role in state.project.role_choices():
                action = roles.addAction(ROLE_NAMES[role], lambda r=role: self._set_role(spk, r))
                action.setCheckable(True)
                action.setChecked(spk.role == role)
            mute = menu.addAction("Unmute" if spk.mute else "Mute", lambda: self._toggle(spk, "mute"))
            solo = menu.addAction("Stop solo" if spk.solo else "Solo (hear only this one)",
                                  lambda: self._toggle(spk, "solo"))
            mute.setEnabled(dev.enabled)
            solo.setEnabled(dev.enabled)
            menu.addSeparator()
            attach = menu.addAction("Speakers attached to the unit",
                                    lambda: self.set_device_attached(dev, dev.kind != "builtin"))
            attach.setCheckable(True)
            attach.setChecked(dev.kind == "builtin")
        else:
            state.select(dev.id, "")
            menu.addSection(dev.title)
            for each in dev.speakers:
                menu.addAction(f"Play a short noise on {each.name}",
                               lambda s=each: state.identify(s.id, "noise"))
            menu.addSeparator()
            attach = menu.addAction("Speakers attached to the unit",
                                    lambda: self.set_device_attached(dev, dev.kind != "builtin"))
            attach.setCheckable(True)
            attach.setChecked(dev.kind == "builtin")
            if dev.kind == "builtin" and not is_shape(dev):
                menu.addAction("Turn to face me", lambda: (face_listener(state.project, dev),
                                                           state.touch_layout()))
        menu.exec(ev.globalPos())

    def _set_role(self, spk, role) -> None:
        self.state.project.set_role(spk, role)
        self.state.touch_routing()
        self.state.touch_speaker(spk.id)

    def _toggle(self, spk, field) -> None:
        setattr(spk, field, not getattr(spk, field))
        self.state.touch_routing()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Space and self.state.sel_spk:
            self.state.identify(self.state.sel_spk, "noise")
            return
        super().keyPressEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        hit = self._hit(ev.position())
        if hit and hit[0] == "speaker":
            self.state.identify(hit[2].id)

    def wheelEvent(self, ev):
        hit = self._hit(ev.position())
        if not hit or hit[1] is None or hit[1].kind != "builtin":
            return
        dev = hit[1]
        step = 5.0 if ev.angleDelta().y() > 0 else -5.0
        dev.rotation = ((dev.rotation + step + 180.0) % 360.0) - 180.0
        self.state.touch_layout()

    def event(self, ev):
        if ev.type() == ev.Type.ToolTip:
            hit = self._hit(QPointF(ev.pos()))
            text = ""
            if hit and hit[0] == "speaker":
                dev, spk = hit[1], hit[2]
                text = (f"{spk.name} channel of {dev.title}\nPlays: {ROLE_NAMES.get(spk.role, spk.role)}"
                        f"\nDouble click to hear which one it is")
            elif hit and hit[0] == "device":
                text = f"{hit[1].title}\nDrag to move, scroll to turn"
            elif hit and hit[0] == "listener":
                text = "You (the listening position)"
            elif hit and hit[0] == "turn":
                text = "Drag to turn"
            elif hit and hit[0] == "edge_x":
                text = "Drag to move this speaker left and right only"
            elif hit and hit[0] == "edge_y":
                text = "Drag to move this speaker forward and back only"
            if text:
                QToolTip.showText(ev.globalPos(), text, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(ev)

    # ------------------------------------------------------------ painting
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        proj = self.state.project
        s, cx, cy = self._geom()
        p.fillRect(self.rect(), QColor(theme.BG))

        room = QRectF(cx - proj.room_w * s / 2, cy - proj.room_h * s / 2, proj.room_w * s, proj.room_h * s)
        p.setPen(QPen(QColor(theme.BORDER), 1.5))
        p.setBrush(QColor(theme.PANEL))
        p.drawRoundedRect(room, 10, 10)
        self._paint_grid(p, room, s, cx, cy)
        self._paint_guides(p)

        small = QFont(self.font())
        small.setPointSizeF(8.5)
        bold = QFont(small)
        bold.setBold(True)

        for dev in proj.devices:
            self._paint_device(p, dev, small)
        sel_dev, sel_spk = self.state.selected_speaker()
        if sel_spk is not None:
            self._paint_measure(p, sel_dev, sel_spk, small)
        any_solo = any(s.solo for d in proj.devices if d.enabled for s in d.speakers)
        for dev in proj.devices:
            for spk in dev.speakers:
                self._paint_speaker(p, dev, spk, bold, small, any_solo)
        self._paint_edge_arrows(p)
        self._paint_listener(p, small)

        p.setFont(small)
        p.setPen(QColor(theme.DIM))
        room_for = self.width() - 20
        for hint in ("Drag to place things.  Drag a speaker's rim to move only it.  "
                     "Right click a speaker to hear it.",
                     "Drag to place.  Drag a rim to move one speaker.  Right click to hear it.",
                     "Drag to place.  Right click to hear it."):
            if p.fontMetrics().horizontalAdvance(hint) <= room_for:
                break                                # the longest hint that fits the width
        p.drawText(QRectF(10, self.height() - 24, room_for, 18), Qt.AlignCenter, hint)
        if not proj.devices:
            p.setPen(QColor(theme.DIM))
            big = QFont(self.font())
            big.setPointSizeF(12)
            p.setFont(big)
            p.drawText(QRectF(room.left(), room.top() + 20, room.width(), 60), Qt.AlignCenter,
                       "Tick the sound outputs you want to use in the list on the left")
        p.end()

    def _paint_grid(self, p, room, s, cx, cy):
        proj = self.state.project
        p.save()
        p.setClipRect(room.adjusted(1, 1, -1, -1))
        half_w, half_h = proj.room_w / 2, proj.room_h / 2
        k = math.ceil(-half_w / 0.5)
        while k * 0.5 <= half_w:
            major = k % 2 == 0
            p.setPen(QPen(theme.faint(18 if major else 8), 1))
            x = cx + k * 0.5 * s
            p.drawLine(QPointF(x, room.top()), QPointF(x, room.bottom()))
            k += 1
        k = math.ceil(-half_h / 0.5)
        while k * 0.5 <= half_h:
            major = k % 2 == 0
            p.setPen(QPen(theme.faint(18 if major else 8), 1))
            y = cy + k * 0.5 * s
            p.drawLine(QPointF(room.left(), y), QPointF(room.right(), y))
            k += 1
        p.restore()
        # one metre scale bar
        p.setPen(QPen(QColor(theme.DIM), 1.5))
        x0, y0 = room.left() + 12, room.bottom() - 12
        p.drawLine(QPointF(x0, y0), QPointF(x0 + s, y0))
        p.drawLine(QPointF(x0, y0 - 3), QPointF(x0, y0 + 3))
        p.drawLine(QPointF(x0 + s, y0 - 3), QPointF(x0 + s, y0 + 3))
        f = QFont(self.font())
        f.setPointSizeF(8)
        p.setFont(f)
        p.drawText(QRectF(x0, y0 - 18, s, 14), Qt.AlignCenter, "1 m")
        p.drawText(QRectF(room.left() + 10, room.top() + 6, 80, 14), Qt.AlignLeft, "FRONT")
        p.drawText(QRectF(room.left() + 10, room.bottom() - 46, 80, 14), Qt.AlignLeft, "BACK")

    def _paint_guides(self, p):
        """Ring around the listener with the ideal spot for each role. It is
        drawn clearly enough to read in every colour theme."""
        proj = self.state.project
        s, _, _ = self._geom()
        dists = sorted(speaker_distance(proj, d, sp) for d, sp in proj.all_speakers() if sp.role != OFF)
        radius = dists[len(dists) // 2] if dists else 1.6
        radius = min(max(radius, 0.8), 0.48 * min(proj.room_w, proj.room_h))
        c = self.to_px(proj.listener_x, proj.listener_y)
        pen = QPen(theme.faint(95), 1.4, Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, radius * s, radius * s)
        f = QFont(self.font())
        f.setPointSizeF(8)
        f.setBold(True)
        p.setFont(f)
        for role in proj.mode_roles():
            if role not in ROLE_ANGLES:
                continue
            a = math.radians(ROLE_ANGLES[role])
            pt = QPointF(c.x() + math.sin(a) * radius * s, c.y() - math.cos(a) * radius * s)
            col = QColor(theme.readable(ROLE_COLORS[role]))
            fill = QColor(col)
            fill.setAlpha(70)
            p.setPen(QPen(col, 2))
            p.setBrush(fill)
            p.drawEllipse(pt, 6, 6)
            out = QPointF(c.x() + math.sin(a) * (radius * s + 17), c.y() - math.cos(a) * (radius * s + 17))
            p.drawText(QRectF(out.x() - 16, out.y() - 8, 32, 16), Qt.AlignCenter, ROLE_SHORT[role])

    def _paint_shape(self, p, dev, font):
        """A surround system: the outline through its speakers, subwoofers outside."""
        selected = self.state.sel_dev == dev.id
        external = dev.kind == "external"
        poly = self._shape(dev)
        p.save()
        p.setOpacity(1.0 if dev.enabled else 0.35)
        fill = QColor(theme.ACCENT if selected else theme.DEVICE_EDGE)
        fill.setAlpha(34 if selected else 26)
        edge = QColor(theme.ACCENT) if selected else QColor(theme.DEVICE_EDGE)
        p.setPen(QPen(edge, 2 if selected else 1.4, Qt.DashLine if external else Qt.SolidLine))
        p.setBrush(fill)
        p.drawPolygon(poly)
        # subwoofers: a dotted line to the nearest corner of the shape
        p.setPen(QPen(theme.faint(110), 1, Qt.DotLine))
        for spk in dev.speakers:
            if is_sub(shape_role(spk)) and len(poly):
                sp = self.to_px(*speaker_position(dev, spk))
                near = min(poly, key=lambda q: _dist(q, sp))
                p.drawLine(sp, near)
        p.restore()
        # the name above the shape (scroll over the shape to turn it)
        if len(poly):
            top = min(q.y() for q in poly)
            cx = sum(q.x() for q in poly) / len(poly)
            text = dev.title + ("  (loose speakers)" if external else "")
            p.setFont(font)
            tw = p.fontMetrics().horizontalAdvance(text) + 8
            p.setOpacity(1.0 if dev.enabled else 0.45)
            p.setPen(QColor(theme.TEXT) if selected else QColor(theme.DIM))
            p.drawText(QRectF(cx - tw / 2, top - R - 26, tw, 18), Qt.AlignCenter, text)
            p.setOpacity(1.0)

    def _paint_device(self, p, dev, font):
        if is_shape(dev):
            self._paint_shape(p, dev, font)
            return
        proj = self.state.project
        selected = self.state.sel_dev == dev.id
        w, h = self._body(dev)
        c = self.to_px(dev.x, dev.y)
        external = dev.kind == "external"
        p.save()
        p.setOpacity(1.0 if dev.enabled else 0.35)
        if external:
            p.setPen(QPen(theme.faint(90), 1, Qt.DotLine))
            for spk in dev.speakers:
                p.drawLine(c, self.to_px(spk.x, spk.y))
        p.translate(c)
        p.rotate(dev.rotation)
        body = QRectF(-w / 2, -h / 2, w, h)
        edge = QColor(theme.ACCENT) if selected else QColor(theme.DEVICE_EDGE)
        p.setPen(QPen(edge, 2 if selected else 1.3, Qt.DashLine if external else Qt.SolidLine))
        p.setBrush(QColor(theme.DEVICE) if not external else QColor(theme.DEVICE_EXT))
        p.drawRoundedRect(body, 5, 5)
        # the bright edge is the front (the side the picture and sound come out of)
        front = QColor(theme.mix(theme.TEXT, theme.ACCENT, 0.3))
        front.setAlpha(150 if not external else 60)
        p.setPen(QPen(front, 2))
        p.drawLine(QPointF(-w / 2 + 6, h / 2 - 1), QPointF(w / 2 - 6, h / 2 - 1))
        p.restore()

        if selected and not external:
            hp = self._handle(dev)
            p.setPen(QPen(QColor(theme.ACCENT), 1.3))
            p.drawLine(c, hp)
            p.setBrush(QColor(theme.BG))
            p.drawEllipse(hp, 7, 7)
            p.drawArc(QRectF(hp.x() - 3.5, hp.y() - 3.5, 7, 7), 30 * 16, 250 * 16)

        # name, on the side away from the listener
        lp = self.to_px(proj.listener_x, proj.listener_y)
        dx, dy = c.x() - lp.x(), c.y() - lp.y()
        n = math.hypot(dx, dy) or 1.0
        dx, dy = dx / n, dy / n
        text = dev.title + ("  (aux out)" if external else "")
        p.setFont(font)
        tw = p.fontMetrics().horizontalAdvance(text) + 8
        off = h / 2 + (44 if selected and not external else 22) + abs(dx) * tw / 2
        tc = QPointF(c.x() + dx * off, c.y() + dy * off)
        p.setOpacity(1.0 if dev.enabled else 0.45)
        p.setPen(QColor(theme.TEXT) if selected else QColor(theme.DIM))
        p.drawText(QRectF(tc.x() - tw / 2, tc.y() - 9, tw, 18), Qt.AlignCenter, text)
        p.setOpacity(1.0)

    def _paint_measure(self, p, dev, spk, font):
        proj = self.state.project
        a = self.to_px(proj.listener_x, proj.listener_y)
        b = self.to_px(*speaker_position(dev, spk))
        p.setPen(QPen(theme.faint(70), 1, Qt.DashLine))
        p.drawLine(a, b)
        angle = speaker_angle(proj, dev, spk)
        side = "ahead" if abs(angle) < 1 else ("behind" if abs(angle) > 179 else
                                                 ("right" if angle > 0 else "left"))
        text = f"{speaker_distance(proj, dev, spk):.2f} m,  {abs(angle):.0f}° {side}"
        mid = QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)
        p.setFont(font)
        tw = p.fontMetrics().horizontalAdvance(text) + 10
        box = QRectF(mid.x() - tw / 2, mid.y() - 9, tw, 18)
        p.setPen(Qt.NoPen)
        shade = QColor(theme.BG)
        shade.setAlpha(220)
        p.setBrush(shade)
        p.drawRoundedRect(box, 4, 4)
        p.setPen(QColor(theme.TEXT))
        p.drawText(box, Qt.AlignCenter, text)

    def _paint_speaker(self, p, dev, spk, bold, small, any_solo=False):
        pos = self.to_px(*speaker_position(dev, spk))
        # a speaker is quiet when muted, or when another speaker is solo
        silenced = spk.mute or (any_solo and not spk.solo)
        active = dev.enabled and spk.role != OFF and not silenced
        color = QColor(ROLE_COLORS.get(spk.role, theme.DIM))
        selected = self.state.sel_spk == spk.id
        p.save()
        p.setOpacity(1.0 if dev.enabled else 0.4)
        level = self.levels.get(spk.id, 0.0) if active else 0.0
        if level > 0.02:
            glow = QColor(color)
            glow.setAlpha(int(40 + 110 * level))
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(pos, R + 3 + 13 * level, R + 3 + 13 * level)
        fill = color if active else QColor(theme.OFF_FILL)
        edge = QColor(theme.BADGE_EDGE)
        if spk.id in self.clipped:
            edge = QColor(theme.BAD)
        p.setPen(QPen(edge, 2.5 if spk.id in self.clipped else 1.5))
        p.setBrush(fill)
        if is_sub(spk.role):
            p.drawRoundedRect(QRectF(pos.x() - R - 3, pos.y() - R, 2 * R + 6, 2 * R), 6, 6)
        else:
            p.drawEllipse(pos, R, R)
        if selected or (self.test_role and self.test_role == spk.role and active):
            p.setPen(QPen(QColor(theme.TEXT), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(pos, R + 4, R + 4)
        if spk.solo and dev.enabled and spk.role != OFF:
            # the solo speaker gets a gold ring, so it is clear why the others are quiet
            p.setPen(QPen(QColor(theme.WARN), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(pos, R + 2.5, R + 2.5)
        tag = ROLE_SHORT.get(spk.role, "") or "off"
        if silenced and spk.role != OFF:
            tag = "mute"
        font = QFont(bold)
        if len(tag) >= 4:                        # "mute" and "SUB2" a touch smaller, to sit inside
            font.setPointSizeF(bold.pointSizeF() - 1.5)
        p.setFont(font)
        p.setPen(QColor("#0b1220") if active else QColor(theme.DIM))
        p.drawText(QRectF(pos.x() - R, pos.y() - R, 2 * R, 2 * R), Qt.AlignCenter, tag)
        if dev.kind == "external":
            p.setFont(small)
            p.setPen(QColor(theme.LABEL))
            p.drawText(QRectF(pos.x() - 50, pos.y() + R + 3, 100, 15), Qt.AlignCenter, spk.name)
        p.restore()

    def _paint_edge_arrows(self, p):
        """Four small arrows around the speaker under the mouse. They show that
        its rim can be dragged sideways (left, right) or front to back (up, down)."""
        if self._hover is None:
            return
        spk_id, axis = self._hover
        dev, spk = self.state.project.find_speaker(spk_id)
        if spk is None:
            return
        c = self.to_px(*speaker_position(dev, spk))
        p.save()
        p.setPen(Qt.NoPen)
        for ux, uy, kind in ((-1, 0, "x"), (1, 0, "x"), (0, -1, "y"), (0, 1, "y")):
            live = kind == axis
            arrow = QColor(theme.TEXT)
            arrow.setAlpha(255 if live else 110)
            p.setBrush(arrow)
            tip = R + (14.0 if live else 11.0)
            base = R + 5.0
            half = 5.5 if live else 4.0
            # a triangle pointing away from the badge
            tri = QPolygonF([
                QPointF(c.x() + ux * tip, c.y() + uy * tip),
                QPointF(c.x() + ux * base - uy * half, c.y() + uy * base + ux * half),
                QPointF(c.x() + ux * base + uy * half, c.y() + uy * base - ux * half),
            ])
            p.drawPolygon(tri)
        p.restore()

    def _paint_listener(self, p, font):
        proj = self.state.project
        c = self.to_px(proj.listener_x, proj.listener_y)
        p.setPen(QPen(QColor(theme.BADGE_EDGE), 1.5))
        p.setBrush(QColor(theme.TEXT))
        nose = QPolygonF([QPointF(c.x() - 5, c.y() - 9), QPointF(c.x(), c.y() - 17),
                          QPointF(c.x() + 5, c.y() - 9)])
        p.drawPolygon(nose)
        p.drawEllipse(c, 11, 11)
        p.setFont(font)
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(c.x() - 30, c.y() + 12, 60, 16), Qt.AlignCenter, "You")
