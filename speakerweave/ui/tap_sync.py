"""Tap along: each speaker's real delay measured by tapping to its clicks.

A click plays on one speaker at a time, at a steady beat. A wide box shows the time
around every click, with 0 ms the moment SpeakerWeave sends it and a line running across
as each click comes up. Each time the click is heard, the person presses the button (or
Space) and a mark lands in the box where they pressed. Tapping along to a beat lands on
the sound itself, not after it, so the middle of the marks is how late that speaker
plays. With two or more speakers measured, Use these results delays the faster ones so
every click lands together, the slowest at 0 ms.
"""
from __future__ import annotations

import statistics
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QSlider, QVBoxLayout, QWidget)

from ..model import OFF, ROLE_NAMES, is_shaker, is_sub
from . import theme
from .panels import dim

BPM = 75                    # a click every 0.8 s: the box shows 0.4 s either side of each
SPAN_MS = 400
GRID_MS = 100
NEED_TAPS = 6               # taps before a speaker counts as measured
USE_LAST = 10               # the measurement uses this many of the latest taps
FRAME_MS = 16


def period_s() -> float:
    return 60.0 / BPM


def nearest_offset_ms(pressed: float, clicks) -> float:
    """How far (ms) a press lies from the click nearest to it: positive after the click.
    clicks: the times clicks left the engine; the next one is taken as one beat on."""
    clicks = list(clicks)
    if not clicks:
        return float("nan")
    candidates = clicks + [clicks[-1] + period_s()]
    best = min(candidates, key=lambda c: abs(pressed - c))
    return (pressed - best) * 1000.0


def measured(taps: list):
    """(delay in ms, spread in ms) from a speaker's taps, or None while there are too few.
    The middle of the latest taps, so one slip of the finger does not count."""
    recent = [t for t in taps[-USE_LAST:] if t == t]
    if len(recent) < NEED_TAPS:
        return None
    middle = statistics.median(recent)
    spread = statistics.median([abs(t - middle) for t in recent])
    return middle, spread


class Timeline(QWidget):
    """The box: lines every 100 ms, 0 where the click is sent, a line running across as each
    click comes up, and a mark for every tap."""

    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        self.setMinimumSize(560, 170)

    def x_of(self, ms: float) -> float:
        left, right = 24.0, self.width() - 24.0
        return left + (ms + SPAN_MS) / (2 * SPAN_MS) * (right - left)

    def cursor_ms(self):
        """Where the running line is: ms from the nearest click (negative: one coming up)."""
        clicks = self.dialog.click_times()
        if not clicks:
            return None
        phase = time.perf_counter() - clicks[-1]
        if phase < 0:
            return None
        p = period_s()
        phase %= p
        if phase > p / 2:
            phase -= p
        return phase * 1000.0

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        box = QRectF(8, 8, self.width() - 16, self.height() - 16)
        p.setPen(QPen(QColor(theme.BORDER), 1.2))
        p.setBrush(QColor(theme.PANEL))
        p.drawRoundedRect(box, 8, 8)
        small = QFont(self.font())
        small.setPointSizeF(8.5)
        p.setFont(small)
        top, bottom = box.top() + 22, box.bottom() - 10
        for ms in range(-SPAN_MS, SPAN_MS + 1, GRID_MS):
            x = self.x_of(ms)
            zero = ms == 0
            p.setPen(QPen(QColor(theme.ACCENT) if zero else theme.faint(40), 2.0 if zero else 1.0))
            p.drawLine(QPointF(x, top), QPointF(x, bottom))
            p.setPen(QColor(theme.TEXT) if zero else QColor(theme.DIM))
            label = "0 ms" if zero else f"{ms:+d}"
            p.drawText(QRectF(x - 30, box.top() + 4, 60, 16), Qt.AlignCenter, label)
        # the taps of the speaker being measured, the latest brightest
        taps = self.dialog.current_taps()[-USE_LAST:]
        for i, ms in enumerate(taps):
            if ms != ms or abs(ms) > SPAN_MS:
                continue
            mark = QColor(theme.ACCENT)
            mark.setAlpha(int(90 + 165 * (i + 1) / len(taps)))
            p.setPen(QPen(mark, 3.0))
            x = self.x_of(ms)
            p.drawLine(QPointF(x, top + 26), QPointF(x, bottom - 26))
        result = measured(self.dialog.current_taps())
        if result is not None:
            ms, _spread = result
            x = self.x_of(max(-SPAN_MS, min(SPAN_MS, ms)))
            p.setPen(QPen(QColor(theme.GOOD), 2.0, Qt.DashLine))
            p.drawLine(QPointF(x, top), QPointF(x, bottom))
            p.setPen(QColor(theme.GOOD))
            p.drawText(QRectF(x - 50, bottom - 18, 100, 16), Qt.AlignCenter, f"{ms:+.0f} ms")
        # the running line, as the next click comes up and goes out
        cursor = self.cursor_ms()
        if cursor is not None:
            x = self.x_of(cursor)
            p.setPen(QPen(QColor(theme.TEXT), 2.5))
            p.drawLine(QPointF(x, top - 4), QPointF(x, bottom))
        p.end()


class TapSyncDialog(QDialog):
    def __init__(self, window, speakers: list):
        """speakers: [(speaker id, low)] in the order they are measured."""
        super().__init__(window)
        self.window, self.state = window, window.state
        self.project = self.state.project
        self.speakers = speakers
        self.low = dict(speakers)
        self.taps: dict = {spk_id: [] for spk_id, _low in speakers}
        self.start = {}
        self.applied = False
        self.setWindowTitle("Tap along")
        self.setMinimumWidth(860)
        col = QVBoxLayout(self)
        col.setContentsMargins(20, 18, 20, 16)
        col.setSpacing(10)
        title = QLabel("Tap along to each speaker")
        title.setStyleSheet("font-size: 17px; font-weight: 700;")
        col.addWidget(title)
        col.addWidget(dim("A click plays on the speaker picked on the left. Every time you hear it, press "
                          "I hear it (or Space). Tap along to the beat: the line running across shows "
                          f"each click coming up, 0 ms is when it is sent. After {NEED_TAPS} taps the "
                          "speaker is measured. Then pick the next one."))
        row = QHBoxLayout()
        self.list = QListWidget()
        self.list.setMinimumWidth(240)
        for spk_id, _low in speakers:
            item = QListWidgetItem("")
            item.setData(Qt.UserRole, spk_id)
            self.list.addItem(item)
        row.addWidget(self.list)
        right = QVBoxLayout()
        self.timeline = Timeline(self)
        right.addWidget(self.timeline, 1)
        self.hear_btn = QPushButton("I hear it  (Space)")
        self.hear_btn.setObjectName("primary")
        self.hear_btn.setMinimumHeight(54)
        self.hear_btn.setStyleSheet("font-size: 16px;")
        self.hear_btn.setFocusPolicy(Qt.NoFocus)
        self.hear_btn.pressed.connect(lambda: self.tap())   # the moment it goes down counts
        right.addWidget(self.hear_btn)
        status = QHBoxLayout()
        self.status = QLabel("")
        status.addWidget(self.status, 1)
        self.clear_btn = QPushButton("Tap again")
        self.clear_btn.setToolTip("Forget this speaker's taps and start again")
        self.clear_btn.clicked.connect(self.clear_taps)
        status.addWidget(self.clear_btn)
        right.addLayout(status)
        row.addLayout(right, 1)
        col.addLayout(row, 1)

        loud = QHBoxLayout()
        loud.addWidget(QLabel("Clicks louder by"))
        self.boost = QSlider(Qt.Horizontal)
        lo, hi = self.state.TEST_BOOST_RANGE
        self.boost.setRange(int(lo), int(hi))
        self.boost_text = QLabel("")
        self.boost_text.setMinimumWidth(52)
        loud.addWidget(self.boost, 1)
        loud.addWidget(self.boost_text)
        col.addLayout(loud)
        buttons = QHBoxLayout()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setToolTip("Stop and put every delay back as it was")
        self.use_btn = QPushButton("Use these results")
        self.use_btn.setObjectName("primary")
        self.use_btn.setToolTip("Delays the faster speakers so every click lands together")
        buttons.addWidget(self.cancel_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.use_btn)
        col.addLayout(buttons)
        self.cancel_btn.clicked.connect(self.reject)
        self.use_btn.clicked.connect(self.use_results)
        self.boost.valueChanged.connect(self._boost_changed)
        self.list.currentRowChanged.connect(self._picked)

        # measured from a clean start: every speaker at 0 ms (Cancel puts the old delays back)
        for spk_id, _low in speakers:
            spk = self.project.find_speaker(spk_id)[1]
            self.start[spk_id] = spk.delay_ms
            spk.delay_ms = 0.0
            self.state.touch_speaker(spk_id)
        self.boost.setValue(int(round(self.state.settings.test_boost_db)))
        self._boost_changed(self.boost.value())
        self._frame = QTimer(self)
        self._frame.setInterval(FRAME_MS)
        self._frame.timeout.connect(self.timeline.update)
        self._frame.start()
        self.list.setCurrentRow(0)
        self._show()

    # ------------------------------------------------------------ the speaker measured
    def current(self) -> str:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item is not None else ""

    def current_taps(self) -> list:
        return self.taps.get(self.current(), [])

    def click_times(self) -> list:
        return list(self.state.engine.click_times)

    def _picked(self, _row: int) -> None:
        spk_id = self.current()
        if spk_id:
            self.state.engine.click_times.clear()
            self.state.play_clicks([(spk_id, self.low[spk_id])], bpm=BPM)
        self._show()

    def _title(self, spk_id: str) -> str:
        dev, spk = self.project.find_speaker(spk_id)
        role = ROLE_NAMES.get(spk.role, spk.role)
        name = f"{spk.name} of {dev.title}" if dev.channels > 1 else dev.title
        return f"{name} ({role})"

    def _show(self) -> None:
        for i in range(self.list.count()):
            item = self.list.item(i)
            spk_id = item.data(Qt.UserRole)
            result = measured(self.taps[spk_id])
            done = f"{result[0]:+.0f} ms" if result else "not measured yet"
            item.setText(f"{self._title(spk_id)}\n    {done}")
        taps = self.current_taps()
        result = measured(taps)
        if result is None:
            left = NEED_TAPS - len([t for t in taps if t == t])
            self.status.setText(f"Tap {left} more time{'s' if left != 1 else ''}" if taps else
                                "Press I hear it each time you hear the click")
        else:
            ms, spread = result
            steady = "steady" if spread <= 15 else "a bit uneven, keep tapping"
            self.status.setText(f"This speaker plays {ms:+.0f} ms after the click is sent "
                                f"(taps {steady}, within {spread:.0f} ms)")
        done = sum(1 for spk_id in self.taps if measured(self.taps[spk_id]) is not None)
        self.use_btn.setEnabled(done >= 2)

    # ------------------------------------------------------------ tapping
    def tap(self, at: float = None) -> float:
        """A press: where it lands relative to the nearest click. Returns the ms."""
        spk_id = self.current()
        if not spk_id:
            return float("nan")
        at = time.perf_counter() if at is None else at
        ms = nearest_offset_ms(at, self.click_times())
        if ms == ms:
            self.taps[spk_id].append(ms)
            self.taps[spk_id] = self.taps[spk_id][-40:]
        self._show()
        self.timeline.update()
        return ms

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Space and not ev.isAutoRepeat():
            self.hear_btn.setDown(True)
            self.tap()
            return
        super().keyPressEvent(ev)

    def keyReleaseEvent(self, ev):
        if ev.key() == Qt.Key_Space and not ev.isAutoRepeat():
            self.hear_btn.setDown(False)
            return
        super().keyReleaseEvent(ev)

    def clear_taps(self) -> None:
        spk_id = self.current()
        if spk_id:
            self.taps[spk_id] = []
        self._show()

    def _boost_changed(self, db: int) -> None:
        self.state.boost_tests(db)
        self.boost_text.setText(f"{db:+d} dB" if db else "0 dB")

    # ------------------------------------------------------------ the end
    def results(self) -> dict:
        """{speaker id: delay to give it} from the measured speakers: the slowest gets 0 ms,
        every other one as much as it plays earlier."""
        lates = {spk_id: measured(taps)[0] for spk_id, taps in self.taps.items()
                 if measured(taps) is not None}
        if len(lates) < 2:
            return {}
        slowest = max(lates.values())
        return {spk_id: round(slowest - late, 1) for spk_id, late in lates.items()}

    def use_results(self) -> None:
        delays = self.results()
        if not delays:
            return
        for spk_id in self.start:
            spk = self.project.find_speaker(spk_id)[1]
            spk.delay_ms = delays.get(spk_id, self.start[spk_id])   # not measured: as it was
        self.applied = True
        self.accept()

    def done(self, result: int) -> None:
        self._frame.stop()
        state = self.state
        state.boost_tests(None)
        state.stop_metronome()
        if not self.applied:
            for spk_id, ms in self.start.items():
                self.project.find_speaker(spk_id)[1].delay_ms = ms
        for spk_id in self.start:
            state.touch_speaker(spk_id)
        state.save_soon()
        super().done(result)
        if self.applied:
            lines = [f"{self._title(i)}: {ms:.1f} ms" for i, ms in self.results().items()]
            QMessageBox.information(self.window, "Tap along",
                                    "Every measured speaker is lined up. The slowest one plays at 0 ms, "
                                    "the others wait for it:\n\n" + "\n".join(lines))
            state.notice.emit("Tap along finished: the measured speakers are lined up.")
        else:
            state.notice.emit("Tap along cancelled: every delay is back as it was.")


def tap_speakers(project) -> list:
    """[(speaker id, low)] of every speaker that plays, subwoofers last (they get a thump)."""
    mains, subs = [], []
    for dev in project.devices:
        if not dev.enabled:
            continue
        for spk in dev.speakers:
            if spk.role == OFF or spk.mute or is_shaker(spk.role) or spk.channel >= dev.channels:
                continue
            low = is_sub(spk.role) or (spk.lp_on and spk.lp_freq <= 250)
            (subs if low else mains).append((spk.id, low))
    return mains + subs


def start_tap_sync(window) -> None:
    speakers = tap_speakers(window.state.project)
    if len(speakers) < 2:
        QMessageBox.information(window, "Tap along",
                                "Tap along needs at least two speakers that play. Tick your outputs "
                                "and give their speakers a role first.")
        return
    dialog = TapSyncDialog(window, speakers)
    dialog.setWindowModality(Qt.WindowModal)
    dialog.exec()
