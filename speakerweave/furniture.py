"""Desks and simulator rigs on the room map.

Three desks: a plain rectangle, a U (a long top with sides that come out towards you) and a
corner desk (an L). Two rigs, seen from above: a racing cockpit of aluminium extrusion with a
seat, wheelbase, wheel, pedals and, if you like, a shifter on either side and a handbrake;
and a flight cockpit with rudder pedals and a side stick and throttle, a centre stick or a
yoke. They are only drawn while Desks and rigs is switched on in the settings.

Everything here is in metres, in the room's own directions: x to the right, y towards the
back of the room (the front is up on the map). A piece has its own directions too: its
front (where the screen goes) is its -y, and you sit on its +y side."""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field

DESKS = {"desk": "Rectangle desk", "desk_u": "U shaped desk", "desk_corner": "Corner desk"}
RIGS = {"racing": "Racing rig", "flight": "Flight rig"}
KINDS = {**DESKS, **RIGS}
FLIGHT_CONTROLS = {"hotas": "Side stick and throttle", "centre": "Centre stick and throttle",
                   "yoke": "Yoke and throttle"}
SIDES = ("left", "right")

# a rig's size: aluminium extrusion 40 x 80 mm, a frame 0.62 m wide and 1.55 m long
RIG_W, RIG_L = 0.62, 1.55
RAIL = 0.08
HEAD_FROM_BACK = 0.16           # where your head is in the seat, from the back of the frame


@dataclass
class Furniture:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    kind: str = "desk"
    x: float = 0.0              # the middle of the piece, metres
    y: float = 0.0
    rotation: float = 0.0       # degrees, clockwise; 0 faces the front of the room
    width: float = 1.6          # desks: side to side
    depth: float = 0.75         # desks: front to back
    wing: float = 0.7           # U and corner desks: how far a side comes out towards you
    wing_depth: float = 0.5     # U and corner desks: how wide a side is
    corner_side: str = "right"  # corner desk: the side the return is on
    shifter: bool = True        # racing rig
    shifter_side: str = "right"
    handbrake: bool = False     # racing rig: beside the shifter, behind it
    controls: str = "hotas"     # flight rig: see FLIGHT_CONTROLS

    @property
    def title(self) -> str:
        return KINDS.get(self.kind, "Desk")

    @property
    def is_rig(self) -> bool:
        return self.kind in RIGS


def _num(value, low, high, default):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return default if not math.isfinite(v) else min(high, max(low, v))


def clean(f: Furniture) -> Furniture:
    """Every value in range, so a hand edited setup cannot break the map."""
    if f.kind not in KINDS:
        f.kind = "desk"
    f.x, f.y = _num(f.x, -50, 50, 0.0), _num(f.y, -50, 50, 0.0)
    f.rotation = ((_num(f.rotation, -1e6, 1e6, 0.0) + 180.0) % 360.0) - 180.0
    f.width = _num(f.width, 0.4, 4.0, 1.6)
    f.depth = _num(f.depth, 0.3, 1.5, 0.75)
    f.wing = _num(f.wing, 0.2, 2.5, 0.7)
    f.wing_depth = _num(f.wing_depth, 0.2, 1.2, 0.5)
    f.wing_depth = min(f.wing_depth, f.width / 2.0 - 0.05) if f.kind == "desk_u" else f.wing_depth
    f.corner_side = f.corner_side if f.corner_side in SIDES else "right"
    f.shifter_side = f.shifter_side if f.shifter_side in SIDES else "right"
    f.shifter, f.handbrake = bool(f.shifter), bool(f.handbrake)
    f.controls = f.controls if f.controls in FLIGHT_CONTROLS else "hotas"
    return f


# ------------------------------------------------------------------ directions
def to_world(f: Furniture, lx: float, ly: float) -> tuple:
    """A point of the piece (its own metres) in the room."""
    a = math.radians(f.rotation)
    c, s = math.cos(a), math.sin(a)
    return f.x + lx * c - ly * s, f.y + lx * s + ly * c


def to_local(f: Furniture, x: float, y: float) -> tuple:
    a = math.radians(f.rotation)
    c, s = math.cos(a), math.sin(a)
    dx, dy = x - f.x, y - f.y
    return dx * c + dy * s, -dx * s + dy * c


def seat_local(f: Furniture) -> tuple:
    """Where you are, in the piece's own metres: in a rig's seat, or at a desk's front edge."""
    if f.is_rig:
        return 0.0, RIG_L / 2.0 - HEAD_FROM_BACK
    if f.kind == "desk_u":
        return 0.0, f.depth / 2.0 + min(f.wing, 0.9) * 0.55
    if f.kind == "desk_corner":
        side = 1.0 if f.corner_side == "right" else -1.0
        return -side * f.wing_depth * 0.35, f.depth / 2.0 + 0.4
    return 0.0, f.depth / 2.0 + 0.4


def seat(f: Furniture) -> tuple:
    return to_world(f, *seat_local(f))


def place_for(f: Furniture, listener_x: float, listener_y: float) -> None:
    """Puts a new piece so you sit at it (facing the front of the room)."""
    f.rotation = 0.0
    sx, sy = seat_local(f)
    f.x, f.y = round(listener_x - sx, 3), round(listener_y - sy, 3)


def new(kind: str, listener_x: float = 0.0, listener_y: float = 0.0) -> Furniture:
    f = Furniture(kind=kind if kind in KINDS else "desk")
    if f.kind == "desk_u":
        f.width, f.depth, f.wing, f.wing_depth = 2.0, 0.7, 0.8, 0.55
    elif f.kind == "desk_corner":
        f.width, f.depth, f.wing, f.wing_depth = 1.6, 0.7, 0.9, 0.6
    clean(f)
    place_for(f, listener_x, listener_y)
    return f


# ------------------------------------------------------------------ shapes
def _rect(x0, y0, x1, y1) -> list:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def desk_outline(f: Furniture) -> list:
    """The desk top, as one polygon in the desk's own metres."""
    w, d = f.width / 2.0, f.depth / 2.0
    if f.kind == "desk_u":
        side, out = f.wing_depth, f.wing
        return [(-w, -d), (w, -d), (w, d + out), (w - side, d + out), (w - side, d),
                (-w + side, d), (-w + side, d + out), (-w, d + out)]
    if f.kind == "desk_corner":
        side, out = f.wing_depth, f.wing
        cut = min(0.25, side * 0.5, out * 0.5)          # the angled inside corner
        pts = [(-w, -d), (w, -d), (w, d + out), (w - side, d + out), (w - side, d + cut),
               (w - side - cut, d), (-w, d)]
        if f.corner_side == "left":
            pts = [(-x, y) for x, y in reversed(pts)]
        return pts
    return _rect(-w, -d, w, d)


def rig_parts(f: Furniture) -> dict:
    """The parts of a rig, in its own metres: name -> list of shapes. A shape is
    ("rect", x0, y0, x1, y1), ("ellipse", cx, cy, rx, ry) or ("poly", [(x, y), ...])."""
    half_w, half_l = RIG_W / 2.0, RIG_L / 2.0
    front, back = -half_l, half_l
    parts = {
        # the base frame: two long rails, cross members at the front, back and under the seat
        "frame": [("rect", -half_w, front, -half_w + RAIL, back),
                  ("rect", half_w - RAIL, front, half_w, back),
                  ("rect", -half_w + RAIL, front, half_w - RAIL, front + RAIL / 2),
                  ("rect", -half_w + RAIL, back - RAIL / 2, half_w - RAIL, back),
                  ("rect", -half_w + RAIL, front + 0.98, half_w - RAIL, front + 0.98 + RAIL / 2)],
        "pedal_plate": [("rect", -0.21, front + 0.06, 0.21, front + 0.30)],
        "seat": [("seat", 0.0, front + 0.92, back - 0.03)],
    }
    seat_front = front + 0.92
    if f.kind == "racing":
        parts["deck"] = [("rect", -half_w + RAIL, front + 0.46, half_w - RAIL, front + 0.56)]
        parts["wheelbase"] = [("rect", -0.075, front + 0.38, 0.075, front + 0.62)]
        parts["wheel"] = [("wheel", 0.0, front + 0.66, 0.165, 0.05)]
        parts["pedals"] = [("rect", x - 0.03, front + 0.10, x + 0.03, front + 0.26)
                           for x in (-0.12, 0.0, 0.12)]
        side = 1.0 if f.shifter_side == "right" else -1.0

        def span(a, b):                      # from a to b sideways, on the shifter's side
            return tuple(sorted((side * a, side * b)))
        if f.shifter or f.handbrake:
            # a mount bolted to the rail beside the seat: an arm out to the side and a plate
            back_end = seat_front + (0.30 if f.handbrake else 0.08)
            ax0, ax1 = span(half_w - RAIL / 2, half_w + 0.20)
            px0, px1 = span(half_w + 0.07, half_w + 0.20)
            parts["mount"] = [("rect", ax0, seat_front - 0.03, ax1, seat_front + 0.03),
                              ("rect", px0, seat_front - 0.09, px1, back_end)]
        cx = side * (half_w + 0.135)
        if f.shifter:
            parts["shifter"] = [("rect", cx - 0.045, seat_front - 0.075, cx + 0.045, seat_front + 0.035),
                                ("knob", cx, seat_front - 0.02, 0.024)]
        if f.handbrake:
            # its base, and the lever leaning back towards you
            y0 = seat_front + (0.07 if f.shifter else -0.05)
            parts["handbrake"] = [("rect", cx - 0.035, y0, cx + 0.035, y0 + 0.09),
                                  ("rect", cx - 0.011, y0 + 0.03, cx + 0.011, y0 + 0.21)]
    else:
        parts["pedals"] = [("rect", x - 0.045, front + 0.09, x + 0.045, front + 0.27)
                           for x in (-0.12, 0.12)]
        parts["pedals"].append(("rect", -0.15, front + 0.17, 0.15, front + 0.19))   # the linkage
        if f.controls == "yoke":
            parts["deck"] = [("rect", -half_w + RAIL, front + 0.46, half_w - RAIL, front + 0.56)]
            parts["yoke"] = [("rect", -0.03, front + 0.40, 0.03, front + 0.70),
                             ("yoke", 0.0, front + 0.72, 0.15, 0.05)]
            parts["throttle"] = [("rect", 0.12, front + 0.44, 0.24, front + 0.58)]
        else:
            if f.controls == "centre":
                parts["stick"] = [("rect", -0.05, seat_front - 0.18, 0.05, seat_front - 0.08),
                                  ("knob", 0.0, seat_front - 0.13, 0.032)]
            else:
                cx = half_w + 0.12
                parts["mount"] = [("rect", half_w - RAIL / 2, seat_front + 0.02, half_w + 0.22,
                                   seat_front + 0.08),
                                  ("rect", -half_w - 0.22, seat_front + 0.02, -half_w + RAIL / 2,
                                   seat_front + 0.08)]
                parts["stick"] = [("rect", cx - 0.06, seat_front - 0.06, cx + 0.06, seat_front + 0.07),
                                  ("knob", cx, seat_front, 0.032)]
            tx = -(half_w + 0.12)
            parts["throttle"] = [("rect", tx - 0.07, seat_front - 0.07, tx + 0.07, seat_front + 0.08),
                                 ("rect", tx - 0.04, seat_front - 0.05, tx - 0.01, seat_front + 0.05),
                                 ("rect", tx + 0.01, seat_front - 0.05, tx + 0.04, seat_front + 0.05)]
    return parts


def _shape_points(shape) -> list:
    kind = shape[0]
    if kind == "rect":
        return _rect(*shape[1:5])
    if kind in ("ellipse", "wheel", "yoke"):
        _k, cx, cy, rx, ry = shape
        return [(cx + rx * math.cos(t * math.pi / 8), cy + ry * math.sin(t * math.pi / 8))
                for t in range(16)]
    if kind == "knob":
        _k, cx, cy, r = shape
        return [(cx + r * math.cos(t * math.pi / 4), cy + r * math.sin(t * math.pi / 4)) for t in range(8)]
    if kind == "seat":
        _k, cx, y0, y1 = shape
        return _rect(cx - 0.26, y0, cx + 0.26, y1)
    return list(shape[1])


def local_outlines(f: Furniture) -> list:
    if not f.is_rig:
        return [desk_outline(f)]
    return [_shape_points(shape) for shapes in rig_parts(f).values() for shape in shapes]


def outlines(f: Furniture) -> list:
    """Every polygon of the piece in room metres (for clicking on it and fitting the map)."""
    return [[to_world(f, x, y) for x, y in poly] for poly in local_outlines(f)]


def _inside(poly: list, x: float, y: float) -> bool:
    hit = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            hit = not hit
        j = i
    return hit


def contains(f: Furniture, x: float, y: float, margin: float = 0.0) -> bool:
    lx, ly = to_local(f, x, y)
    if f.is_rig:
        # the whole frame counts, so a click between two rails still finds the rig
        half_w, half_l = RIG_W / 2.0 + 0.25 + margin, RIG_L / 2.0 + margin
        return abs(lx) <= half_w and abs(ly) <= half_l
    poly = desk_outline(f)
    if _inside(poly, lx, ly):
        return True
    if margin > 0:
        return any(_inside(poly, lx + dx, ly + dy) for dx, dy in
                   ((margin, 0), (-margin, 0), (0, margin), (0, -margin)))
    return False


def corners(f: Furniture) -> list:
    """The outer corners of the piece in room metres, to keep it in view on the map."""
    pts = [p for poly in outlines(f) for p in poly]
    return pts
