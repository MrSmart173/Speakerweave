"""The Fun page: sound effects for the PC sound. Each one can be switched on or off, or
played for a set time, from its card, a key, a controller button or a Stream Deck link."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider,
                               QSpinBox, QVBoxLayout, QWidget)

from .. import fun
from ..controls import Action, binding_for
from . import theme
from .panels import dim, scrolled

CARD_WIDTH = 350          # cards per row: as many of this width as fit


class EffectCard(QFrame):
    def __init__(self, page, effect: fun.Effect):
        super().__init__()
        self.page = page
        self.state = page.state
        self.effect = effect
        self.setObjectName("funcard")
        self.setMinimumWidth(300)
        col = QVBoxLayout(self)
        col.setContentsMargins(14, 10, 14, 12)
        col.setSpacing(6)

        head = QHBoxLayout()
        name = QLabel(effect.name)
        name.setObjectName("subtitle")
        head.addWidget(name, 1)
        self.switch = QPushButton("Off")
        self.switch.setCheckable(True)
        self.switch.setFixedWidth(64)
        self.switch.setToolTip(f"Switch {effect.name} on until you switch it off")
        self.switch.clicked.connect(lambda on: self.state.set_fun(effect.key, on))
        head.addWidget(self.switch)
        col.addLayout(head)
        col.addWidget(dim(effect.blurb))

        row = QHBoxLayout()
        row.addWidget(QLabel(effect.amount_name))
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, int(round((effect.hi - effect.lo) / effect.step)))
        self.slider.valueChanged.connect(self._slid)
        row.addWidget(self.slider, 1)
        self.value = QLabel("")
        self.value.setMinimumWidth(92)
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.value)
        col.addLayout(row)

        row = QHBoxLayout()
        self.play = QPushButton("Play for")
        self.play.setToolTip("Switches it on now and off again by itself after this long")
        self.play.clicked.connect(lambda: self.state.fun_for(effect.key, self.seconds.value()))
        row.addWidget(self.play)
        self.seconds = QSpinBox()
        self.seconds.setRange(fun.SECONDS_MIN, fun.SECONDS_MAX)
        self.seconds.setSuffix(" s")
        self.seconds.setKeyboardTracking(False)
        self.seconds.valueChanged.connect(lambda v: self.state.set_fun_seconds(effect.key, v))
        row.addWidget(self.seconds)
        self.left = dim("")
        row.addWidget(self.left, 1)
        col.addLayout(row)

        keys = QGridLayout()
        keys.setHorizontalSpacing(6)
        keys.setVerticalSpacing(4)
        self.key_buttons = {}
        for r, (prefix, text) in enumerate((("fun", "On or off"), ("fun_for", "Play for"))):
            action = Action(f"{prefix}:{effect.key}",
                            f"{effect.name} " + ("on or off" if prefix == "fun" else "for its set time"),
                            "Fun")
            keys.addWidget(dim(f"{text} key"), r, 0)
            button = QPushButton("Set key")
            button.clicked.connect(lambda _c=False, a=action: self.page.capture(a))
            clear = QPushButton("×")
            clear.setFixedWidth(30)
            clear.setToolTip("Take the key away")
            clear.clicked.connect(lambda _c=False, a=action: self.page.clear_key(a))
            keys.addWidget(button, r, 1)
            keys.addWidget(clear, r, 2)
            self.key_buttons[action.key] = (button, clear)
        keys.setColumnStretch(1, 1)
        col.addLayout(keys)
        self.restyle()
        self.load()

    def _slid(self, position: int) -> None:
        e = self.effect
        amount = e.lo + position * e.step
        self.value.setText(e.text(amount))
        if abs(amount - self.state.fun_amount(e.key)) > 1e-9:
            self.state.set_fun_amount(e.key, amount)

    def load(self) -> None:
        e, state = self.effect, self.state
        for w in (self.slider, self.seconds):
            w.blockSignals(True)
        self.slider.setValue(int(round((state.fun_amount(e.key) - e.lo) / e.step)))
        self.seconds.setValue(int(state.fun_seconds(e.key)))
        for w in (self.slider, self.seconds):
            w.blockSignals(False)
        self.value.setText(e.text(state.fun_amount(e.key)))
        self.show_state()
        self.show_keys()

    def show_state(self) -> None:
        on = self.effect.key in self.state.fun_on
        self.switch.blockSignals(True)
        self.switch.setChecked(on)
        self.switch.blockSignals(False)
        self.switch.setText("On" if on else "Off")
        left = self.state.fun_left(self.effect.key)
        self.left.setText(f"{left:.0f} s left" if left > 0 else "")
        if on != self.property("lit"):
            self.setProperty("lit", on)
            self.restyle()

    def show_keys(self) -> None:
        bindings = self.state.settings.bindings
        for action_key, (button, clear) in self.key_buttons.items():
            binding = binding_for(bindings, action_key, "key")
            text = binding["text"] if binding else "Set key"
            button.setText(text if len(text) <= 24 else text[:22] + "...")
            button.setStyleSheet("font-weight: 600;" if binding else "")
            button.setToolTip(f"{binding['text']}. Click to choose another." if binding else
                              "Choose a key. It works everywhere, also while a game is in front.")
            clear.setVisible(binding is not None)

    def restyle(self) -> None:
        edge = theme.ACCENT if self.property("lit") else theme.BORDER
        width = 2 if self.property("lit") else 1
        self.setStyleSheet(f"QFrame#funcard {{ background: {theme.PANEL}; border: {width}px solid {edge}; "
                           f"border-radius: 8px; }}")


class FunPage(QWidget):
    def __init__(self, state, window):
        super().__init__()
        self.state = state
        self.window = window
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(16, 16, 16, 16)
        col.setSpacing(10)
        page = QVBoxLayout(self)
        page.setContentsMargins(0, 0, 0, 0)
        page.addWidget(scrolled(inner))

        title = QLabel("Fun")
        title.setObjectName("title")
        col.addWidget(title)
        col.addWidget(dim("Sound effects for everything the PC plays. Switch one on, or play it for a "
                          "set time. Give any of them a key (it works while a game is in front), or a "
                          "controller button or Stream Deck link on the Controls page. Several can play "
                          "at once."))
        row = QHBoxLayout()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        row.addWidget(self.status, 1)
        self.stop_btn = QPushButton("Stop every effect")
        self.stop_btn.clicked.connect(state.stop_fun)
        row.addWidget(self.stop_btn)
        col.addLayout(row)

        self.grid = QGridLayout()
        self.grid.setSpacing(10)
        col.addLayout(self.grid)
        col.addStretch(1)
        self.cards = [EffectCard(self, effect) for effect in fun.EFFECTS]
        self._columns = 0
        self._lay_out(3)

        self._tick = QTimer(self)                  # the countdowns of timed effects
        self._tick.setInterval(250)
        self._tick.timeout.connect(self._show_state)
        state.funChanged.connect(self._show_state)
        state.runningChanged.connect(self._show_state)
        state.settingsChanged.connect(self._show_keys)
        window.controls_page.bindingsChanged.connect(self._show_keys)
        self._show_state()

    def _lay_out(self, columns: int) -> None:
        columns = max(1, columns)
        if columns == self._columns:
            return
        self._columns = columns
        for card in self.cards:
            self.grid.removeWidget(card)
        for i, card in enumerate(self.cards):
            self.grid.addWidget(card, i // columns, i % columns)
        for c in range(4):
            self.grid.setColumnStretch(c, 1 if c < columns else 0)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._lay_out((self.width() - 40) // CARD_WIDTH)

    def _show_state(self) -> None:
        for card in self.cards:
            card.show_state()
        on = [fun.BY_KEY[k].name for k in fun.ORDER + ("spin",) if k in self.state.fun_on]
        if not self.state.runner.running and on:
            text = "The sound is stopped, so nothing is heard. Press Start to hear the effects."
            self.status.setStyleSheet(f"color: {theme.WARN};")
        else:
            text = ("Playing: " + ", ".join(on)) if on else "No effect is on."
            self.status.setStyleSheet("")
        self.status.setText(text)
        self.stop_btn.setEnabled(bool(on))
        timed = any(self.state.fun_left(k) > 0 for k in self.state.fun_on)
        if timed and not self._tick.isActive():
            self._tick.start()
        elif not timed:
            self._tick.stop()

    def _show_keys(self) -> None:
        for card in self.cards:
            card.show_keys()

    def capture(self, action: Action) -> None:
        self.window.controls_page.capture(action, "key")

    def clear_key(self, action: Action) -> None:
        self.window.controls_page._clear(action.key, "key")

    def load(self) -> None:
        for card in self.cards:
            card.load()

    def restyle(self) -> None:
        for card in self.cards:
            card.restyle()
        self._show_state()
