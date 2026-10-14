"""Frequency response graph with draggable EQ bands and frequency limits."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ..dsp import response_db
from ..model import EQBand
from . import theme

F_LO, F_HI = 10.0, 22000.0
DB_HI, DB_LO = 18.0, -30.0
GAIN_LIMIT = 18.0
Q_MIN, Q_MAX = 0.2, 12.0
GRID_F = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]
MAX_BANDS = 16


def nice_freq(f: float) -> float:
    """Round to three significant figures."""
    if f <= 0:
        return F_LO
    digits = 2 - int(math.floor(math.log10(f)))
    return round(f, digits)


def freq_text(f: float) -> str:
    if f >= 1000:
        return f"{f / 1000:g} kHz" if f % 1000 == 0 else f"{f / 1000:.2f} kHz"
    return f"{f:g} Hz"


class EqGraph(QWidget):
    changed = Signal()          # the user dragged something
    bandSelected = Signal(int)

    def __init__(self):
        super().__init__()
        self.spk = None
        self.sr = 48000.0
        self.color = QColor(theme.ACCENT)
        self.selected = -1
        self._drag = None       # ("band", index) | ("hp",) | ("lp",)
        self._freqs = np.geomspace(F_LO, F_HI, 320)
        self.setMinimumHeight(210)
        self.setMouseTracking(True)

    def set_speaker(self, spk, sr: float, color: str) -> None:
        if spk is not self.spk:
            self.selected = -1
        self.spk = spk
        self.sr = sr
        self.color = QColor(color)
        if spk is not None and self.selected >= len(spk.eq):
            self.selected = -1
        self.update()

    # ------------------------------------------------------------ axes
    def _plot(self) -> QRectF:
        return QRectF(34, 8, self.width() - 44, self.height() - 30)

    def fx(self, f: float) -> float:
        r = self._plot()
        t = math.log(max(f, F_LO) / F_LO) / math.log(F_HI / F_LO)
        return r.left() + min(max(t, 0.0), 1.0) * r.width()

    def xf(self, x: float) -> float:
        r = self._plot()
        t = min(max((x - r.left()) / r.width(), 0.0), 1.0)
        return F_LO * (F_HI / F_LO) ** t

    def gy(self, db: float) -> float:
        r = self._plot()
        t = (DB_HI - min(max(db, DB_LO), DB_HI)) / (DB_HI - DB_LO)
        return r.top() + t * r.height()

    def yg(self, y: float) -> float:
        r = self._plot()
        return DB_HI - (y - r.top()) / r.height() * (DB_HI - DB_LO)

    def _band_pos(self, band: EQBand) -> QPointF:
        return QPointF(self.fx(band.freq), self.gy(band.gain_db))

    # ------------------------------------------------------------ mouse
    def _hit(self, pos: QPointF):
        if self.spk is None:
            return None
        best, best_d = None, 11.0
        for i, band in enumerate(self.spk.eq):
            bp = self._band_pos(band)
            d = math.hypot(bp.x() - pos.x(), bp.y() - pos.y())
            if d < best_d:
                best, best_d = ("band", i), d
        if best:
            return best
        if self.spk.hp_on and abs(pos.x() - self.fx(self.spk.hp_freq)) < 7:
            return ("hp",)
        if self.spk.lp_on and abs(pos.x() - self.fx(self.spk.lp_freq)) < 7:
            return ("lp",)
        return None

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton or self.spk is None:
            return
        hit = self._hit(ev.position())
        self._drag = hit
        if hit and hit[0] == "band":
            self.selected = hit[1]
            self.bandSelected.emit(hit[1])
        self.update()

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self._drag is None or self.spk is None:
            hit = self._hit(pos)
            if hit is None:
                self.setCursor(Qt.ArrowCursor)
            else:
                self.setCursor(Qt.SizeAllCursor if hit[0] == "band" else Qt.SizeHorCursor)
            return
        if self._drag[0] == "band":
            band = self.spk.eq[self._drag[1]]
            band.freq = nice_freq(min(max(self.xf(pos.x()), F_LO), 20000.0))
            band.gain_db = round(min(max(self.yg(pos.y()), -GAIN_LIMIT), GAIN_LIMIT), 1)
            if abs(band.gain_db) < 0.25:
                band.gain_db = 0.0      # easy to land exactly on flat
        elif self._drag[0] == "hp":
            top = self.spk.lp_freq * 0.8 if self.spk.lp_on else 20000.0
            self.spk.hp_freq = nice_freq(min(max(self.xf(pos.x()), F_LO), top))
        elif self._drag[0] == "lp":
            low = self.spk.hp_freq * 1.25 if self.spk.hp_on else 20.0
            self.spk.lp_freq = nice_freq(min(max(self.xf(pos.x()), low), 20000.0))
        self.changed.emit()
        self.update()

    def mouseReleaseEvent(self, _ev):
        self._drag = None

    def mouseDoubleClickEvent(self, ev):
        if self.spk is None:
            return
        hit = self._hit(ev.position())
        if hit and hit[0] == "band":
            self.spk.eq[hit[1]].gain_db = 0.0
        elif hit is None and self._plot().contains(ev.position()) and len(self.spk.eq) < MAX_BANDS:
            band = EQBand("peak", nice_freq(self.xf(ev.position().x())),
                          round(min(max(self.yg(ev.position().y()), -GAIN_LIMIT), GAIN_LIMIT), 1), 1.41)
            self.spk.eq.append(band)
            self.selected = len(self.spk.eq) - 1
            self.bandSelected.emit(self.selected)
        else:
            return
        self.changed.emit()
        self.update()

    def wheelEvent(self, ev):
        if self.spk is None:
            return
        hit = self._hit(ev.position())
        if not hit or hit[0] != "band":
            ev.ignore()
            return
        band = self.spk.eq[hit[1]]
        factor = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
        band.q = round(min(max(band.q * factor, Q_MIN), Q_MAX), 2)
        self.selected = hit[1]
        self.bandSelected.emit(hit[1])
        self.changed.emit()
        self.update()

    # ------------------------------------------------------------ painting
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._plot()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.FIELD))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        font = QFont(self.font())
        font.setPointSizeF(7.5)
        p.setFont(font)

        for f in GRID_F:
            x = self.fx(f)
            p.setPen(QPen(theme.faint(16), 1))
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            p.setPen(QColor(theme.DIM))
            label = f"{f // 1000}k" if f >= 1000 else str(f)
            p.drawText(QRectF(x - 20, r.bottom() + 3, 40, 14), Qt.AlignCenter, label)
        for db in range(int(DB_LO), int(DB_HI) + 1, 6):
            y = self.gy(db)
            p.setPen(QPen(theme.faint(46 if db == 0 else 16), 1))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(QColor(theme.DIM))
            p.drawText(QRectF(0, y - 7, 30, 14), Qt.AlignRight | Qt.AlignVCenter, f"{db:+d}" if db else "0")

        spk = self.spk
        if spk is None:
            p.setPen(QColor(theme.DIM))
            p.drawText(r, Qt.AlignCenter, "Select a speaker")
            p.end()
            return

        # the parts of the range this speaker is not allowed to play
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 90) if theme.DARK else theme.faint(22))
        if spk.hp_on:
            p.drawRect(QRectF(r.left(), r.top(), self.fx(spk.hp_freq) - r.left(), r.height()))
        if spk.lp_on:
            x = self.fx(spk.lp_freq)
            p.drawRect(QRectF(x, r.top(), r.right() - x, r.height()))

        resp = response_db(spk, self.sr, self._freqs)
        path = QPainterPath()
        for i, (f, db) in enumerate(zip(self._freqs, resp)):
            pt = QPointF(self.fx(float(f)), self.gy(float(db)))
            path.lineTo(pt) if i else path.moveTo(pt)
        fill = QPainterPath(path)
        fill.lineTo(QPointF(r.right(), r.bottom()))
        fill.lineTo(QPointF(r.left(), r.bottom()))
        fill.closeSubpath()
        p.save()
        p.setClipRect(r)
        tint = QColor(self.color)
        tint.setAlpha(38)
        p.setPen(Qt.NoPen)
        p.setBrush(tint)
        p.drawPath(fill)
        p.setPen(QPen(self.color, 2))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.restore()

        for on, freq, left in ((spk.hp_on, spk.hp_freq, True), (spk.lp_on, spk.lp_freq, False)):
            if not on:
                continue
            x = self.fx(freq)
            p.setPen(QPen(QColor(theme.WARN), 1.5))
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            text = freq_text(freq)
            tw = p.fontMetrics().horizontalAdvance(text) + 8
            box = QRectF(x + 3 if left else x - tw - 3, r.top() + 3, tw, 15)
            if box.right() > r.right():
                box.moveRight(x - 3)
            if box.left() < r.left():
                box.moveLeft(x + 3)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.WARN))
            p.drawRoundedRect(box, 3, 3)
            p.setPen(QColor("#0b1220") if theme.DARK else QColor("#ffffff"))
            p.drawText(box, Qt.AlignCenter, text)

        for i, band in enumerate(spk.eq):
            pt = self._band_pos(band)
            live = spk.eq_on and band.enabled
            p.setPen(QPen(QColor(theme.TEXT) if i == self.selected else QColor(theme.BADGE_EDGE),
                          2 if i == self.selected else 1.2))
            p.setBrush(self.color if live else QColor(theme.OFF_FILL))
            p.drawEllipse(pt, 6.5 if i == self.selected else 5.5, 6.5 if i == self.selected else 5.5)
        p.end()
