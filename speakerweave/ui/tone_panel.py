"""The Tone generator panel: a tone of any pitch from 1 Hz to 20,000 Hz on the speakers you
pick, played steady, as beeps, as a pattern of notes or as a sweep."""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QPushButton,
                               QSizePolicy, QSlider,
                               QSpinBox, QStackedWidget, QTabBar, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .. import tones
from ..model import OFF
from .panels import dim

SLIDER_STEPS = 1000
QUICK = (50.0, 100.0, 440.0, 1000.0, 10000.0)


def hz_to_slider(hz: float) -> int:
    hz = tones.clamp_hz(hz)
    return int(round(math.log(hz / tones.LOWEST) / math.log(tones.HIGHEST / tones.LOWEST) * SLIDER_STEPS))


def slider_to_hz(value: int) -> float:
    hz = tones.LOWEST * (tones.HIGHEST / tones.LOWEST) ** (value / float(SLIDER_STEPS))
    # round to what a person would type: whole hertz above 100, tenths below
    return float(round(hz) if hz >= 100 else round(hz, 1))


def _hz_box(value: float) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(tones.LOWEST, tones.HIGHEST)
    box.setDecimals(2)
    box.setSuffix(" Hz")
    box.setKeyboardTracking(False)
    box.setValue(value)
    return box


class TonePanel(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self._loading = False
        spec = tones.clean(state.settings.tone)
        col = QVBoxLayout(self)
        col.setContentsMargins(4, 4, 4, 4)
        col.setSpacing(8)

        # play and stop first, like a transport, with where it plays beside them
        row = QHBoxLayout()
        self.play_btn = QPushButton("Play")
        self.play_btn.setObjectName("primary")
        self.stop_btn = QPushButton("Stop")
        row.addWidget(self.play_btn)
        row.addWidget(self.stop_btn)
        row.addSpacing(8)
        row.addWidget(QLabel("on"))
        self.target = QComboBox()
        self.target.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.target.setMinimumContentsLength(10)
        self.target.setToolTip("Which speakers play the tone. The PC sound waits on every speaker "
                               "while a tone plays.")
        row.addWidget(self.target, 1)
        col.addLayout(row)
        self.status = dim("")
        self.status.setWordWrap(True)
        col.addWidget(self.status)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        # pitch: typed, or on a slider spread evenly over the octaves from 1 Hz to 20 kHz
        self.hz = _hz_box(spec["hz"])
        self.hz.setToolTip("The pitch, from 1 Hz to 20,000 Hz")
        self.hz_slider = QSlider(Qt.Horizontal)
        self.hz_slider.setRange(0, SLIDER_STEPS)
        self.hz_slider.setValue(hz_to_slider(spec["hz"]))
        self.hz_slider.setToolTip("Every octave takes the same room on the slider")
        row = QHBoxLayout()
        row.addWidget(self.hz)
        row.addWidget(self.hz_slider, 1)
        form.addRow("Frequency", row)
        quick = QHBoxLayout()
        quick.setSpacing(4)
        down = QPushButton("÷2")
        down.setObjectName("quick")
        down.setToolTip("An octave lower")
        down.clicked.connect(lambda: self.hz.setValue(max(tones.LOWEST, self.hz.value() / 2.0)))
        quick.addWidget(down)
        for hz in QUICK:
            button = QPushButton(tones.hz_text(hz).replace(" ", ""))
            button.setObjectName("quick")
            button.setToolTip(f"Set the pitch to {tones.hz_text(hz)}")
            button.clicked.connect(lambda _c=False, h=hz: self.hz.setValue(h))
            quick.addWidget(button)
        up = QPushButton("×2")
        up.setObjectName("quick")
        up.setToolTip("An octave higher")
        up.clicked.connect(lambda: self.hz.setValue(min(tones.HIGHEST, self.hz.value() * 2.0)))
        quick.addWidget(up)
        quick.addStretch(1)
        form.addRow("", quick)

        self.wave = QComboBox()
        for key, name in tones.WAVES.items():
            self.wave.addItem(name, key)
        self.wave.setCurrentIndex(max(0, self.wave.findData(spec["wave"])))
        self.wave.setToolTip("Sine is a pure tone. Square, triangle and saw add overtones, so they "
                             "sound brighter and are easier to hear on small speakers.")
        form.addRow("Wave", self.wave)

        self.level = QSlider(Qt.Horizontal)
        self.level.setRange(-60, 0)
        self.level.setValue(int(round(spec["db"])))
        self.level_text = QLabel("")
        self.level_text.setFixedWidth(52)
        row = QHBoxLayout()
        row.addWidget(self.level, 1)
        row.addWidget(self.level_text)
        form.addRow("Level", row)
        col.addLayout(form)

        # how it plays
        self.kind_tabs = QTabBar()
        self.kind_tabs.setExpanding(False)
        self.kind_tabs.setDrawBase(False)
        for key, name in tones.KINDS.items():
            self.kind_tabs.addTab(name)
            self.kind_tabs.setTabData(self.kind_tabs.count() - 1, key)
        col.addWidget(self.kind_tabs)
        self.kind_pages = QStackedWidget()
        self.kind_pages.addWidget(self._steady_page())
        self.kind_pages.addWidget(self._beeps_page(spec))
        self.kind_pages.addWidget(self._pattern_page(spec))
        self.kind_pages.addWidget(self._sweep_page(spec))
        col.addWidget(self.kind_pages)
        self.kind_tabs.setCurrentIndex(list(tones.KINDS).index(spec["kind"]))
        self.kind_pages.setCurrentIndex(self.kind_tabs.currentIndex())
        self._fit_page()

        self.warning = QLabel("")
        self.warning.setObjectName("warn")
        self.warning.setWordWrap(True)
        col.addWidget(self.warning)
        col.addWidget(dim("Start quietly and turn up slowly. Very low, very high and long loud tones "
                          "can damage speakers and hearing."))
        col.addStretch(1)

        self.hz.valueChanged.connect(self._hz_typed)
        self.hz_slider.valueChanged.connect(self._hz_slid)
        self.wave.activated.connect(lambda _i: self._changed(live=True))
        self.level.valueChanged.connect(lambda _v: self._changed(live=True))
        self.kind_tabs.currentChanged.connect(self._kind_changed)
        self.play_btn.clicked.connect(self.play)
        self.stop_btn.clicked.connect(self.state.stop_tone)
        self.target.activated.connect(self._target_chosen)
        state.toneChanged.connect(self._show_state)
        state.structureChanged.connect(self._fill_targets)
        state.selectionChanged.connect(self._show_state)
        self._fill_targets()
        self._changed(live=False)
        self._show_state()

    # ---------------------------------------------------------- the four ways to play
    def _steady_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 6, 0, 0)
        v.addWidget(dim("One tone that plays until you press Stop. Change the pitch, wave or level "
                        "while it plays."))
        v.addStretch(1)
        return page

    def _ms_box(self, value: int, low: int, high: int) -> QSpinBox:
        box = QSpinBox()
        box.setRange(low, high)
        box.setSingleStep(10)
        box.setSuffix(" ms")
        box.setValue(int(value))
        box.valueChanged.connect(lambda _v: self._changed(live=False))
        return box

    def _repeat_box(self, value: int) -> QSpinBox:
        box = QSpinBox()
        box.setRange(0, 9999)
        box.setSpecialValueText("Until stopped")
        box.setSuffix(" times")
        box.setValue(int(value))
        box.valueChanged.connect(lambda _v: self._changed(live=False))
        return box

    def _beeps_page(self, spec) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 6, 0, 0)
        form.setHorizontalSpacing(12)
        self.beep_ms = self._ms_box(spec["beep_ms"], 10, 10000)
        self.gap_ms = self._ms_box(spec["gap_ms"], 0, 10000)
        self.beep_repeat = self._repeat_box(spec["repeat"])
        form.addRow("Beep", self.beep_ms)
        form.addRow("Gap", self.gap_ms)
        form.addRow("Repeat", self.beep_repeat)
        return page

    def _pattern_page(self, spec) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 6, 0, 0)
        v.setSpacing(6)
        row = QHBoxLayout()
        self.preset = QComboBox()
        self.preset.setToolTip("Ready made patterns, and the ones you saved")
        row.addWidget(self.preset, 1)
        self.save_pattern = QPushButton("Save...")
        self.save_pattern.setToolTip("Keep this pattern under a name of your own")
        self.delete_pattern = QPushButton("Delete")
        row.addWidget(self.save_pattern)
        row.addWidget(self.delete_pattern)
        v.addLayout(row)
        self.steps = QTableWidget(0, 2)
        self.steps.setHorizontalHeaderLabels(["Pitch (Hz, 0 for a rest)", "Length (ms)"])
        self.steps.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.steps.verticalHeader().setVisible(False)
        self.steps.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.steps.setMinimumHeight(140)
        v.addWidget(self.steps, 1)
        row = QHBoxLayout()
        add = QPushButton("Add note")
        rest = QPushButton("Add rest")
        remove = QPushButton("Remove")
        row.addWidget(add)
        row.addWidget(rest)
        row.addWidget(remove)
        row.addStretch(1)
        v.addLayout(row)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        self.pattern_repeat = self._repeat_box(spec["repeat"])
        form.addRow("Repeat", self.pattern_repeat)
        v.addLayout(form)
        self._set_steps(spec["steps"])
        self._fill_presets()
        add.clicked.connect(lambda: self._add_step(self.hz.value()))
        rest.clicked.connect(lambda: self._add_step(0.0))
        remove.clicked.connect(self._remove_steps)
        self.steps.itemChanged.connect(lambda _i: self._changed(live=False))
        self.preset.activated.connect(self._preset_chosen)
        self.save_pattern.clicked.connect(self._save_pattern)
        self.delete_pattern.clicked.connect(self._delete_pattern)
        return page

    def _sweep_page(self, spec) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 6, 0, 0)
        form.setHorizontalSpacing(12)
        self.sweep_from = _hz_box(spec["sweep_from"])
        self.sweep_to = _hz_box(spec["sweep_to"])
        self.sweep_s = QDoubleSpinBox()
        self.sweep_s.setRange(0.2, 600.0)
        self.sweep_s.setDecimals(1)
        self.sweep_s.setSuffix(" s")
        self.sweep_s.setValue(spec["sweep_s"])
        self.sweep_log = QCheckBox("Evenly through the octaves (logarithmic)")
        self.sweep_log.setChecked(spec["sweep_log"])
        self.sweep_back = QCheckBox("There and back")
        self.sweep_back.setChecked(spec["sweep_back"])
        self.sweep_repeat = self._repeat_box(spec["repeat"])
        form.addRow("From", self.sweep_from)
        form.addRow("To", self.sweep_to)
        form.addRow("Over", self.sweep_s)
        form.addRow("", self.sweep_log)
        form.addRow("", self.sweep_back)
        form.addRow("Repeat", self.sweep_repeat)
        for box in (self.sweep_from, self.sweep_to, self.sweep_s):
            box.valueChanged.connect(lambda _v: self._changed(live=False))
        for box in (self.sweep_log, self.sweep_back):
            box.toggled.connect(lambda _v: self._changed(live=False))
        return page

    # ---------------------------------------------------------- pattern steps
    def _set_steps(self, steps: list) -> None:
        self._loading = True
        self.steps.setRowCount(0)
        for hz, ms in steps:
            self._append_row(hz, ms)
        self._loading = False

    def _append_row(self, hz: float, ms: int) -> None:
        row = self.steps.rowCount()
        self.steps.insertRow(row)
        self.steps.setItem(row, 0, QTableWidgetItem("rest" if hz <= 0 else f"{hz:g}"))
        self.steps.setItem(row, 1, QTableWidgetItem(str(int(ms))))

    def _add_step(self, hz: float) -> None:
        if self.steps.rowCount() >= tones.MAX_STEPS:
            return
        self._loading = True
        self._append_row(hz, 250 if hz > 0 else 120)
        self._loading = False
        self._changed(live=False)

    def _remove_steps(self) -> None:
        rows = sorted({i.row() for i in self.steps.selectedIndexes()}, reverse=True)
        if not rows and self.steps.rowCount():
            rows = [self.steps.rowCount() - 1]
        for row in rows:
            self.steps.removeRow(row)
        self._changed(live=False)

    def table_steps(self) -> list:
        text = []
        for row in range(self.steps.rowCount()):
            hz = self.steps.item(row, 0)
            ms = self.steps.item(row, 1)
            if hz is not None and ms is not None:
                text.append(f"{hz.text().strip() or 'rest'} {ms.text().strip()}")
        return tones.parse_steps(", ".join(text))

    def _fill_presets(self) -> None:
        self.preset.clear()
        self.preset.addItem("Choose a pattern...", "")
        for name in tones.PATTERNS:
            self.preset.addItem(name, name)
        saved = self.state.settings.tone_patterns
        if saved:
            self.preset.insertSeparator(self.preset.count())
            for name in saved:
                self.preset.addItem(name, "saved:" + name)
        self.delete_pattern.setEnabled(False)

    def _preset_chosen(self, _i: int) -> None:
        key = self.preset.currentData() or ""
        if key.startswith("saved:"):
            steps = self.state.settings.tone_patterns.get(key[6:])
        else:
            steps = tones.PATTERNS.get(key)
        self.delete_pattern.setEnabled(key.startswith("saved:"))
        if steps:
            self._set_steps(steps)
            self._changed(live=False)

    def _save_pattern(self) -> None:
        name, ok = QInputDialog.getText(self, "Save pattern", "A name for this pattern:")
        name = " ".join(str(name or "").split())[:40]
        if not ok or not name or name in tones.PATTERNS:
            return
        self.state.settings.tone_patterns[name] = self.table_steps()
        self.state.save_settings()
        self._fill_presets()
        self.preset.setCurrentIndex(self.preset.findData("saved:" + name))
        self.delete_pattern.setEnabled(True)

    def _delete_pattern(self) -> None:
        key = self.preset.currentData() or ""
        if key.startswith("saved:"):
            self.state.settings.tone_patterns.pop(key[6:], None)
            self.state.save_settings()
            self._fill_presets()

    # ---------------------------------------------------------- reading the panel
    def spec(self) -> dict:
        kind = self.kind_tabs.tabData(self.kind_tabs.currentIndex())
        repeat = {"beeps": self.beep_repeat, "pattern": self.pattern_repeat,
                  "sweep": self.sweep_repeat}.get(kind)
        return tones.clean({
            "kind": kind, "hz": self.hz.value(), "wave": self.wave.currentData(),
            "db": float(self.level.value()), "beep_ms": self.beep_ms.value(),
            "gap_ms": self.gap_ms.value(), "repeat": repeat.value() if repeat is not None else 0,
            "steps": self.table_steps(), "sweep_from": self.sweep_from.value(),
            "sweep_to": self.sweep_to.value(), "sweep_s": self.sweep_s.value(),
            "sweep_log": self.sweep_log.isChecked(), "sweep_back": self.sweep_back.isChecked(),
        })

    def _hz_typed(self, hz: float) -> None:
        self.hz_slider.blockSignals(True)
        self.hz_slider.setValue(hz_to_slider(hz))
        self.hz_slider.blockSignals(False)
        self._changed(live=True)

    def _hz_slid(self, value: int) -> None:
        self.hz.blockSignals(True)
        self.hz.setValue(slider_to_hz(value))
        self.hz.blockSignals(False)
        self._changed(live=True)

    def _kind_changed(self, index: int) -> None:
        self.kind_pages.setCurrentIndex(index)
        self._fit_page()
        self._changed(live=False)

    def _fit_page(self) -> None:
        """Only the page in front takes room, so Steady tone is not as tall as Pattern."""
        for i in range(self.kind_pages.count()):
            page = self.kind_pages.widget(i)
            policy = QSizePolicy.Preferred if i == self.kind_pages.currentIndex() else QSizePolicy.Ignored
            page.setSizePolicy(policy, policy)
        self.kind_pages.adjustSize()

    def _changed(self, live: bool) -> None:
        if self._loading:
            return
        spec = self.spec()
        self.state.settings.tone = spec
        self.level_text.setText(f"{spec['db']:.0f} dB")
        low = min(spec["hz"], spec["sweep_from"], spec["sweep_to"]) if spec["kind"] == "sweep" \
            else (min([hz for hz, _ms in spec["steps"] if hz > 0] or [spec["hz"]])
                  if spec["kind"] == "pattern" else spec["hz"])
        notes = []
        if low < tones.LOW_WARNING_HZ:
            notes.append(f"Below {tones.LOW_WARNING_HZ:g} Hz most speakers cannot play a tone, and a "
                         f"loud one can damage them. Subwoofers and bass shakers handle it best.")
        if spec["db"] > -6:
            notes.append("This is loud. Turn your amplifier down before you press Play.")
        self.warning.setText(" ".join(notes))
        self.warning.setVisible(bool(notes))
        if self.state.tone_playing:
            tone = self.state.engine._tone
            if live and tone is not None and spec["kind"] in ("steady", "beeps") \
                    and tone[0].spec["kind"] == spec["kind"]:
                tone[0].retune(spec)                     # follows the knobs while it plays
            else:
                self._show_state()

    def _fill_targets(self) -> None:
        chosen = self.state.settings.tone_target
        self.target.clear()
        self.target.addItem("Every speaker that plays", "all")
        self.target.addItem("The selected speaker", "selected")
        for dev, spk in self.state.project.all_speakers():
            if dev.enabled and spk.role != OFF:
                self.target.addItem(f"{spk.name} ({dev.title})", spk.id)
        index = self.target.findData(chosen)
        self.target.setCurrentIndex(index if index >= 0 else 0)

    def _target_chosen(self, _i: int) -> None:
        self.state.settings.tone_target = self.target.currentData()
        if self.state.tone_playing:
            self.state.refresh_tone()

    # ---------------------------------------------------------- playing
    def play(self) -> None:
        self.state.play_tone(self.spec(), self.target.currentData() or "all")

    def _show_state(self) -> None:
        playing = self.state.tone_playing
        self.stop_btn.setEnabled(playing)
        self.play_btn.setText("Play again" if playing else "Play")
        if playing:
            count = len(self.state.engine._tone[1]) if self.state.engine._tone else 0
            self.status.setText(f"Playing {tones.describe(self.state.engine._tone[0].spec)} on "
                                f"{count} speaker{'s' if count != 1 else ''}. The PC sound waits "
                                f"meanwhile.")
        else:
            self.status.setText(f"Ready: {tones.describe(self.spec())}.")
