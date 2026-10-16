"""The settings panels on the right: speaker, output device, sound and lights."""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMenu,
                               QPushButton, QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget)

from ..model import (EQBand, OFF, ROLE_COLORS, ROLE_NAMES, can_move_alone, default_eq, face_listener,
                     is_shaker, is_sub,
                     is_shape, move_speaker, partner_speaker, set_attached, speaker_position)
from .. import speaker_library
from ..presets import BY_KEY as PRESETS_BY_KEY, RANGE_PRESETS, apply_range_preset, matching_preset
from ..rgb import RGB_MODES
from . import theme
from .eqgraph import EqGraph, MAX_BANDS, Q_MAX, Q_MIN, freq_text

SLOPES = [(12, "Gentle, 12 dB/oct"), (24, "Normal, 24 dB/oct"), (48, "Steep, 48 dB/oct")]
BAND_KINDS = [("peak", "Bell"), ("lowshelf", "Low shelf"), ("highshelf", "High shelf")]


def dim(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("dim")
    label.setWordWrap(True)
    return label


def fill_sound_menu(menu, state, play) -> None:
    """Fills a menu with every test sound: noise, sweep and the user's own."""
    menu.clear()
    first_own = True
    for kind, name in state.test_sound_choices():
        if kind.startswith("custom") and first_own:
            menu.addSeparator()
            first_own = False
        menu.addAction(name, lambda k=kind: play(k))


def tag(text: str) -> QLabel:
    """A short faint label that always stays on one line."""
    label = QLabel(text)
    label.setObjectName("dim")
    return label


def scrolled(inner: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setWidget(inner)
    return area


def slim_combo() -> QComboBox:
    """A drop down that shrinks with the panel instead of forcing it wider."""
    box = QComboBox()
    box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    box.setMinimumContentsLength(8)
    return box


def freq_spin() -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(10.0, 20000.0)
    spin.setDecimals(1)
    spin.setSuffix(" Hz")
    spin.setStepType(QDoubleSpinBox.AdaptiveDecimalStepType)
    spin.setKeyboardTracking(False)
    return spin


class NumSlider(QWidget):
    """A slider with an exact number box next to it."""
    valueChanged = Signal(float)

    def __init__(self, low: float, high: float, step: float, suffix: str, decimals: int = 1):
        super().__init__()
        self._step = step
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(round(low / step), round(high / step))
        self.spin = QDoubleSpinBox()
        self.spin.setRange(low, high)
        self.spin.setSingleStep(step)
        self.spin.setDecimals(decimals)
        self.spin.setSuffix(suffix)
        self.spin.setKeyboardTracking(False)
        self.spin.setFixedWidth(96)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.slider, 1)
        row.addWidget(self.spin)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)

    def _from_slider(self, v: int) -> None:
        self.spin.blockSignals(True)
        self.spin.setValue(v * self._step)
        self.spin.blockSignals(False)
        self.valueChanged.emit(self.spin.value())

    def _from_spin(self, v: float) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(round(v / self._step))
        self.slider.blockSignals(False)
        self.valueChanged.emit(v)

    def value(self) -> float:
        return self.spin.value()

    def setValue(self, v: float) -> None:
        for w in (self.slider, self.spin):
            w.blockSignals(True)
        self.spin.setValue(v)
        self.slider.setValue(round(v / self._step))
        for w in (self.slider, self.spin):
            w.blockSignals(False)


# ======================================================================= speaker

class SpeakerPanel(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self._loading = False
        self._busy = False
        self._moving = False

        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(10, 10, 10, 10)
        col.setSpacing(6)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrolled(inner))

        self.empty = dim("Click a speaker on the room map, or in the list on the left, "
                         "to change what it plays and how it sounds.")
        col.addWidget(self.empty)
        self.body = QWidget()
        col.addWidget(self.body)
        col.addStretch(1)
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)

        # ---- header
        head = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Speaker name")
        self.identify = QPushButton("Play test sound")
        self.identify.setToolTip("Plays a sound on this speaker only. Right click a speaker on the "
                                 "map for the same choices.")
        sound_menu = QMenu(self.identify)
        sound_menu.aboutToShow.connect(lambda: fill_sound_menu(sound_menu, self.state, self._play))
        fill_sound_menu(sound_menu, self.state, self._play)
        self.identify.setMenu(sound_menu)
        head.addWidget(self.name, 1)
        head.addWidget(self.identify)
        body.addLayout(head)
        self.where = dim("")
        body.addWidget(self.where)

        # ---- role and level
        box = QGroupBox("What it plays")
        form = QFormLayout(box)
        self.role = slim_combo()
        form.addRow("Role", self.role)
        self.gain = NumSlider(-30.0, 12.0, 0.5, " dB")
        form.addRow("Volume", self.gain)
        self.delay = NumSlider(0.0, 300.0, 0.1, " ms", 1)
        self.delay.setToolTip("Hold this speaker back so its sound arrives together with the others")
        form.addRow("Delay", self.delay)
        toggles = QHBoxLayout()
        self.mute = QPushButton("Mute")
        self.solo = QPushButton("Solo")
        self.invert = QPushButton("Flip polarity")
        for b in (self.mute, self.solo, self.invert):
            b.setCheckable(True)
            toggles.addWidget(b)
        self.solo.setToolTip("Hear only this speaker")
        self.invert.setToolTip("Try this if the bass gets thinner when this speaker joins in")
        form.addRow("", toggles)
        body.addWidget(box)

        # ---- position
        box = QGroupBox("Position in the room")
        form = QFormLayout(box)
        self.pos_x = DevicePanel._metres(-50, 50)
        self.pos_y = DevicePanel._metres(-50, 50)
        form.addRow("Left / right", self.pos_x)
        form.addRow("Front / back", self.pos_y)
        self.pos_hint = dim("")
        form.addRow(self.pos_hint)
        body.addWidget(box)

        # ---- frequency range
        box = QGroupBox("Frequency range")
        grid = QGridLayout(box)
        self.hp_on = QCheckBox("Nothing below")
        self.hp_freq = freq_spin()
        self.hp_slope = slim_combo()
        self.lp_on = QCheckBox("Nothing above")
        self.lp_freq = freq_spin()
        self.lp_slope = slim_combo()
        for combo in (self.hp_slope, self.lp_slope):
            for value, text in SLOPES:
                combo.addItem(text, value)
        grid.addWidget(self.hp_on, 0, 0)
        grid.addWidget(self.hp_freq, 0, 1)
        grid.addWidget(self.hp_slope, 0, 2)
        grid.addWidget(self.lp_on, 1, 0)
        grid.addWidget(self.lp_freq, 1, 1)
        grid.addWidget(self.lp_slope, 1, 2)
        grid.setColumnStretch(2, 1)
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Speaker type"))
        self.speaker_type = slim_combo()
        self.speaker_type.addItem("Custom (set by hand)", "")
        for preset in RANGE_PRESETS:
            self.speaker_type.addItem(preset.name, preset.key)
            self.speaker_type.setItemData(self.speaker_type.count() - 1, preset.hint, Qt.ToolTipRole)
        self.speaker_type.setToolTip("Fills in a sensible frequency range for this kind of speaker")
        type_row.addWidget(self.speaker_type, 1)
        grid.addLayout(type_row, 2, 0, 1, 3)
        self.type_hint = dim("")
        grid.addWidget(self.type_hint, 3, 0, 1, 3)
        self.range_text = dim("")
        grid.addWidget(self.range_text, 4, 0, 1, 3)
        body.addWidget(box)

        # ---- equaliser
        box = QGroupBox("Equaliser")
        eq = QVBoxLayout(box)
        bar = QHBoxLayout()
        self.eq_on = QCheckBox("On")
        self.eq_add = QPushButton("Add")
        self.eq_del = QPushButton("Remove")
        self.eq_flat = QPushButton("Flat")
        self.eq_copy = QPushButton("Copy")
        self.eq_paste = QPushButton("Paste")
        self.eq_add.setToolTip("Add a band")
        self.eq_del.setToolTip("Remove the selected band")
        self.eq_flat.setToolTip("Reset the equaliser to flat")
        self.eq_copy.setToolTip("Copy this speaker's equaliser and frequency range")
        self.eq_paste.setToolTip("Paste the copied equaliser and frequency range onto this speaker")
        bar.addWidget(self.eq_on)
        bar.addStretch(1)
        for b in (self.eq_add, self.eq_del, self.eq_flat, self.eq_copy, self.eq_paste):
            bar.addWidget(b)
        eq.addLayout(bar)
        self.graph = EqGraph()
        eq.addWidget(self.graph)
        band = QGridLayout()
        self.band_title = QLabel("Band")
        self.band_kind = slim_combo()
        for value, text in BAND_KINDS:
            self.band_kind.addItem(text, value)
        self.band_freq = freq_spin()
        self.band_gain = QDoubleSpinBox()
        self.band_gain.setRange(-18.0, 18.0)
        self.band_gain.setSingleStep(0.5)
        self.band_gain.setDecimals(1)
        self.band_gain.setSuffix(" dB")
        self.band_q = QDoubleSpinBox()
        self.band_q.setRange(Q_MIN, Q_MAX)
        self.band_q.setSingleStep(0.1)
        self.band_q.setDecimals(2)
        self.band_q.setToolTip("Sharpness. Low = wide and gentle, high = narrow and precise")
        self.band_on = QCheckBox("Band on")
        for w in (self.band_gain, self.band_q):
            w.setKeyboardTracking(False)
        band.addWidget(self.band_title, 0, 0)
        band.addWidget(self.band_kind, 0, 1)
        band.addWidget(self.band_on, 0, 2, 1, 2)
        band.addWidget(dim("Frequency"), 1, 0)
        band.addWidget(self.band_freq, 1, 1)
        band.addWidget(dim("Gain"), 1, 2)
        band.addWidget(self.band_gain, 1, 3)
        band.addWidget(dim("Sharpness (Q)"), 2, 0)
        band.addWidget(self.band_q, 2, 1)
        eq.addLayout(band)
        eq.addWidget(dim("Drag a dot to shape the sound. Scroll over a dot to make it wider or "
                         "narrower. Double click empty space for a new band. The orange lines "
                         "are the frequency limits and can be dragged too."))
        body.addWidget(box)

        # ---- lights
        box = QGroupBox("Lights (RGB)")
        form = QFormLayout(box)
        self.rgb_target = slim_combo()
        self.rgb_mode = slim_combo()
        for value, text in RGB_MODES.items():
            self.rgb_mode.addItem(text, value)
        row = QHBoxLayout()
        self.rgb_role = QCheckBox("Use the role colour")
        self.rgb_pick = QPushButton("Pick colour")
        row.addWidget(self.rgb_role)
        row.addWidget(self.rgb_pick)
        row.addStretch(1)
        form.addRow("Light", self.rgb_target)
        form.addRow("Effect", self.rgb_mode)
        form.addRow("Colour", row)
        self.rgb_hint = dim("")
        form.addRow(self.rgb_hint)
        body.addWidget(box)

        # ---- wiring
        self.name.editingFinished.connect(self._name_edited)
        self.role.activated.connect(self._role_changed)
        self.gain.valueChanged.connect(lambda v: self._set("gain_db", v))
        self.delay.valueChanged.connect(lambda v: self._set("delay_ms", v))
        self.mute.toggled.connect(lambda v: self._set_routing("mute", v))
        self.solo.toggled.connect(lambda v: self._set_routing("solo", v))
        self.invert.toggled.connect(lambda v: self._set("invert", v))
        self.pos_x.valueChanged.connect(lambda _v: self._position_edited())
        self.pos_y.valueChanged.connect(lambda _v: self._position_edited())
        self.hp_on.toggled.connect(lambda v: self._set("hp_on", v))
        self.lp_on.toggled.connect(lambda v: self._set("lp_on", v))
        self.hp_freq.valueChanged.connect(lambda v: self._set("hp_freq", v))
        self.lp_freq.valueChanged.connect(lambda v: self._set("lp_freq", v))
        self.hp_slope.activated.connect(lambda _i: self._set("hp_slope", self.hp_slope.currentData()))
        self.lp_slope.activated.connect(lambda _i: self._set("lp_slope", self.lp_slope.currentData()))
        self.speaker_type.activated.connect(self._type_chosen)
        self.eq_on.toggled.connect(lambda v: self._set("eq_on", v))
        self.eq_add.clicked.connect(self._add_band)
        self.eq_del.clicked.connect(self._del_band)
        self.eq_flat.clicked.connect(self._flat)
        self.eq_copy.clicked.connect(self._copy)
        self.eq_paste.clicked.connect(self._paste)
        self.graph.changed.connect(self._graph_changed)
        self.graph.bandSelected.connect(lambda _i: self._load_band())
        self.band_kind.activated.connect(lambda _i: self._set_band("kind", self.band_kind.currentData()))
        self.band_freq.valueChanged.connect(lambda v: self._set_band("freq", v))
        self.band_gain.valueChanged.connect(lambda v: self._set_band("gain_db", v))
        self.band_q.valueChanged.connect(lambda v: self._set_band("q", v))
        self.band_on.toggled.connect(lambda v: self._set_band("enabled", v))
        self.rgb_target.activated.connect(self._rgb_changed)
        self.rgb_mode.activated.connect(self._rgb_changed)
        self.rgb_role.toggled.connect(self._rgb_role_toggled)
        self.rgb_pick.clicked.connect(self._pick_colour)

        state.selectionChanged.connect(self.load)
        state.structureChanged.connect(self._external_change)
        state.speakerChanged.connect(lambda _id: self._external_change())
        state.layoutChanged.connect(self._load_position)
        self.load()

    # ------------------------------------------------------------ helpers
    def _spk(self):
        return self.state.selected_speaker()[1]

    def _external_change(self) -> None:
        if not self._busy:
            self.load()

    def _commit(self, routing: bool = False) -> None:
        spk = self._spk()
        if spk is None:
            return
        self._busy = True
        try:
            if routing:
                self.state.touch_routing()
            else:
                self.state.touch_speaker(spk.id)
        finally:
            self._busy = False
        self.graph.update()
        self._range_summary()

    def _set(self, field: str, value) -> None:
        spk = self._spk()
        if self._loading or spk is None:
            return
        setattr(spk, field, value)
        self._commit()

    def _set_routing(self, field: str, value) -> None:
        spk = self._spk()
        if self._loading or spk is None:
            return
        setattr(spk, field, value)
        self._commit(routing=True)

    # ------------------------------------------------------------ loading
    def load(self) -> None:
        dev, spk = self.state.selected_speaker()
        self.empty.setVisible(spk is None)
        self.body.setVisible(spk is not None)
        if spk is None:
            self.graph.set_speaker(None, self.state.engine.sr, theme.ACCENT)
            return
        self._loading = True
        try:
            proj = self.state.project
            self.name.setText(spk.name)
            kind = "built into" if dev.kind == "builtin" else "plugged into the aux out of"
            self.where.setText(f"Channel {spk.channel + 1} of {dev.title}, {kind} it")
            self.role.clear()
            for role in proj.role_choices():
                self.role.addItem(ROLE_NAMES[role], role)
            if spk.role not in proj.role_choices():
                self.role.addItem(ROLE_NAMES.get(spk.role, spk.role), spk.role)
            self.role.setCurrentIndex(max(0, self.role.findData(spk.role)))
            self.gain.setValue(spk.gain_db)
            self.delay.setValue(spk.delay_ms)
            self.mute.setChecked(spk.mute)
            self.solo.setChecked(spk.solo)
            self.invert.setChecked(spk.invert)
            self._load_position()
            self._load_limits()
            self.eq_on.setChecked(spk.eq_on)
            self.eq_paste.setEnabled(self.state.eq_clipboard is not None)
            self.graph.set_speaker(spk, self.state.engine.sr, ROLE_COLORS.get(spk.role, theme.ACCENT))
            self._load_band()
            self._load_rgb(spk)
        finally:
            self._loading = False
        self._range_summary()

    def _load_position(self) -> None:
        """Shows where the selected speaker is. Follows the room map live."""
        dev, spk = self.state.selected_speaker()
        if spk is None or self._moving:
            return
        was, self._loading = self._loading, True
        x, y = speaker_position(dev, spk)
        self.pos_x.setValue(x)
        self.pos_y.setValue(y)
        movable = can_move_alone(dev, spk)
        self.pos_x.setEnabled(movable)
        self.pos_y.setEnabled(movable)
        if not movable:
            hint = "This speaker sits inside its unit. Move the unit on the Output tab."
        elif self.state.project.mirror and partner_speaker(dev, spk) is not None:
            hint = (f"Mirror is on: {partner_speaker(dev, spk).name} moves the opposite way "
                    f"sideways and the same way front to back.")
        elif dev.kind == "builtin":
            hint = "Moving one end stretches and turns the unit. The other end stays put."
        else:
            hint = ""
        self.pos_hint.setText(hint)
        self.pos_hint.setVisible(bool(hint))
        self._loading = was

    def _position_edited(self) -> None:
        dev, spk = self.state.selected_speaker()
        if self._loading or spk is None or not can_move_alone(dev, spk):
            return
        move_speaker(dev, spk, self.pos_x.value(), self.pos_y.value(), self.state.project.mirror)
        self._moving = True         # do not rewrite the box that is being typed in
        try:
            self.state.touch_layout()
        finally:
            self._moving = False

    def _load_limits(self) -> None:
        spk = self._spk()
        was, self._loading = self._loading, True
        self.hp_on.setChecked(spk.hp_on)
        self.lp_on.setChecked(spk.lp_on)
        self.hp_freq.setValue(spk.hp_freq)
        self.lp_freq.setValue(spk.lp_freq)
        self.hp_slope.setCurrentIndex(max(0, self.hp_slope.findData(int(spk.hp_slope))))
        self.lp_slope.setCurrentIndex(max(0, self.lp_slope.findData(int(spk.lp_slope))))
        self._loading = was

    def _range_summary(self) -> None:
        spk = self._spk()
        if spk is None:
            return
        key = matching_preset(spk)
        spk.range_preset = key
        self.speaker_type.blockSignals(True)
        self.speaker_type.setCurrentIndex(max(0, self.speaker_type.findData(key)))
        self.speaker_type.blockSignals(False)
        self.type_hint.setText(PRESETS_BY_KEY[key].hint if key else
                               "The limits were set by hand. Pick a speaker type to start again.")
        if spk.hp_on and spk.lp_on:
            text = f"Plays only {freq_text(spk.hp_freq)} to {freq_text(spk.lp_freq)}."
        elif spk.hp_on:
            text = f"Plays everything from {freq_text(spk.hp_freq)} up."
        elif spk.lp_on:
            text = f"Plays everything up to {freq_text(spk.lp_freq)}."
        else:
            text = "Plays the full range."
        if spk.hp_on and self.state.engine.keep_lows and not is_sub(spk.role) \
                and not is_shaker(spk.role):
            text += (f" No subwoofer is playing, so it keeps its notes below "
                     f"{freq_text(spk.hp_freq)} for now (Sound tab, Bass).")
        self.range_text.setText(text)

    def _band(self):
        spk = self._spk()
        i = self.graph.selected
        if spk is None or not (0 <= i < len(spk.eq)):
            return None
        return spk.eq[i]

    def _load_band(self) -> None:
        band = self._band()
        was, self._loading = self._loading, True
        widgets = (self.band_kind, self.band_freq, self.band_gain, self.band_q, self.band_on)
        for w in widgets:
            w.setEnabled(band is not None)
        self.eq_del.setEnabled(band is not None)
        spk = self._spk()
        self.eq_add.setEnabled(spk is not None and len(spk.eq) < MAX_BANDS)
        if band is None:
            self.band_title.setText("Click a dot")
        else:
            self.band_title.setText(f"Band {self.graph.selected + 1}")
            self.band_kind.setCurrentIndex(max(0, self.band_kind.findData(band.kind)))
            self.band_freq.setValue(band.freq)
            self.band_gain.setValue(band.gain_db)
            self.band_q.setValue(band.q)
            self.band_on.setChecked(band.enabled)
        self._loading = was

    def _load_rgb(self, spk) -> None:
        rgb = self.state.rgb
        self.rgb_target.clear()
        self.rgb_target.addItem("None", ("", ""))
        for dev_name, zone, leds in rgb.targets():
            text = f"{dev_name} ({leds} LEDs)" if not zone else f"{dev_name}: {zone} ({leds} LEDs)"
            self.rgb_target.addItem(text, (dev_name, zone))
        want = (spk.rgb_device, spk.rgb_zone)
        index = next((i for i in range(self.rgb_target.count())
                      if tuple(self.rgb_target.itemData(i)) == want), -1)
        if index < 0:
            self.rgb_target.addItem(f"{spk.rgb_device} {spk.rgb_zone} (not found)".strip(), want)
            index = self.rgb_target.count() - 1
        self.rgb_target.setCurrentIndex(index)
        self.rgb_mode.setCurrentIndex(max(0, self.rgb_mode.findData(spk.rgb_mode)))
        self.rgb_role.setChecked(not spk.rgb_color)
        self._paint_pick(spk)
        self.rgb_hint.setText("" if rgb.connected else
                              "Connect to OpenRGB in the Lights tab to see your RGB hardware here.")
        self.rgb_hint.setVisible(not rgb.connected)

    def _paint_pick(self, spk) -> None:
        colour = spk.rgb_color or ROLE_COLORS.get(spk.role, "#ffffff")
        self.rgb_pick.setStyleSheet(f"background: {colour}; color: #0b1220; font-weight: 600;")
        self.rgb_pick.setEnabled(bool(spk.rgb_color))

    # ------------------------------------------------------------ actions
    def _name_edited(self) -> None:
        spk = self._spk()
        if self._loading or spk is None or spk.name == self.name.text().strip():
            return
        spk.name = self.name.text().strip() or spk.name
        self._commit(routing=True)

    def _role_changed(self, _index: int) -> None:
        spk = self._spk()
        if self._loading or spk is None:
            return
        self.state.project.set_role(spk, self.role.currentData())
        self._commit(routing=True)
        self.state.touch_speaker(spk.id)

    def _preset(self, key: str) -> None:
        spk = self._spk()
        if spk is None:
            return
        apply_range_preset(spk, key)
        self._load_limits()
        self._commit()

    def _type_chosen(self, _index: int) -> None:
        key = self.speaker_type.currentData()
        if key:
            self._preset(key)
        else:
            self._range_summary()

    def _play(self, kind: str) -> None:
        spk = self._spk()
        if spk is not None:
            self.state.identify(spk.id, kind)

    def _graph_changed(self) -> None:
        self._load_limits()
        self._load_band()
        self._commit()

    def _set_band(self, field: str, value) -> None:
        band = self._band()
        if self._loading or band is None:
            return
        setattr(band, field, value)
        self._commit()

    def _add_band(self) -> None:
        spk = self._spk()
        if spk is None or len(spk.eq) >= MAX_BANDS:
            return
        spk.eq.append(EQBand("peak", 1000.0, 3.0, 1.41))
        self.graph.selected = len(spk.eq) - 1
        self._load_band()
        self._commit()

    def _del_band(self) -> None:
        spk, band = self._spk(), self._band()
        if band is None:
            return
        spk.eq.remove(band)
        self.graph.selected = -1
        self._load_band()
        self._commit()

    def _flat(self) -> None:
        spk = self._spk()
        if spk is None:
            return
        spk.eq = default_eq()
        self.graph.selected = -1
        self._load_band()
        self._commit()

    def _copy(self) -> None:
        spk = self._spk()
        if spk is None:
            return
        self.state.eq_clipboard = {
            "eq": copy.deepcopy(spk.eq), "eq_on": spk.eq_on,
            "limits": (spk.hp_on, spk.hp_freq, spk.hp_slope, spk.lp_on, spk.lp_freq, spk.lp_slope)}
        self.eq_paste.setEnabled(True)
        self.state.notice.emit("Copied. Select another speaker and press Paste.")

    def _paste(self) -> None:
        spk, clip = self._spk(), self.state.eq_clipboard
        if spk is None or clip is None:
            return
        spk.eq = copy.deepcopy(clip["eq"])
        spk.eq_on = clip["eq_on"]
        (spk.hp_on, spk.hp_freq, spk.hp_slope, spk.lp_on, spk.lp_freq, spk.lp_slope) = clip["limits"]
        self.state.touch_speaker(spk.id)
        self.load()

    def _rgb_changed(self, _index: int = 0) -> None:
        spk = self._spk()
        if self._loading or spk is None:
            return
        spk.rgb_device, spk.rgb_zone = tuple(self.rgb_target.currentData())
        spk.rgb_mode = self.rgb_mode.currentData()
        self.state.save_soon()

    def _rgb_role_toggled(self, on: bool) -> None:
        spk = self._spk()
        if self._loading or spk is None:
            return
        spk.rgb_color = "" if on else ROLE_COLORS.get(spk.role, "#ffffff")
        self._paint_pick(spk)
        self.state.save_soon()

    def _pick_colour(self) -> None:
        spk = self._spk()
        if spk is None:
            return
        colour = QColorDialog.getColor(QColor(spk.rgb_color or "#ffffff"), self, "Light colour")
        if colour.isValid():
            spk.rgb_color = colour.name()
            self._paint_pick(spk)
            self.state.save_soon()


# ======================================================================= device

class DevicePanel(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self._loading = False
        self._busy = False
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(10, 10, 10, 10)
        col.setSpacing(6)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrolled(inner))
        self.empty = dim("Click a screen or sound output on the room map to set it up.")
        col.addWidget(self.empty)
        self.body = QWidget()
        col.addWidget(self.body)
        col.addStretch(1)
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)

        box = QGroupBox("Output")
        form = QFormLayout(box)
        self.label = QLineEdit()
        self.label.setPlaceholderText("Your own name for it, for example Left TV")
        self.system = dim("")
        self.enabled = QCheckBox("Use this output")
        form.addRow("Name", self.label)
        form.addRow("Windows name", self.system)
        form.addRow("", self.enabled)
        body.addWidget(box)

        box = QGroupBox("Where the sound comes out")
        v = QVBoxLayout(box)
        self.kind = slim_combo()
        self.kind.addItem("Speakers attached to this screen or unit", "builtin")
        self.kind.addItem("Loose speakers, each on its own spot (aux, headphone or line out)",
                          "external")
        v.addWidget(self.kind)
        self.kind_help = dim("")
        v.addWidget(self.kind_help)
        body.addWidget(box)

        box = QGroupBox("Speaker model")
        v = QVBoxLayout(box)
        self.recognised = QLabel("")
        self.recognised.setWordWrap(True)
        v.addWidget(self.recognised)
        self.model = slim_combo()
        self.model.setMaxVisibleItems(24)
        v.addWidget(self.model)
        self.model_note = dim("")
        v.addWidget(self.model_note)
        body.addWidget(box)

        box = QGroupBox("Position in the room")
        form = QFormLayout(box)
        self.x = self._metres(-50, 50)
        self.y = self._metres(-50, 50)
        self.rot = QDoubleSpinBox()
        self.rot.setRange(-180.0, 180.0)
        self.rot.setSingleStep(5.0)
        self.rot.setDecimals(1)
        self.rot.setSuffix(" °")
        self.rot.setWrapping(True)
        self.width_m = self._metres(0.1, 10)
        self.face = QPushButton("Turn to face me")
        form.addRow("Left / right", self.x)
        form.addRow("Front / back", self.y)
        form.addRow("Turned by", self.rot)
        form.addRow("Speaker spacing", self.width_m)
        self.pos_form = form
        form.addRow("", self.face)
        self.width_m.setToolTip("Distance between the left and right speaker of this unit, "
                                "roughly the width of the screen")
        body.addWidget(box)

        box = QGroupBox("Trim for the whole output")
        form = QFormLayout(box)
        self.gain = NumSlider(-30.0, 12.0, 0.5, " dB")
        self.trim = NumSlider(0.0, 300.0, 1.0, " ms", 0)
        form.addRow("Volume", self.gain)
        form.addRow("Extra delay", self.trim)
        form.addRow(dim("TVs process sound for a moment before playing it, and every model takes a "
                        "different time. If one output is ahead of the others, add delay to it "
                        "here until they line up. Game mode on the TV usually shortens its lag."))
        body.addWidget(box)

        self.remove = QPushButton("Remove from this setup")
        body.addWidget(self.remove)

        self.label.editingFinished.connect(self._label_edited)
        self.enabled.toggled.connect(self._enabled_toggled)
        self.kind.activated.connect(self._kind_changed)
        self.model.activated.connect(self._model_chosen)
        for spin, field in ((self.x, "x"), (self.y, "y"), (self.rot, "rotation"), (self.width_m, "width")):
            spin.valueChanged.connect(lambda v, f=field: self._set_layout(f, v))
        self.face.clicked.connect(self._face)
        self.gain.valueChanged.connect(lambda v: self._set_trim("gain_db", v))
        self.trim.valueChanged.connect(lambda v: self._set_trim("trim_ms", v))
        self.remove.clicked.connect(self._remove)

        state.selectionChanged.connect(self.load)
        state.structureChanged.connect(self._external)
        state.layoutChanged.connect(self._external)
        self.load()

    @staticmethod
    def _metres(low: float, high: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setSingleStep(0.05)
        spin.setDecimals(2)
        spin.setSuffix(" m")
        spin.setKeyboardTracking(False)
        return spin

    def _dev(self):
        return self.state.selected_device()

    def _external(self) -> None:
        if not self._busy:
            self.load()

    def load(self) -> None:
        dev = self._dev()
        self.empty.setVisible(dev is None)
        self.body.setVisible(dev is not None)
        if dev is None:
            return
        self._loading = True
        try:
            if not self.label.hasFocus():
                self.label.setText(dev.label)
            self.system.setText(dev.name)
            self.enabled.setChecked(dev.enabled)
            self.kind.setCurrentIndex(max(0, self.kind.findData(dev.kind)))
            if dev.kind == "builtin" and is_shape(dev):
                self.kind_help.setText("A surround system: its speakers sit in a shape around you "
                                       "and move and turn together. Make them loose to drag each "
                                       "speaker to where it really stands.")
            elif dev.kind == "builtin":
                self.kind_help.setText("The speakers sit in the unit itself, so they move and turn "
                                       "with it on the map.")
            else:
                self.kind_help.setText("Use this for a TV or monitor with no speakers of its own, or "
                                       "whenever you plugged speakers into its audio jack. Each "
                                       "speaker can now be dragged to its own spot on the map. "
                                       "Windows still sends the sound to this screen, the screen "
                                       "passes it out of the jack.")
            self._load_model(dev)
            self.x.setValue(dev.x)
            self.y.setValue(dev.y)
            self.rot.setValue(dev.rotation)
            self.width_m.setValue(dev.width)
            builtin = dev.kind == "builtin"
            self.rot.setEnabled(builtin)
            self.width_m.setEnabled(builtin)
            self.face.setEnabled(builtin and not is_shape(dev))
            spacing = self.pos_form.labelForField(self.width_m)
            if spacing is not None:
                spacing.setText("Size across" if is_shape(dev) else "Speaker spacing")
            self.gain.setValue(dev.gain_db)
            self.trim.setValue(dev.trim_ms)
        finally:
            self._loading = False

    def _load_model(self, dev) -> None:
        combo = self.model
        combo.clear()
        combo.addItem("Not chosen", "")
        heading_font = combo.font()
        heading_font.setBold(True)
        for heading, entries in speaker_library.choices():
            combo.addItem(heading, None)
            item = combo.model().item(combo.count() - 1)
            item.setEnabled(False)
            item.setFont(heading_font)
            for entry in entries:
                combo.addItem("    " + entry.name, entry.key)
        combo.setCurrentIndex(max(0, combo.findData(dev.model or "")))
        found = speaker_library.recognise(dev.name)
        if found is not None and found.category != "interface":
            self.recognised.setText(f"Windows calls this output \u201c{dev.name}\u201d. Recognised as: "
                                    f"<b>{found.name}</b>.")
        else:
            self.recognised.setText(f"Windows calls this output \u201c{dev.name}\u201d. Choose which "
                                    f"speakers are connected to get a matching preset.")
        entry = speaker_library.BY_KEY.get(dev.model)
        self.model_note.setText(entry.note if entry else "")
        self.model_note.setVisible(bool(entry and entry.note))

    def _model_chosen(self, _index: int) -> None:
        dev = self._dev()
        key = self.model.currentData()
        if self._loading or dev is None or key is None:
            return
        if key == "":
            dev.model = ""
            if self.state.project.use_all_channels(dev):
                self.state.touch_streams()      # every channel Windows offers is back
                self.state.touch_layout()
            self.load()
            self.state.save_soon()
            return
        before = [s.id for s in dev.speakers]
        speaker_library.apply_model(dev, speaker_library.BY_KEY[key], self.state.project)
        if [s.id for s in dev.speakers] != before:
            self.state.touch_streams()          # speakers left (a 2.1 system offered as 7.1)
        for spk in dev.speakers:
            self.state.engine.update_speaker(spk.id)
        self.state.touch_layout()
        self.load()
        self.state.notice.emit(f"{dev.title}: settings for {speaker_library.BY_KEY[key].name} applied")

    def _run(self, fn) -> None:
        self._busy = True
        try:
            fn()
        finally:
            self._busy = False

    def _label_edited(self) -> None:
        dev = self._dev()
        if self._loading or dev is None or dev.label == self.label.text().strip():
            return
        dev.label = self.label.text().strip()
        self._run(self.state.touch_routing)

    def _enabled_toggled(self, on: bool) -> None:
        dev = self._dev()
        if self._loading or dev is None:
            return
        dev.enabled = on
        self._run(self.state.touch_streams)

    def _kind_changed(self, _i: int) -> None:
        dev = self._dev()
        if self._loading or dev is None or dev.kind == self.kind.currentData():
            return
        # loose speakers go back to the spot they had the last time they were loose
        set_attached(dev, self.kind.currentData() == "builtin")
        self.state.touch_layout()
        self.state.structureChanged.emit()
        self.load()

    def _set_layout(self, field: str, value: float) -> None:
        dev = self._dev()
        if self._loading or dev is None:
            return
        setattr(dev, field, value)
        self._run(self.state.touch_layout)

    def _face(self) -> None:
        dev = self._dev()
        if dev is not None:
            face_listener(self.state.project, dev)
            self.state.touch_layout()

    def _set_trim(self, field: str, value: float) -> None:
        dev = self._dev()
        if self._loading or dev is None:
            return
        setattr(dev, field, value)
        for spk in dev.speakers:
            self.state.engine.update_speaker(spk.id)
        self.state.save_soon()

    def _remove(self) -> None:
        dev = self._dev()
        if dev is None:
            return
        self.state.project.remove_device(dev.id)
        self.state.select("", "")
        self.state.touch_streams()


# ======================================================================= sound

class SoundPanel(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self._loading = False
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(10, 10, 10, 10)
        col.setSpacing(6)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrolled(inner))

        box = QGroupBox("Incoming sound")
        form = QFormLayout(box)
        self.layout_combo = slim_combo()
        self.layout_combo.addItem("Work it out from the number of channels", "auto")
        for key, text in (("stereo", "Stereo"), ("5.1", "5.1 surround"), ("7.1", "7.1 surround"),
                          ("quad", "Quad"), ("mono", "Mono")):
            self.layout_combo.addItem(text, key)
        self.upmix = QCheckBox("Fill speakers the source has no channel for")
        self.upmix.setToolTip("For example stereo music is also played on the side and rear "
                              "speakers. Off = those speakers stay silent")
        form.addRow("Channel layout", self.layout_combo)
        form.addRow("", self.upmix)
        self.source_now = dim("")
        self.source_now.hide()
        form.addRow(self.source_now)
        body_note = dim("For true surround from games, the device you listen to must be set to "
                        "5.1 or 7.1 in the Windows sound settings.")
        form.addRow(body_note)
        col.addWidget(box)

        box = QGroupBox("Bass")
        form = QFormLayout(box)
        self.redirect = QCheckBox("Send the bass of every channel to the subwoofer as well")
        self.redirect_db = NumSlider(-24.0, 6.0, 0.5, " dB")
        self.lfe_mains = QCheckBox("No subwoofer in this mode: play the bass channel on the fronts")
        self.keep_lows = QCheckBox("No subwoofer playing: every speaker keeps its lows")
        self.keep_lows.setToolTip("A speaker's \"Nothing below\" limit hands its lowest notes to "
                                  "the subwoofer. With no subwoofer playing they would simply be "
                                  "lost and the sound gets thin, so the limit waits until there is "
                                  "one. Off: the limits always apply.")
        form.addRow(self.redirect)
        form.addRow("Amount", self.redirect_db)
        form.addRow(self.lfe_mains)
        form.addRow(self.keep_lows)
        col.addWidget(box)

        box = QGroupBox("Timing")
        form = QFormLayout(box)
        self.buffer = NumSlider(0.0, 300.0, 5.0, " ms", 0)
        form.addRow("Safety buffer", self.buffer)
        form.addRow(dim("0 ms gives the least delay: SpeakerWeave then keeps only the room your "
                        "sound cards need, and adds a little more by itself if one runs dry. "
                        "Raise it if you still hear crackles or dropouts."))
        col.addWidget(box)

        box = QGroupBox("Room")
        form = QFormLayout(box)
        self.room_w = DevicePanel._metres(1.0, 30.0)
        self.room_h = DevicePanel._metres(1.0, 30.0)
        self.auto_face = QCheckBox("Screens turn to face me while I drag them")
        form.addRow("Width", self.room_w)
        form.addRow("Depth", self.room_h)
        form.addRow(self.auto_face)
        col.addWidget(box)

        box = QGroupBox("Keeping the outputs in step")
        v = QVBoxLayout(box)
        v.addWidget(dim("Every sound device runs on its own clock. The app nudges each one by a "
                        "tiny amount so they never drift apart."))
        self.sync = QLabel("Not running")
        self.sync.setTextFormat(Qt.PlainText)
        v.addWidget(self.sync)
        col.addWidget(box)
        col.addStretch(1)

        self.layout_combo.activated.connect(lambda _i: self._set("source_layout", self.layout_combo.currentData(), "routing"))
        self.upmix.toggled.connect(lambda v: self._set("upmix", v, "routing"))
        self.redirect.toggled.connect(lambda v: self._set("bass_redirect", v, "routing"))
        self.redirect_db.valueChanged.connect(lambda v: self._set("bass_redirect_db", v, "routing"))
        self.lfe_mains.toggled.connect(lambda v: self._set("lfe_to_mains", v, "routing"))
        self.keep_lows.toggled.connect(lambda v: self._set("keep_lows", v, "routing"))
        self.buffer.valueChanged.connect(lambda v: self._set("buffer_ms", v, "streams"))
        self.room_w.valueChanged.connect(lambda v: self._set("room_w", v, "layout"))
        self.room_h.valueChanged.connect(lambda v: self._set("room_h", v, "layout"))
        self.auto_face.toggled.connect(lambda v: self._set("auto_face", v, "save"))
        self._quiet = False
        state.structureChanged.connect(self._external)
        self.load()

    def _external(self) -> None:
        if not self._quiet:
            self.load()

    def load(self) -> None:
        p = self.state.project
        self._loading = True
        self.layout_combo.setCurrentIndex(max(0, self.layout_combo.findData(p.source_layout)))
        self.upmix.setChecked(p.upmix)
        self.redirect.setChecked(p.bass_redirect)
        self.redirect_db.setValue(p.bass_redirect_db)
        self.lfe_mains.setChecked(p.lfe_to_mains)
        self.keep_lows.setChecked(p.keep_lows)
        self.buffer.setValue(p.buffer_ms)
        self.room_w.setValue(p.room_w)
        self.room_h.setValue(p.room_h)
        self.auto_face.setChecked(p.auto_face)
        self._loading = False

    def _set(self, field: str, value, effect: str) -> None:
        if self._loading:
            return
        setattr(self.state.project, field, value)
        self._quiet = True
        try:
            if effect == "routing":
                self.state.touch_routing()
            elif effect == "streams":
                self.state.touch_streams()
            elif effect == "layout":
                self.state.touch_layout()
            else:
                self.state.save_soon()
        finally:
            self._quiet = False

    def refresh_status(self) -> None:
        state = self.state
        eng = state.engine
        if not state.runner.running:
            self.sync.setText("Not running")
            self.source_now.hide()
            return
        names = ", ".join(r for r in eng.source_roles if r != OFF)
        self.source_now.show()
        self.source_now.setText(f"Receiving {eng.src_channels} channels at {eng.sr / 1000:g} kHz: {names}")
        lines = []
        for dev_id, (fill, ppm, drops) in state.runner.status().items():
            dev = state.project.find_device(dev_id)
            if dev is None:
                continue
            lines.append(f"{dev.title}\n    buffer {fill:.0f} ms,  clock correction {ppm:+.0f} ppm,  "
                         f"interruptions {drops}")
        self.sync.setText("\n".join(lines) or "No output running")


# ======================================================================= lights

class LightsPanel(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(10, 10, 10, 10)
        col.setSpacing(6)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrolled(inner))

        box = QGroupBox("OpenRGB connection")
        form = QFormLayout(box)
        self.host = QLineEdit(state.project.rgb_host)
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(state.project.rgb_port)
        self.connect_btn = QPushButton("Connect")
        self.status = dim("Not connected")
        form.addRow("Address", self.host)
        form.addRow("Port", self.port)
        form.addRow("", self.connect_btn)
        form.addRow(self.status)
        col.addWidget(box)

        box = QGroupBox("Lights that were found")
        v = QVBoxLayout(box)
        self.found = QLabel("Nothing yet")
        self.found.setTextFormat(Qt.PlainText)
        self.found.setWordWrap(True)
        v.addWidget(self.found)
        col.addWidget(box)

        box = QGroupBox("How it works")
        v = QVBoxLayout(box)
        v.addWidget(dim(
            "The lights are driven through OpenRGB, a free program that knows how to talk to "
            "most RGB hardware (motherboard headers, LED controllers, RGB speakers and so on).\n\n"
            "1. Install and open OpenRGB and check that it can see your lights.\n"
            "2. In OpenRGB open the SDK Server tab and press Start Server.\n"
            "3. Press Connect here.\n"
            "4. Select a speaker, and in its Lights section choose which light belongs to it.\n\n"
            "Each speaker can show its role colour or one you pick, either steady, pulsing with "
            "its own sound, as a level meter along the LEDs, or as a rainbow."))
        col.addWidget(box)
        col.addStretch(1)

        self.connect_btn.clicked.connect(self._toggle)
        state.structureChanged.connect(self._sync_fields)
        self.refresh_status()

    def _sync_fields(self) -> None:
        if not self.host.hasFocus():
            self.host.setText(self.state.project.rgb_host)
        self.port.setValue(self.state.project.rgb_port)

    def _toggle(self) -> None:
        state = self.state
        if state.rgb.connected:
            state.rgb.disconnect()
            state.project.rgb_enabled = False
        else:
            state.project.rgb_host = self.host.text().strip() or "127.0.0.1"
            state.project.rgb_port = self.port.value()
            state.project.rgb_enabled = state.rgb.connect()
        state.save_soon()
        self.refresh_status()
        state.selectionChanged.emit()      # the speaker panel lists the lights

    def refresh_status(self) -> None:
        rgb = self.state.rgb
        self.connect_btn.setText("Disconnect" if rgb.connected else "Connect")
        if rgb.connected:
            targets = rgb.targets()
            self.status.setText("Connected")
            lines = []
            for dev, zone, leds in targets:
                lines.append(f"{dev}  ({leds} LEDs)" if not zone else f"      {zone}  ({leds} LEDs)")
            self.found.setText("\n".join(lines) or "OpenRGB reports no lights")
        else:
            self.status.setText(rgb.error or "Not connected")
            self.found.setText("Nothing yet")
