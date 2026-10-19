"""The Performance page: how much of the PC SpeakerWeave uses (processor, memory), how
hard the sound work is, and how every output is keeping up.

Readings are taken once a second all the time, so the last two minutes are already
there when the page is opened. They are only drawn while the page is on screen.
"""
from __future__ import annotations

from collections import deque

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout,
                               QWidget)

from ..perf import ProcessStats
from . import theme
from .panels import dim, scrolled

HISTORY_S = 120             # seconds the chart goes back
# the two lines of the chart: categorical blue and orange, checked for colour blindness
# and contrast against every theme's panels (dark and light steps)
SERIES = {"cpu": ("SpeakerWeave processor use", "#3987e5", "#2a78d6"),
          "load": ("Sound work per block", "#d95926", "#eb6834")}
BUSY_LOAD = 0.7             # sound work above this share of a block risks dropouts
PEAK_S = 10                 # the busiest block of the last this many seconds is shown


def _color(key: str) -> QColor:
    _name, dark, light = SERIES[key]
    return QColor(dark if theme.DARK else light)


def _mb(size: float) -> str:
    return f"{size / 1048576:.0f} MB"


def _gb(size: float) -> str:
    return f"{size / 1073741824:.0f} GB"


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    h, m, s = seconds // 3600, seconds // 60 % 60, seconds % 60
    return f"{h} h {m} min" if h else (f"{m} min {s} s" if m else f"{s} s")


def delay_note(runner) -> str:
    """Where the delay comes from, in a line: "listening 10, buffer 8, output 12, speakers 3 ms"."""
    parts = runner.delay_parts()
    names = (("listening", "listening"), ("buffer", "buffer"), ("output", "output"),
             ("speakers", "lining up speakers"))
    text = ", ".join(f"{label} {parts[key]:.0f}" for key, label in names if parts[key] >= 0.5) + " ms"
    if runner.exclusive:
        text += f". {len(runner.exclusive)} of {len(runner.fifos)} outputs on their own"
    return text


class _Tile(QFrame):
    """One headline number with a line underneath that says what it means."""

    def __init__(self, title: str, tip: str):
        super().__init__()
        self.setObjectName("tile")
        self.setToolTip(tip)
        col = QVBoxLayout(self)
        col.setContentsMargins(14, 10, 14, 12)
        col.setSpacing(2)
        self.title = dim(title)
        self.value = QLabel("...")
        self.value.setStyleSheet("font-size: 22px; font-weight: 700;")
        self.note = dim("")
        col.addWidget(self.title)
        col.addWidget(self.value)
        col.addWidget(self.note)
        self.restyle()

    def restyle(self) -> None:
        self.setStyleSheet(f"QFrame#tile {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER}; "
                           f"border-radius: 8px; }}")

    def show_value(self, value: str, note: str, warn: bool = False) -> None:
        self.value.setText(value)
        # a status colour only for a real problem, and never on its own: the note says why
        self.value.setStyleSheet("font-size: 22px; font-weight: 700;"
                                 + (f" color: {theme.WARN};" if warn else ""))
        self.note.setText(note)


class HistoryChart(QWidget):
    """The last two minutes of processor use and sound work, as two thin lines on one
    percent scale, with a readout under the mouse."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(190)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.data = {key: deque(maxlen=HISTORY_S) for key in SERIES}
        self._hover = None

    def add(self, cpu: float, load: float) -> None:
        self.data["cpu"].append(cpu)
        self.data["load"].append(load)
        if self.isVisible():
            self.update()

    def _top(self) -> float:
        highest = max([1.0] + [v for series in self.data.values() for v in series])
        for step in (4, 8, 20, 40, 100, 200, 400):     # four grid steps of whole numbers
            if highest <= step:
                return float(step)
        return highest

    def _plot(self) -> QRectF:
        return QRectF(44, 12, max(10, self.width() - 44 - 96), max(10, self.height() - 12 - 26))

    def mouseMoveEvent(self, ev):
        plot = self._plot()
        if plot.contains(ev.position()):
            ago = int(round((plot.right() - ev.position().x()) / plot.width() * (HISTORY_S - 1)))
            self._hover = max(0, ago)
        else:
            self._hover = None
        self.update()

    def leaveEvent(self, _ev):
        self._hover = None
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        plot = self._plot()
        top = self._top()
        font = p.font()
        font.setPointSizeF(max(7.5, font.pointSizeF() - 1))
        p.setFont(font)
        ink, faint_ink = QColor(theme.DIM), theme.faint(40)
        # recessive grid and axis: four lines, labelled in the muted text colour
        for i in range(5):
            y = plot.bottom() - plot.height() * i / 4
            p.setPen(QPen(faint_ink, 1))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(ink)
            p.drawText(QRectF(0, y - 8, plot.left() - 6, 16), Qt.AlignRight | Qt.AlignVCenter,
                       f"{top * i / 4:.0f}%")
        p.setPen(ink)
        p.drawText(QRectF(plot.left(), plot.bottom() + 4, 120, 18), Qt.AlignLeft, "2 minutes ago")
        p.drawText(QRectF(plot.right() - 120, plot.bottom() + 4, 120, 18), Qt.AlignRight, "now")

        def point(index_from_end: int, value: float) -> QPointF:
            x = plot.right() - plot.width() * index_from_end / (HISTORY_S - 1)
            y = plot.bottom() - plot.height() * min(value, top) / top
            return QPointF(x, y)

        for key, series in self.data.items():
            if not series:
                continue
            values = list(series)
            path = QPainterPath()
            for i, value in enumerate(values):
                pt = point(len(values) - 1 - i, value)
                path.moveTo(pt) if i == 0 else path.lineTo(pt)
            pen = QPen(_color(key), 2)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        # direct labels at the right end of each line: a dot in the series colour, the
        # value in the text colour, nudged apart when the two are close
        ends = []
        for key, series in self.data.items():
            if series:
                ends.append([point(0, series[-1]).y(), key, series[-1]])
        ends.sort()
        if len(ends) == 2 and ends[1][0] - ends[0][0] < 16:
            mid = (ends[0][0] + ends[1][0]) / 2
            ends[0][0], ends[1][0] = mid - 8, mid + 8
        for y, key, value in ends:
            p.setPen(Qt.NoPen)
            p.setBrush(_color(key))
            p.drawEllipse(QPointF(plot.right() + 10, y), 4, 4)
            p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(plot.right() + 18, y - 9, 80, 18), Qt.AlignLeft | Qt.AlignVCenter,
                       f"{value:.1f}%")
        # the readout under the mouse: a guide line and both values at that moment
        if self._hover is not None:
            x = plot.right() - plot.width() * self._hover / (HISTORY_S - 1)
            p.setPen(QPen(theme.faint(110), 1, Qt.DashLine))
            p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            lines = [f"{self._hover} s ago" if self._hover else "now"]
            for key, series in self.data.items():
                if self._hover < len(series):
                    lines.append(f"{SERIES[key][0]}: {series[-1 - self._hover]:.1f}%")
            width = max(p.fontMetrics().horizontalAdvance(t) for t in lines) + 16
            height = 18 * len(lines) + 8
            bx = x + 10 if x + 10 + width < self.width() else x - 10 - width
            box = QRectF(bx, plot.top() + 4, width, height)
            shade = QColor(theme.PANEL_2)
            shade.setAlpha(240)
            p.setPen(QPen(QColor(theme.BORDER), 1))
            p.setBrush(shade)
            p.drawRoundedRect(box, 6, 6)
            p.setPen(QColor(theme.TEXT))
            for i, text in enumerate(lines):
                p.drawText(QRectF(box.left() + 8, box.top() + 4 + 18 * i, width, 18),
                           Qt.AlignLeft | Qt.AlignVCenter, text)
        p.end()


class PerformancePage(QWidget):
    def __init__(self, state, window):
        super().__init__()
        self.state = state
        self.window = window
        self.stats = ProcessStats()
        self.last = {}
        self.peaks = deque(maxlen=PEAK_S)           # the highest block load of each second

        inner = QWidget()
        outer = QHBoxLayout(inner)
        outer.setContentsMargins(16, 16, 16, 16)
        column = QWidget()
        column.setMaximumWidth(980)
        outer.addWidget(column, 1)
        outer.addStretch(0)
        col = QVBoxLayout(column)
        col.setSpacing(10)
        page = QVBoxLayout(self)
        page.setContentsMargins(0, 0, 0, 0)
        page.addWidget(scrolled(inner))

        title = QLabel("Performance")
        title.setObjectName("title")
        col.addWidget(title)
        col.addWidget(dim("How much of this PC SpeakerWeave uses, and how well the sound keeps up. "
                          "Updated every second."))

        grid = QGridLayout()
        grid.setSpacing(10)
        self.cpu = _Tile("Processor", "SpeakerWeave's share of all the PC's processor cores")
        self.memory = _Tile("Memory", "The memory SpeakerWeave has in use right now")
        self.load = _Tile("Sound work", "How much of each block's time the sound work takes. "
                          "Above 70% the sound can start to break up.")
        self.delay = _Tile("Delay", "How far behind the PC your speakers play because of "
                           "SpeakerWeave and Windows' buffers: listening to the PC sound, the room "
                           "kept so no output runs dry, the slowest output's buffer and the delay "
                           "given to speakers to line them up. Each device adds its own inside on "
                           "top (screens and TVs often 20 to 80 ms). Less: Lowest delay on the "
                           "Sound tab, and the virtual device at 48 kHz.")
        self.dropouts = _Tile("Dropouts", "Moments an output ran out of sound since the sound started")
        self.pc = _Tile("Whole PC", "How busy the PC's processor is with everything together")
        for i, tile in enumerate((self.cpu, self.memory, self.load, self.delay, self.dropouts, self.pc)):
            grid.addWidget(tile, i // 3, i % 3)
        col.addLayout(grid)

        chart_box = QFrame()
        chart_box.setObjectName("tile")
        chart_box.setStyleSheet(f"QFrame#tile {{ background: {theme.PANEL}; border: 1px solid "
                                f"{theme.BORDER}; border-radius: 8px; }}")
        chart_col = QVBoxLayout(chart_box)
        chart_col.setContentsMargins(14, 10, 14, 10)
        legend = QHBoxLayout()
        chart_title = QLabel("<b>The last two minutes</b>")
        legend.addWidget(chart_title)
        legend.addStretch(1)
        for key, (name, _dark, _light) in SERIES.items():
            swatch = QLabel()
            swatch.setFixedSize(16, 3)
            swatch.setStyleSheet(f"background: {_color(key).name()}; border-radius: 1px;")
            legend.addWidget(swatch)
            legend.addWidget(QLabel(name))
            legend.addSpacing(10)
        chart_col.addLayout(legend)
        self.chart = HistoryChart()
        chart_col.addWidget(self.chart)
        col.addWidget(chart_box)

        heading = QLabel("<b>Outputs</b>")
        col.addWidget(heading)
        self.outputs = QGridLayout()
        self.outputs.setHorizontalSpacing(18)
        self.outputs.setVerticalSpacing(4)
        col.addLayout(self.outputs)
        self.details = dim("")
        col.addWidget(self.details)
        col.addStretch(1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.tick)
        self._timer.start(1000)
        self.tick()

    # ------------------------------------------------------------ readings
    def tick(self) -> None:
        shown = self.isVisible()
        s = self.stats.sample(threads=shown)          # counting threads takes a moment
        runner = self.state.runner
        load = 100.0 * runner.load if runner.running else 0.0
        self.peaks.append(100.0 * runner.take_load_peak() if runner.running else 0.0)
        self.last = dict(s, load=load, load_peak=max(self.peaks))
        self.chart.add(s.get("cpu_pc", 0.0), load)
        if shown:
            self.show_readings()

    def show_readings(self) -> None:
        s = self.last
        runner = self.state.runner
        if "cpu_pc" in s:
            self.cpu.show_value(f"{s['cpu_pc']:.1f}%",
                                f"of the whole PC, {s['cpu_core']:.0f}% of one of its {s['cores']} cores")
        if s.get("pc_total"):
            share = 100.0 * s["in_use"] / s["pc_total"]
            self.memory.show_value(_mb(s["in_use"]), f"{share:.1f}% of this PC's {_gb(s['pc_total'])}, "
                                                     f"at most {_mb(s['peak'])} so far")
        if runner.running:
            busy = s["load"] >= BUSY_LOAD * 100
            note = (f"of each block's time, at most {s['load_peak']:.0f}% in the last {PEAK_S} seconds" if not busy
                    else "Close to the limit. Close heavy programs, or raise the Safety buffer "
                         "on the Sound tab.")
            self.load.show_value(f"{s['load']:.0f}%", note, warn=busy)
            self.delay.show_value(f"{runner.delay_ms():.0f} ms", delay_note(runner))
            status = runner.status()
            drops = sum(g for _f, _p, g in status.values())
            self.dropouts.show_value(str(drops), "since the sound started" if drops == 0 else
                                     "since the sound started. The Outputs list shows where",
                                     warn=drops > 0)
        else:
            for tile in (self.load, self.delay, self.dropouts):
                tile.show_value("Off", "The sound is not running")
            status = {}
        if "pc_busy" in s:
            self.pc.show_value(f"{s['pc_busy']:.0f}%", "busy with everything that runs on it")
        self._show_outputs(status)
        self.details.setText(
            f"Running for {_duration(s.get('uptime_s', 0))}.  {s.get('threads', 0)} threads, "
            f"{s.get('handles', 0)} handles.  Mixing errors: {runner.callback_errors}.")

    def _show_outputs(self, status: dict) -> None:
        """One row per output. The labels are made once per set of outputs and only get new
        text after that, so nothing flickers or lingers."""
        rows = [(dev_id,) + tuple(values) for dev_id, values in status.items()]
        shape = tuple(r[0] for r in rows)
        if shape != getattr(self, "_rows_for", None):
            self._rows_for = shape
            while self.outputs.count():
                item = self.outputs.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.hide()
                    widget.setParent(None)
                    widget.deleteLater()
            self._cells = []
            if not rows:
                self.outputs.addWidget(dim("Start the sound to see how every output keeps up."), 0, 0, 1, 4)
                return
            for c, text in enumerate(("Output", "Buffer", "Clock correction", "Dropouts")):
                self.outputs.addWidget(dim(text), 0, c)
            for r in range(len(rows)):
                cells = [QLabel("") for _ in range(4)]
                for c, cell in enumerate(cells):
                    self.outputs.addWidget(cell, r + 1, c)
                self._cells.append(cells)
        for cells, (dev_id, fill, ppm, glitches) in zip(self._cells, rows):
            dev = self.state.project.find_device(dev_id)
            texts = (dev.title if dev is not None else dev_id, f"{fill:.0f} ms", f"{ppm:+.0f} ppm",
                     str(glitches))
            for cell, text in zip(cells, texts):
                cell.setText(text)

    def showEvent(self, ev):
        super().showEvent(ev)
        if self.last:
            self.show_readings()

    def restyle(self) -> None:
        for tile in (self.cpu, self.memory, self.load, self.delay, self.dropouts, self.pc):
            tile.restyle()
        self.chart.update()
