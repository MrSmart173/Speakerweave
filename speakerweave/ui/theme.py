"""Colours and widget styling."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette, QPixmap, QPainter, QIcon, QPen, QBrush
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtWidgets import QAbstractSpinBox, QLineEdit

# The colours in use right now. use() fills them in from the chosen theme.
BG = PANEL = PANEL_2 = FIELD = BORDER = TEXT = DIM = ACCENT = ON_ACCENT = ""
GOOD = WARN = BAD = DEVICE = DEVICE_EXT = DEVICE_EDGE = OFF_FILL = BADGE_EDGE = LABEL = ""
BANNER_BG = BANNER_EDGE = STYLE = ""
DARK = True

# ------------------------------------------------------------------ colour themes
#
# A theme is five colours, the same number a theme on Adobe Color has:
# background, panels, lines, text and accent. Every other colour of the app is
# worked out from those five. The presets were picked with the colour harmony
# rules Adobe Color offers (complementary, analogous, triad, shades and split
# complementary) and checked for readable contrast.

THEME_KEYS = ("bg", "panel", "line", "text", "accent")
THEME_LABELS = {"bg": "Background", "panel": "Panels", "line": "Lines and borders",
                "text": "Text", "accent": "Accent"}
CUSTOM = "custom"

PRESETS = {
    "midnight": ("Midnight", "Default",
                 {"bg": "#14171c", "panel": "#1b1f26", "line": "#2f3643", "text": "#e6e9ef",
                  "accent": "#4da3ff"}),
    "ember": ("Ember", "Complementary: deep teal with warm orange",
              {"bg": "#0f1519", "panel": "#162027", "line": "#2a3a45", "text": "#eef2f3",
               "accent": "#ff8c42"}),
    "forest": ("Forest", "Analogous: greens leaning to lime",
               {"bg": "#0e1511", "panel": "#142019", "line": "#27392d", "text": "#e3efe6",
                "accent": "#8fd65b"}),
    "neon": ("Neon", "Triad: purple, magenta and cyan",
             {"bg": "#120d1c", "panel": "#1b1429", "line": "#352a4d", "text": "#efe8ff",
              "accent": "#ff4fa8"}),
    "amber": ("Amber", "Shades: warm browns with amber",
              {"bg": "#15120d", "panel": "#1f1a12", "line": "#3a3122", "text": "#f4ead6",
               "accent": "#ffb238"}),
    "daylight": ("Daylight", "Split complementary, light",
                 {"bg": "#eef1f5", "panel": "#ffffff", "line": "#d3d9e2", "text": "#1d2330",
                  "accent": "#2f6fdb"}),
}
DEFAULT_THEME = "midnight"

# the original look, kept exactly as it was
_MIDNIGHT_EXACT = {
    "PANEL_2": "#232831", "FIELD": "#12151a", "DIM": "#8d96a5", "ON_ACCENT": "#0b1220",
    "DEVICE": "#2a3040", "DEVICE_EXT": "#20242d", "DEVICE_EDGE": "#56607a", "OFF_FILL": "#3a404c",
    "BADGE_EDGE": "#0d0f13", "LABEL": "#c9d0dc", "BANNER_BG": "#3a2a14", "BANNER_EDGE": "#6b4a1c",
}


def _rgb(color: str) -> tuple:
    c = QColor(color)
    return c.red(), c.green(), c.blue()


def mix(a: str, b: str, t: float) -> str:
    """The colour t of the way from a to b."""
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    return "#{:02x}{:02x}{:02x}".format(round(ra + (rb - ra) * t), round(ga + (gb - ga) * t),
                                        round(ba + (bb - ba) * t))


def luminance(color: str) -> float:
    def lin(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(color)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio, 1 to 21. 4.5 or more reads comfortably."""
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def clean_colors(colors) -> dict:
    """Five valid colours, gaps filled from the original look."""
    base = dict(PRESETS[DEFAULT_THEME][2])
    for key in THEME_KEYS:
        value = (colors or {}).get(key) if isinstance(colors, dict) else None
        if isinstance(value, str) and QColor(value).isValid():
            base[key] = QColor(value).name()
    return base


def palette(colors: dict) -> dict:
    """Every colour the app uses, worked out from the five theme colours."""
    c = clean_colors(colors)
    bg, panel, line, text, accent = (c[k] for k in THEME_KEYS)
    dark = luminance(bg) < 0.35
    warn = "#ffb454" if dark else "#a85d00"
    pal = {
        "BG": bg, "PANEL": panel, "BORDER": line, "TEXT": text, "ACCENT": accent,
        "PANEL_2": mix(panel, text, 0.05),
        "FIELD": mix(bg, "#000000", 0.12) if dark else mix(panel, "#ffffff", 0.7),
        "DIM": mix(text, panel, 0.44 if dark else 0.40),
        "ON_ACCENT": "#0b1220" if luminance(accent) > 0.28 else "#ffffff",
        "GOOD": "#5fd38a" if dark else "#1f8f4e",
        "WARN": warn,
        "BAD": "#ff6b6b" if dark else "#d64545",
        "DEVICE": mix(mix(panel, accent, 0.10), text, 0.06),
        "DEVICE_EXT": mix(panel, text, 0.03),
        "DEVICE_EDGE": mix(line, text, 0.25),
        "OFF_FILL": mix(panel, text, 0.16),
        "BADGE_EDGE": "#0d0f13" if dark else mix(text, panel, 0.25),
        "LABEL": mix(text, panel, 0.12),
        "BANNER_BG": mix(panel, warn, 0.14),
        "BANNER_EDGE": mix(panel, warn, 0.40),
        "DARK": dark,
    }
    if c == PRESETS[DEFAULT_THEME][2]:
        pal.update(_MIDNIGHT_EXACT)
    return pal


def colors_for(settings) -> dict:
    """The five colours chosen in the settings."""
    name = getattr(settings, "theme", DEFAULT_THEME)
    if name == CUSTOM:
        return clean_colors(getattr(settings, "custom_colors", {}))
    return dict(PRESETS.get(name, PRESETS[DEFAULT_THEME])[2])


def readable(color: str, minimum: float = 3.2) -> str:
    """color, made lighter on a dark theme or darker on a light one until it
    stands out clearly against the panels (contrast of at least minimum)."""
    target = "#ffffff" if DARK else "#000000"
    for _ in range(12):
        if contrast(color, PANEL) >= minimum:
            break
        color = mix(color, target, 0.15)
    return color


def faint(alpha: int) -> QColor:
    """A see through line in the text colour (for grids and guides)."""
    c = QColor(TEXT)
    c.setAlpha(alpha if DARK else min(255, int(alpha * 1.3)))
    return c


def _style() -> str:
    return f"""
QWidget {{ color: {TEXT}; font-size: 13px; }}
QMainWindow, QDialog {{ background: {BG}; }}
QToolTip {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}
QGroupBox {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px;
             margin-top: 18px; padding: 10px 10px 10px 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 4px; top: 0px; padding: 0 4px;
                    color: {DIM}; font-weight: 600; }}
QPushButton {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 6px;
               padding: 5px 12px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {FIELD}; }}
QPushButton:disabled {{ color: {DIM}; border-color: {PANEL_2}; }}
QPushButton:checked {{ background: {ACCENT}; color: {ON_ACCENT}; border-color: {ACCENT}; }}
QPushButton#primary {{ background: {ACCENT}; color: {ON_ACCENT}; border-color: {ACCENT};
                       font-weight: 700; padding: 7px 18px; }}
QPushButton#primary:checked {{ background: {BAD}; border-color: {BAD}; color: #ffffff; }}
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{ background: {FIELD}; border: 1px solid {BORDER};
               border-radius: 6px; padding: 4px 6px; selection-background-color: {ACCENT};
               selection-color: {ON_ACCENT}; }}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {DIM}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: {PANEL_2}; border: 1px solid {BORDER};
               selection-background-color: {ACCENT}; selection-color: {ON_ACCENT}; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 8px; background: {BG}; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {DIM}; padding: 7px 14px; border: none;
                border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTreeWidget, QTableWidget, QListWidget {{ background: {PANEL}; border: 1px solid {BORDER};
               border-radius: 8px; outline: none; }}
QTreeWidget::item {{ padding: 3px 2px; }}
QTreeWidget::item:selected {{ background: {PANEL_2}; color: {TEXT}; }}
QTreeWidget::indicator {{ width: 14px; height: 14px; border: 1px solid {DIM}; border-radius: 4px;
                          background: {FIELD}; }}
QTreeWidget::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QHeaderView::section {{ background: {PANEL}; color: {DIM}; border: none; padding: 4px; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 14px; height: 14px; margin: -5px 0;
                              border-radius: 7px; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {DIM}; border-radius: 4px;
                        background: {FIELD}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QLabel#dim {{ color: {DIM}; }}
QLabel#banner {{ background: {BANNER_BG}; color: {WARN}; border: 1px solid {BANNER_EDGE};
                 border-radius: 6px; padding: 6px 10px; }}
QLabel#title {{ font-size: 16px; font-weight: 700; }}
QLabel#subtitle {{ font-weight: 700; }}
QLabel#warn {{ color: {WARN}; }}
QPushButton#danger {{ color: {BAD}; border-color: {BAD}; }}
QPushButton#mapRow {{ padding: 5px 8px; }}
QPushButton#danger:hover {{ background: {BAD}; color: #ffffff; }}
QStatusBar {{ background: {PANEL}; color: {DIM}; }}
QSplitter::handle {{ background: {BG}; width: 6px; }}
QMenu {{ background: {PANEL_2}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 5px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT}; color: {ON_ACCENT}; }}
QMenu::item:disabled {{ color: {DIM}; }}
"""


def use(colors: dict) -> None:
    """Makes colors the current theme for everything drawn from now on."""
    globals().update(palette(colors))
    globals()["STYLE"] = _style()


use(PRESETS[DEFAULT_THEME][2])


def apply(app, colors: dict = None) -> None:
    if colors is not None:
        use(colors)
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(FIELD))
    pal.setColor(QPalette.AlternateBase, QColor(PANEL))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(PANEL_2))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor(ON_ACCENT))
    pal.setColor(QPalette.ToolTipBase, QColor(PANEL_2))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.PlaceholderText, QColor(DIM))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(DIM))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor(DIM))
    app.setPalette(pal)
    app.setStyleSheet(STYLE)


# ------------------------------------------------------------------ Adobe Color

def parse_hex_list(text: str) -> list:
    """Every colour code in a piece of text, such as the five codes copied
    from a theme on Adobe Color ("#1A2B3C, 4D5E6F ...")."""
    import re
    found = re.findall(r"(?<![0-9A-Fa-f])#?([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})(?![0-9A-Fa-f])", text or "")
    out = []
    for code in found:
        if len(code) == 3:
            code = "".join(ch * 2 for ch in code)
        out.append("#" + code.lower())
    return out


def read_ase(path: str) -> list:
    """The colours in an Adobe Swatch Exchange file (.ase), the file Adobe
    Color and other Adobe apps save themes in."""
    import struct
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:4] != b"ASEF":
        raise ValueError("This is not an Adobe swatch file (.ase).")
    count = struct.unpack(">I", data[8:12])[0]
    pos, out = 12, []
    for _ in range(count):
        if pos + 6 > len(data):
            break
        kind, length = struct.unpack(">HI", data[pos:pos + 6])
        body = data[pos + 6:pos + 6 + length]
        pos += 6 + length
        if kind != 0x0001 or len(body) < 2:
            continue                                  # a group start or end
        name_len = struct.unpack(">H", body[:2])[0]
        at = 2 + name_len * 2
        model = body[at:at + 4]
        at += 4
        if model == b"RGB ":
            r, g, b = struct.unpack(">3f", body[at:at + 12])
        elif model == b"Gray":
            r = g = b = struct.unpack(">f", body[at:at + 4])[0]
        elif model == b"CMYK":
            cc, m, y, k = struct.unpack(">4f", body[at:at + 16])
            r, g, b = (1 - cc) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)
        elif model == b"LAB ":
            lab_l, lab_a, lab_b = struct.unpack(">3f", body[at:at + 12])
            r, g, b = _lab_to_rgb(lab_l * 100.0, lab_a, lab_b)
        else:
            continue
        out.append("#{:02x}{:02x}{:02x}".format(*(max(0, min(255, round(v * 255))) for v in (r, g, b))))
    return out


def _lab_to_rgb(l, a, b):
    fy = (l + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200

    def inv(t):
        return t ** 3 if t ** 3 > 0.008856 else (t - 16 / 116) / 7.787
    x, y, z = 0.95047 * inv(fx), 1.0 * inv(fy), 1.08883 * inv(fz)
    lin = (3.2406 * x - 1.5372 * y - 0.4986 * z, -0.9689 * x + 1.8758 * y + 0.0415 * z,
           0.0557 * x - 0.2040 * y + 1.0570 * z)
    return tuple(12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055 for v in lin)


def colors_from_swatches(codes: list, light: bool = False) -> dict:
    """Turns the colours of an Adobe Color theme into the five theme colours.
    For a dark look the darkest colour becomes the background (deepened when
    needed so text stays readable) and the lightest the text. For a light look
    it is the other way round. The most colourful of the rest is the accent,
    and the last one tints the lines. Every colour can be changed afterwards."""
    codes = list(dict.fromkeys(QColor(c).name() for c in codes if QColor(c).isValid()))
    if not codes:
        raise ValueError("No colour codes found.")
    order = sorted(codes, key=luminance, reverse=light)
    bg, text = order[0], order[-1] if len(order) > 1 else ("#1d2330" if light else "#e6e9ef")
    rest = order[1:-1]
    for _ in range(12):                           # keep the hue, fix the brightness
        if (luminance(bg) > 0.82) if light else (luminance(bg) < 0.03):
            break
        bg = mix(bg, "#ffffff" if light else "#000000", 0.25)
    for _ in range(12):
        if contrast(text, bg) >= 7.0:
            break
        text = mix(text, "#000000" if light else "#ffffff", 0.25)
    panel = mix(bg, "#ffffff", 0.6) if light else mix(bg, text, 0.06)

    def colourful(c):
        q = QColor(c)
        return q.hsvSaturationF() * q.valueF()
    accent = max(rest, key=colourful) if rest else ("#2f6fdb" if light else "#4da3ff")
    for _ in range(12):
        if contrast(accent, panel) >= 3.0:
            break
        accent = mix(accent, "#000000" if light else "#ffffff", 0.15)
    rest = [c for c in rest if c != accent]
    line = mix(panel, text, 0.15)
    if rest:
        line = mix(line, rest[-1], 0.25)
    return {"bg": bg, "panel": panel, "line": line, "text": text, "accent": accent}



NUMBER_BOX_INSET = 7      # pixels between the left edge of a number box and its digits


def pad_number_boxes(root) -> None:
    """Moves the digits of every number box under root away from its left edge.
    The style sheet padding does not reach the text inside a number box, so the
    margin is set on the text field itself."""
    for spin in root.findChildren(QAbstractSpinBox):
        field = spin.findChild(QLineEdit)
        if field is not None:
            field.setTextMargins(NUMBER_BOX_INSET, 0, 0, 0)


def app_pixmap(size: int = 128) -> QPixmap:
    """The app icon, drawn in code so no image files are needed."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 128.0, size / 128.0)
    p.setBrush(QColor("#1b1f26"))       # the icon keeps its colours in every theme
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(4, 4, 120, 120), 26, 26)
    spots = [(-34, -26, "#4da3ff"), (0, -38, "#f5d76e"), (34, -26, "#ff6b6b"),
             (-38, 22, "#4dd0c8"), (38, 22, "#ff9f5a")]
    p.setPen(QPen(QColor("#2f3643"), 3))
    for x, y, _ in spots:
        p.drawLine(QPointF(64, 74), QPointF(64 + x, 64 + y))
    p.setPen(Qt.NoPen)
    for x, y, color in spots:
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(64 + x, 64 + y), 12, 12)
    p.setBrush(QBrush(QColor("#e6e9ef")))
    p.drawEllipse(QPointF(64, 74), 10, 10)
    p.end()
    return pix


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(app_pixmap(size))
    return icon
