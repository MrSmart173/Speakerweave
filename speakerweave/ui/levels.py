"""Level meters, like a mixing desk: one block for the sound coming from the
PC, one block for every output, with a labelled bar for each channel.

Only painting happens here (about 30 times a second while the sound runs), the
levels themselves are measured by the engine as it mixes.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QSizePolicy, QWidget

from ..model import OFF, ROLE_COLORS, ROLE_SHORT
from . import theme

DB_LOW = -60.0
FALL_DB_PER_S = 30.0        # how fast a bar drops when the sound gets quieter
HOLD_S = 1.5                # how long the peak line stays up
BAR_W = 14
GAP = 6
SCALE_W = 26
TICKS = (0, -6, -12, -18, -24, -30, -36, -42, -48, -60)


def to_db(level: float) -> float:
    return 20.0 * math.log10(level) if level > 1e-6 else DB_LOW


def _colour(db: float) -> QColor:
    if db > -6:
        return QColor("#ff5b5b")
    if db > -18:
        return QColor("#f5c84b")
    return QColor("#4fd17f")


class MeterBlock(QWidget):
    """One box: a title, a dB scale and one bar per channel."""

    def __init__(self, title: str, subtitle: str = ""):
        super().__init__()
        self.title = title
        self.subtitle = subtitle
        self.labels: list = []          # (text, colour) per bar
        self.levels: list = []          # shown level per bar, in dB
        self.peaks: list = []           # peak line per bar, in dB
        self._peak_time: list = []
        self.step = BAR_W + GAP             # from one bar to the next, wide enough for its label
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setMinimumHeight(150)

    def set_channels(self, labels: list) -> None:
        if [t for t, _ in labels] != [t for t, _ in self.labels]:
            self.labels = list(labels)
            n = len(labels)
            self.levels = [DB_LOW] * n
            self.peaks = [DB_LOW] * n
            self._peak_time = [0.0] * n
            bold = QFont(self.font())
            bold.setPointSizeF(7.5)
            bold.setBold(True)
            widest = max([QFontMetrics(bold).horizontalAdvance(t) for t, _ in labels] + [0])
            self.step = max(BAR_W + GAP, widest + 6)
            width = SCALE_W + 18 + (n - 1) * self.step + BAR_W + 14
            self.setFixedWidth(max(width, 128))
            self.update()

    def feed(self, values, dt: float) -> bool:
        """values: the newest peak of each channel (0 to 1). Returns True if the
        picture changed."""
        changed = False
        now = time.monotonic()
        for i in range(len(self.levels)):
            new = to_db(float(values[i])) if i < len(values) else DB_LOW
            shown = max(new, self.levels[i] - FALL_DB_PER_S * dt)
            shown = max(shown, DB_LOW)
            if abs(shown - self.levels[i]) > 0.05:
                self.levels[i] = shown
                changed = True
            if new >= self.peaks[i] or now - self._peak_time[i] > HOLD_S:
                if abs(new - self.peaks[i]) > 0.05:
                    changed = True
                self.peaks[i] = max(new, DB_LOW)
                self._peak_time[i] = now
        return changed

    def loudest(self) -> float:
        return max(self.peaks) if self.peaks else DB_LOW

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor(theme.PANEL))
        p.drawRoundedRect(r, 8, 8)

        title = QFont(self.font())
        title.setBold(True)
        title.setPointSizeF(9)
        p.setFont(title)
        p.setPen(QColor(theme.TEXT))
        head = QRectF(10, 6, self.width() - 20, 16)
        p.drawText(head, Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(self.title, Qt.ElideRight, int(head.width())))
        small = QFont(self.font())
        small.setPointSizeF(7.5)
        p.setFont(small)
        p.setPen(QColor(theme.DIM))
        loud = self.loudest()
        reading = "silent" if loud <= DB_LOW + 0.5 else f"{loud:.1f} dB"
        sub = f"{self.subtitle}   {reading}" if self.subtitle else reading
        p.drawText(QRectF(10, 22, self.width() - 20, 14), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(sub, Qt.ElideRight, self.width() - 20))

        top, bottom = 44.0, self.height() - 24.0
        span = bottom - top

        def y_of(db):
            return top + span * (min(0.0, db) / DB_LOW)

        # the dB scale on the left
        p.setFont(small)
        for db in TICKS:
            y = y_of(db)
            p.setPen(QColor(theme.DIM))
            p.drawText(QRectF(4, y - 6, SCALE_W, 12), Qt.AlignRight | Qt.AlignVCenter, str(db))
            p.setPen(QPen(theme.faint(30), 1))
            p.drawLine(QPointF(SCALE_W + 10, y), QPointF(self.width() - 10, y))

        x = SCALE_W + 14.0
        for i, (label, colour) in enumerate(self.labels):
            bar = QRectF(x, top, BAR_W, span)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.FIELD))
            p.drawRoundedRect(bar, 3, 3)
            level = self.levels[i]
            if level > DB_LOW + 0.5:
                # three coloured zones, like a mixing desk
                for lo, hi in ((DB_LOW, -18.0), (-18.0, -6.0), (-6.0, 0.0)):
                    if level <= lo:
                        break
                    y1, y2 = y_of(min(level, hi)), y_of(lo)
                    p.setBrush(_colour((lo + hi) / 2))
                    p.drawRect(QRectF(x + 1, y1, BAR_W - 2, y2 - y1))
            peak = self.peaks[i]
            if peak > DB_LOW + 0.5:
                p.setPen(QPen(_colour(peak), 2))
                y = y_of(peak)
                p.drawLine(QPointF(x + 1, y), QPointF(x + BAR_W - 1, y))
            # the channel label under the bar, in its role colour
            p.setPen(QColor(theme.readable(colour) if colour else theme.DIM))
            bold = QFont(small)
            bold.setBold(True)
            p.setFont(bold)
            p.drawText(QRectF(x + BAR_W / 2 - self.step / 2, bottom + 4, self.step, 14),
                       Qt.AlignCenter, label)
            p.setFont(small)
            x += self.step
        p.end()


class LevelsBar(QScrollArea):
    """The row of meter blocks under the room map."""

    def __init__(self, state):
        super().__init__()
        self.state = state
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFixedHeight(196)
        inner = QWidget()
        self.row = QHBoxLayout(inner)
        self.row.setContentsMargins(0, 4, 0, 4)
        self.row.setSpacing(8)
        self.row.addStretch(1)
        self.setWidget(inner)
        self.input_block = MeterBlock("PC sound")
        self.row.insertWidget(0, self.input_block)
        self.blocks: dict = {}               # device id -> MeterBlock
        self._last = time.monotonic()
        self._quiet = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(33)
        state.structureChanged.connect(self.rebuild)
        state.runningChanged.connect(self.rebuild)
        state.devicesScanned.connect(self.rebuild)
        self.rebuild()

    def rebuild(self) -> None:
        p = self.state.project
        engine = self.state.engine
        # the PC's sound
        if p.input_kind == "test":
            source = "Test signal"
        else:
            source = p.input_name.replace(" [Loopback]", "") or "Nothing chosen"
        self.input_block.subtitle = source
        roles = engine.source_roles if self.state.runner.running else ["FL", "FR"]
        self.input_block.set_channels([(_source_label(r, len(roles)), ROLE_COLORS.get(r, ""))
                                       for r in roles])
        # one block per output that is ticked
        wanted = [d for d in p.devices if d.enabled]
        for dev_id in list(self.blocks):
            if dev_id not in {d.id for d in wanted}:
                block = self.blocks.pop(dev_id)
                self.row.removeWidget(block)
                block.hide()                    # gone at once, deleted when Qt gets to it
                block.deleteLater()
        for index, dev in enumerate(wanted):
            block = self.blocks.get(dev.id)
            if block is None:
                block = self.blocks[dev.id] = MeterBlock(dev.title)
            block.title = dev.title
            block.subtitle = f"{dev.channels} channels" if dev.channels > 2 else ""
            labels = []
            for ch in range(dev.channels):
                spk = next((s for s in dev.speakers if s.channel == ch), None)
                if spk is None or spk.role == OFF:
                    labels.append((spk.name[:4] if spk else str(ch + 1), ""))
                else:
                    labels.append((ROLE_SHORT.get(spk.role, spk.role), ROLE_COLORS.get(spk.role, "")))
            block.set_channels(labels)
            self.row.insertWidget(index + 1, block)
            block.update()
        self.input_block.update()

    def tick(self) -> None:
        if not self.isVisible():
            return
        now = time.monotonic()
        dt, self._last = now - self._last, now
        engine = self.state.engine
        running = self.state.runner.running
        if not running:
            if self._quiet:
                return                       # nothing moves while stopped
            self._quiet = True
        else:
            self._quiet = False
        zero = ()
        if self.input_block.feed(engine.input_peaks if running else zero, dt):
            self.input_block.update()
        for dev_id, block in self.blocks.items():
            values = engine.output_peaks.get(dev_id, zero) if running else zero
            if block.feed(values, dt if running else 10.0):
                block.update()
        if not running:
            self.input_block.feed(zero, 10.0)
            self.input_block.update()


def _source_label(role: str, count: int) -> str:
    if count <= 2:
        return {"FL": "L", "FR": "R"}.get(role, role)
    return ROLE_SHORT.get(role, role)
