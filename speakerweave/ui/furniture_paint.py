"""Drawing desks and sim rigs on the room map, from above, in the colours of the theme."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen, QPolygonF

from .. import furniture
from . import theme


def _c(t: float, base: str = None) -> QColor:
    """A grey between the panels and the text: 0 is the panel, 1 the text."""
    return QColor(theme.mix(base or theme.PANEL, theme.TEXT, t))


def _pen(color: QColor, width: float = 1.0) -> QPen:
    pen = QPen(color, width)
    pen.setCosmetic(True)               # in pixels, whatever the zoom
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _rect(shape) -> QRectF:
    _k, x0, y0, x1, y1 = shape
    return QRectF(QPointF(x0, y0), QPointF(x1, y1)).normalized()


def paint(p, f, scale: float, at: QPointF, selected: bool) -> None:
    """Draws one piece with its middle at the pixel at, scale pixels to the metre."""
    p.save()
    p.translate(at)
    p.rotate(f.rotation)
    p.scale(scale, scale)
    if f.is_rig:
        _paint_rig(p, f)
    else:
        _paint_desk(p, f)
    if selected:
        pen = _pen(QColor(theme.ACCENT), 1.6)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        for poly in ([furniture.desk_outline(f)] if not f.is_rig else [_rig_bounds(f)]):
            p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in poly]))
    p.restore()


def _rig_bounds(f) -> list:
    xs, ys = [], []
    for poly in furniture.local_outlines(f):
        for x, y in poly:
            xs.append(x)
            ys.append(y)
    pad = 0.03
    return [(min(xs) - pad, min(ys) - pad), (max(xs) + pad, min(ys) - pad),
            (max(xs) + pad, max(ys) + pad), (min(xs) - pad, max(ys) + pad)]


# ------------------------------------------------------------------ desks
def _paint_desk(p, f) -> None:
    poly = QPolygonF([QPointF(x, y) for x, y in furniture.desk_outline(f)])
    p.setPen(_pen(_c(0.42), 1.3))
    p.setBrush(_c(0.13))
    p.drawPolygon(poly)
    # the edge you sit at, a little stronger, so the way the desk faces shows
    w, d = f.width / 2.0, f.depth / 2.0
    p.setPen(_pen(_c(0.6), 2.0))
    if f.kind == "desk":
        p.drawLine(QPointF(-w + 0.02, d), QPointF(w - 0.02, d))
    elif f.kind == "desk_u":
        side = f.wing_depth
        p.drawLine(QPointF(-w + side, d), QPointF(w - side, d))
    else:
        side, cut = f.wing_depth, min(0.25, f.wing_depth * 0.5, f.wing * 0.5)
        sign = 1.0 if f.corner_side == "right" else -1.0
        p.drawPolyline(QPolygonF([QPointF(-sign * (w - 0.02), d), QPointF(sign * (w - side - cut), d),
                                  QPointF(sign * (w - side), d + cut)]))


# ------------------------------------------------------------------ rigs
def _extrusion(p, rect: QRectF) -> None:
    """A length of aluminium extrusion seen from above, with the slot along it."""
    p.setPen(_pen(_c(0.62), 0.8))
    p.setBrush(_c(0.38))
    p.drawRect(rect)
    p.setPen(_pen(_c(0.18), 1.0))
    if rect.width() >= rect.height():
        y = rect.center().y()
        p.drawLine(QPointF(rect.left() + 0.01, y), QPointF(rect.right() - 0.01, y))
    else:
        x = rect.center().x()
        p.drawLine(QPointF(x, rect.top() + 0.01), QPointF(x, rect.bottom() - 0.01))


def _box(p, rect: QRectF, shade: float, radius: float = 0.012, edge: float = 0.5) -> None:
    p.setPen(_pen(_c(edge), 0.9))
    p.setBrush(_c(shade, theme.BG))
    p.drawRoundedRect(rect, radius, radius)


def _seat(p, shape) -> None:
    _k, cx, y0, y1 = shape
    shell = QRectF(cx - 0.26, y0, 0.52, y1 - y0)
    p.setPen(_pen(_c(0.45), 1.0))
    p.setBrush(_c(0.10, theme.BG))
    p.drawRoundedRect(shell, 0.08, 0.08)
    # the cushion between the side bolsters
    cushion = QRectF(cx - 0.165, y0 + 0.05, 0.33, (y1 - y0) - 0.24)
    p.setPen(_pen(_c(0.30), 0.9))
    p.setBrush(_c(0.18, theme.BG))
    p.drawRoundedRect(cushion, 0.05, 0.05)
    # the top of the backrest, with the slots for the harness
    head = QRectF(cx - 0.14, y1 - 0.16, 0.28, 0.12)
    p.setBrush(_c(0.14, theme.BG))
    p.drawRoundedRect(head, 0.04, 0.04)
    p.setBrush(_c(0.05, theme.BG))
    for x in (-0.07, 0.04):
        p.drawRoundedRect(QRectF(cx + x, y1 - 0.125, 0.03, 0.05), 0.01, 0.01)


def _wheel(p, shape) -> None:
    _k, cx, cy, rx, ry = shape
    rim = QPen(_c(0.30, theme.BG), 0.028)
    rim.setCapStyle(Qt.RoundCap)
    p.setPen(rim)
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(cx, cy), rx, ry)
    p.setPen(_pen(_c(0.55), 0.8))
    p.drawEllipse(QPointF(cx, cy), rx + 0.014, ry + 0.014)
    _box(p, QRectF(cx - 0.05, cy - 0.025, 0.10, 0.05), 0.20, 0.015)      # the hub


def _yoke(p, shape) -> None:
    _k, cx, cy, rx, ry = shape
    path = QPainterPath()
    path.moveTo(cx - rx, cy - ry)
    path.lineTo(cx - rx, cy + ry * 0.4)
    path.lineTo(cx + rx, cy + ry * 0.4)
    path.lineTo(cx + rx, cy - ry)
    pen = QPen(_c(0.30, theme.BG), 0.03)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    _box(p, QRectF(cx - 0.04, cy - 0.02, 0.08, 0.05), 0.20, 0.012)


def _knob(p, shape) -> None:
    _k, cx, cy, r = shape
    p.setPen(_pen(_c(0.2, theme.BG), 0.9))
    p.setBrush(_c(0.85))
    p.drawEllipse(QPointF(cx, cy), r, r)


def _paint_rig(p, f) -> None:
    parts = furniture.rig_parts(f)
    for shape in parts.get("frame", []):
        _extrusion(p, _rect(shape))
    for shape in parts.get("deck", []):
        _extrusion(p, _rect(shape))
    for shape in parts.get("mount", []):
        _extrusion(p, _rect(shape))
    for shape in parts.get("pedal_plate", []):
        _box(p, _rect(shape), 0.22, 0.01, 0.45)
    for shape in parts.get("pedals", []):
        _box(p, _rect(shape), 0.42, 0.008, 0.7)
    for shape in parts.get("seat", []):
        _seat(p, shape)
    for name in ("wheelbase", "throttle", "stick", "shifter", "handbrake", "yoke", "wheel"):
        for shape in parts.get(name, []):
            kind = shape[0]
            if kind == "rect":
                shade = 0.14 if name in ("wheelbase", "throttle", "shifter", "stick") else 0.30
                _box(p, _rect(shape), shade)
            elif kind == "wheel":
                _wheel(p, shape)
            elif kind == "yoke":
                _yoke(p, shape)
            elif kind == "knob":
                _knob(p, shape)
