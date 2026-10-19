"""The Easy sync window: two speakers tick together, the person adds delay to the one
they hear first until the click sounds like one, then the next pair (see easysync.py)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QDialog, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QMessageBox, QPushButton, QSlider, QVBoxLayout)

from ..dsp import MAX_DELAY_MS
from ..easysync import EasySync
from ..model import ROLE_NAMES
from . import theme
from .panels import dim

# first row: more delay (plays later), second row: less delay (plays earlier)
STEPS = ((5.0, "+5 ms"), (1.0, "+1 ms"), (0.1, "+0.1 ms"),
         (-5.0, "\u22125 ms"), (-1.0, "\u22121 ms"), (-0.1, "\u22120.1 ms"))
SWEEP_SPEEDS = ((0.5, "0.5 ms a second"), (1.0, "1 ms a second"), (2.0, "2 ms a second"),
                (5.0, "5 ms a second"))
SWEEP_TICK_MS = 100
# holding a step button down: after this long it repeats, faster the longer it is held
# (held for at least, seconds between repeats)
HOLD_STAGES = ((5.0, 0.04), (3.0, 0.12), (1.8, 0.3))
HOLD_POLL_MS = 20


class HoldRepeat:
    """Makes a button do its job once when pressed, and again and again while it is held:
    slowly after 1.8 seconds, faster after 3 and faster still after 5."""

    def __init__(self, button, action, clock=None):
        import time
        self.button, self.action = button, action
        self.clock = clock or time.monotonic
        self.since = None
        self.last = 0.0
        self.timer = QTimer(button)
        self.timer.setInterval(HOLD_POLL_MS)
        self.timer.timeout.connect(self.poll)
        button.pressed.connect(self.press)
        button.released.connect(self.release)

    def press(self) -> None:
        self.action()
        self.since = self.last = self.clock()
        self.timer.start()

    def release(self) -> None:
        self.timer.stop()
        self.since = None

    def poll(self) -> None:
        if self.since is None or not self.button.isDown():
            self.release()
            return
        now = self.clock()
        held = now - self.since
        gap = next((g for after, g in HOLD_STAGES if held >= after), None)
        if gap is not None and now - self.last >= gap:
            self.last = now
            self.action()


class _SpeakerCard(QFrame):
    """One speaker of the pair: its name, its delay and the buttons that change it."""

    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        self.spk_id = ""
        self.setObjectName("syncCard")
        self.setStyleSheet(f"QFrame#syncCard {{ background: {theme.PANEL}; border: 1px solid "
                           f"{theme.BORDER}; border-radius: 8px; }}")
        col = QVBoxLayout(self)
        col.setContentsMargins(14, 12, 14, 12)
        col.setSpacing(4)
        self.name = QLabel("")
        self.name.setStyleSheet("font-size: 15px; font-weight: 700;")
        self.name.setWordWrap(True)
        self.where = dim("")
        self.delay = QDoubleSpinBox()
        self.delay.setRange(0.0, MAX_DELAY_MS)
        self.delay.setDecimals(1)
        self.delay.setSingleStep(0.1)
        self.delay.setSuffix(" ms")
        self.delay.setKeyboardTracking(False)        # the new value counts once typed in
        self.delay.setStyleSheet(f"color: {theme.ACCENT}; font-weight: 700;")
        self.delay.setToolTip("Type a delay for this speaker, then press Enter")
        self.delay.valueChanged.connect(lambda ms: self.dialog.type_delay(self.spk_id, ms))
        col.addWidget(self.name)
        col.addWidget(self.where)
        row = QHBoxLayout()
        row.addWidget(QLabel("Delay"))
        row.addWidget(self.delay, 1)
        col.addLayout(row)
        grid = QGridLayout()
        grid.setSpacing(4)
        self.buttons = []
        self.holders = []
        for i, (ms, text) in enumerate(STEPS):
            button = QPushButton(text)
            button.setToolTip(("Add delay: this speaker plays later" if ms > 0 else
                               "Take delay away: this speaker plays earlier")
                              + ". Hold it down to keep going, faster the longer you hold")
            self.holders.append(HoldRepeat(button, lambda m=ms: self.dialog.hold_back(self.spk_id, m)))
            grid.addWidget(button, i // 3, i % 3)
            self.buttons.append(button)
        col.addLayout(grid)
        # a sweep: the delay creeps up (or down) until Stop is pressed where it sounds right
        sweep = QHBoxLayout()
        self.sweep_up = QPushButton("Sweep later")
        self.sweep_down = QPushButton("Sweep earlier")
        self.sweep_up.setToolTip("Slowly adds delay. Press Stop the moment the clicks sound like one")
        self.sweep_down.setToolTip("Slowly takes delay away. Press Stop the moment the clicks sound "
                                   "like one")
        self.sweep_up.clicked.connect(lambda: self.dialog.toggle_sweep(self, 1))
        self.sweep_down.clicked.connect(lambda: self.dialog.toggle_sweep(self, -1))
        sweep.addWidget(self.sweep_up)
        sweep.addWidget(self.sweep_down)
        col.addLayout(sweep)

    def show_speaker(self, sync: EasySync, spk_id: str, matched: bool) -> None:
        self.spk_id = spk_id
        dev, spk = sync.project.find_speaker(spk_id)
        role = ROLE_NAMES.get(spk.role, spk.role)
        self.name.setText(f"{spk.name} of {dev.title}" if dev.channels > 1 else dev.title)
        self.where.setText(role + ("   (already matched)" if matched else ""))
        self.delay.blockSignals(True)
        self.delay.setValue(spk.delay_ms)
        self.delay.blockSignals(False)

    def show_sweep(self, direction: int) -> None:
        """direction: 1 sweeping later, -1 earlier, 0 not sweeping."""
        self.sweep_up.setText("Stop" if direction == 1 else "Sweep later")
        self.sweep_down.setText("Stop" if direction == -1 else "Sweep earlier")
        self.sweep_up.setObjectName("primary" if direction == 1 else "")
        self.sweep_down.setObjectName("primary" if direction == -1 else "")
        for button in (self.sweep_up, self.sweep_down):
            button.style().unpolish(button)
            button.style().polish(button)
        for button in self.buttons:
            button.setEnabled(direction == 0)
        self.sweep_up.setEnabled(direction in (0, 1))
        self.sweep_down.setEnabled(direction in (0, -1))
        self.delay.setReadOnly(direction != 0)


class EasySyncDialog(QDialog):
    def __init__(self, window, sync: EasySync):
        super().__init__(window)
        self.window, self.state, self.sync = window, window.state, sync
        for spk_id in sync.order:                   # its starting delays reach the speakers
            self.state.touch_speaker(spk_id)
        self.done_ok = False
        self.setWindowTitle("Easy sync")
        self.setMinimumWidth(560)
        col = QVBoxLayout(self)
        col.setContentsMargins(20, 18, 20, 16)
        col.setSpacing(10)
        self.progress = dim("")
        title = QLabel("Line up your speakers by ear")
        title.setStyleSheet("font-size: 17px; font-weight: 700;")
        col.addWidget(self.progress)
        col.addWidget(title)
        self.help = QLabel("")
        self.help.setWordWrap(True)
        col.addWidget(self.help)
        row = QHBoxLayout()
        self.left, self.right = _SpeakerCard(self), _SpeakerCard(self)
        row.addWidget(self.left, 1)
        row.addWidget(self.right, 1)
        col.addLayout(row)
        col.addWidget(dim("Sit where you normally listen. Small steps near the end: around 1 ms "
                          "the click moves between the speakers, above about 30 ms it turns into "
                          "two clicks."))
        loud = QHBoxLayout()
        loud.addWidget(QLabel("Clicks louder by"))
        self.boost = QSlider(Qt.Horizontal)
        lo, hi = self.state.TEST_BOOST_RANGE
        self.boost.setRange(int(lo), int(hi))
        self.boost.setToolTip("How much louder the clicks play while this window is open. The "
                              "volume goes back to normal when it closes.")
        self.boost_text = QLabel("")
        self.boost_text.setMinimumWidth(52)
        loud.addWidget(self.boost, 1)
        loud.addWidget(self.boost_text)
        loud.addSpacing(16)
        loud.addWidget(QLabel("Sweep speed"))
        self.speed = QComboBox()
        for rate, text in SWEEP_SPEEDS:
            self.speed.addItem(text, rate)
        self.speed.setCurrentIndex(1)
        self.speed.setToolTip("How fast a sweep changes the delay. Slower is easier to stop at "
                              "the right moment")
        loud.addWidget(self.speed)
        col.addLayout(loud)
        self._sweep = None                       # (card, direction) while a sweep runs
        self._sweep_timer = QTimer(self)
        self._sweep_timer.setInterval(SWEEP_TICK_MS)
        self._sweep_timer.timeout.connect(self._sweep_tick)
        self.boost.valueChanged.connect(self._boost_changed)
        self.boost.setValue(int(round(self.state.settings.test_boost_db)))
        self._boost_changed(self.boost.value())
        buttons = QHBoxLayout()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setToolTip("Stop and put every delay back as it was")
        self.back_btn = QPushButton("Back")
        self.next_btn = QPushButton("")
        self.next_btn.setObjectName("primary")
        buttons.addWidget(self.cancel_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.back_btn)
        buttons.addWidget(self.next_btn)
        col.addLayout(buttons)
        self.cancel_btn.clicked.connect(self.reject)
        self.back_btn.clicked.connect(self._back)
        self.next_btn.clicked.connect(self._next)
        self._show_pair()

    # ------------------------------------------------------------ pairs
    def _show_pair(self) -> None:
        sync = self.sync
        a, b = sync.pair()
        self.progress.setText(f"Pair {sync.index + 1} of {sync.pairs}")
        sound = "thump" if sync.low_pair() else "click"
        self.help.setText(
            f"Both speakers {sound} together. The {sound} seems to come from the one that plays "
            f"first: add delay to that one, a little at a time, until you hear a single {sound} "
            f"coming from between the two. Gone too far? Take some off again, or add to the other "
            f"one.")
        self.left.show_speaker(sync, a, matched=sync.index > 0)
        self.right.show_speaker(sync, b, matched=False)
        self.back_btn.setEnabled(sync.index > 0)
        last = sync.index + 1 >= sync.pairs
        self.next_btn.setText("They sound the same: finish" if last else "They sound the same: next pair")
        self.state.play_clicks([(a, sync.low_pair()), (b, sync.low_pair())])

    def hold_back(self, spk_id: str, ms: float) -> None:
        for changed in self.sync.hold_back(spk_id, ms):
            self.state.touch_speaker(changed)
        self._show_delays()

    def type_delay(self, spk_id: str, ms: float) -> None:
        if not spk_id or self._sweep is not None:
            return
        for changed in self.sync.set_delay(spk_id, ms):
            self.state.touch_speaker(changed)
        self._show_delays()

    def _show_delays(self) -> None:
        a, b = self.sync.pair()
        self.left.show_speaker(self.sync, a, matched=self.sync.index > 0)
        self.right.show_speaker(self.sync, b, matched=False)

    # ------------------------------------------------------------ sweeping
    def toggle_sweep(self, card, direction: int) -> None:
        """Starts a sweep on this speaker, or stops the one running (any Stop button)."""
        if self._sweep is not None:
            self.stop_sweep()
            return
        self._sweep = (card, direction)
        card.show_sweep(direction)
        other = self.right if card is self.left else self.left
        other.sweep_up.setEnabled(False)
        other.sweep_down.setEnabled(False)
        self._sweep_timer.start()

    def stop_sweep(self) -> None:
        self._sweep_timer.stop()
        if self._sweep is None:
            return
        self._sweep = None
        for card in (self.left, self.right):
            card.show_sweep(0)
            card.sweep_up.setEnabled(True)
            card.sweep_down.setEnabled(True)

    def _sweep_tick(self) -> None:
        if self._sweep is None:
            return
        card, direction = self._sweep
        step = float(self.speed.currentData()) * SWEEP_TICK_MS / 1000.0 * direction
        before = {i: self.sync.delay(i) for i in self.sync.order}
        self.hold_back(card.spk_id, step)
        if all(abs(self.sync.delay(i) - before[i]) < 1e-9 for i in before):
            self.stop_sweep()                    # at the end of the range: nothing moves

    def _next(self) -> None:
        self.stop_sweep()
        if self.sync.next():
            self._show_pair()
            return
        self.done_ok = True
        self.accept()

    def _back(self) -> None:
        self.stop_sweep()
        if self.sync.back():
            self._show_pair()

    # ------------------------------------------------------------ the end
    def _boost_changed(self, db: int) -> None:
        self.state.boost_tests(db)
        self.boost_text.setText(f"{db:+d} dB" if db else "0 dB")

    def done(self, result: int) -> None:
        state, sync = self.state, self.sync
        self.stop_sweep()
        state.boost_tests(None)                     # the normal volume again
        state.stop_metronome()
        if self.done_ok:
            delays = sync.finish()
        else:
            delays = {}
            sync.cancel()
        for spk_id in sync.order:
            state.touch_speaker(spk_id)
        state.save_soon()
        super().done(result)
        if self.done_ok:
            lines = []
            for spk_id, ms in delays.items():
                dev, spk = sync.project.find_speaker(spk_id)
                lines.append(f"{spk.name} of {dev.title}: {ms:.1f} ms")
            QMessageBox.information(self.window, "Easy sync",
                                    "Your speakers are lined up. The one that needed the least delay "
                                    "now plays at 0 ms, the rest as early as they can:\n\n"
                                    + "\n".join(lines))
            state.notice.emit("Easy sync finished: every speaker is lined up.")
        else:
            state.notice.emit("Easy sync cancelled: every delay is back as it was.")


def start_easy_sync(window) -> None:
    sync = EasySync(window.state.project, from_zero=True)
    if sync.pairs < 1:
        QMessageBox.information(window, "Easy sync",
                                "Easy sync needs at least two speakers that play. Tick your outputs "
                                "and give their speakers a role first.")
        return
    dialog = EasySyncDialog(window, sync)
    dialog.setWindowModality(Qt.WindowModal)
    dialog.exec()
