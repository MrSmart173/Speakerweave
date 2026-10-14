"""The Easy sync window: two speakers tick together, the person adds delay to the one
they hear first until the click sounds like one, then the next pair (see easysync.py)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QVBoxLayout)

from ..easysync import EasySync
from ..model import ROLE_NAMES
from . import theme
from .panels import dim

STEPS = ((5.0, "+5 ms"), (1.0, "+1 ms"), (0.2, "+0.2 ms"), (-1.0, "-1 ms"))


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
        self.delay = QLabel("")
        self.delay.setStyleSheet(f"color: {theme.ACCENT}; font-weight: 700;")
        col.addWidget(self.name)
        col.addWidget(self.where)
        col.addWidget(self.delay)
        grid = QGridLayout()
        grid.setSpacing(4)
        self.buttons = []
        for i, (ms, text) in enumerate(STEPS):
            button = QPushButton(text)
            button.setToolTip("Add delay: this speaker plays later" if ms > 0 else
                              "Take delay away: this speaker plays earlier")
            button.clicked.connect(lambda _=False, m=ms: self.dialog.hold_back(self.spk_id, m))
            grid.addWidget(button, i // 2, i % 2)
            self.buttons.append(button)
        col.addLayout(grid)

    def show_speaker(self, sync: EasySync, spk_id: str, matched: bool) -> None:
        self.spk_id = spk_id
        dev, spk = sync.project.find_speaker(spk_id)
        role = ROLE_NAMES.get(spk.role, spk.role)
        self.name.setText(f"{spk.name} of {dev.title}" if dev.channels > 1 else dev.title)
        self.where.setText(role + ("   (already matched)" if matched else ""))
        self.delay.setText(f"Delay {spk.delay_ms:.1f} ms")


class EasySyncDialog(QDialog):
    def __init__(self, window, sync: EasySync):
        super().__init__(window)
        self.window, self.state, self.sync = window, window.state, sync
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
        a, b = self.sync.pair()
        self.left.show_speaker(self.sync, a, matched=self.sync.index > 0)
        self.right.show_speaker(self.sync, b, matched=False)

    def _next(self) -> None:
        if self.sync.next():
            self._show_pair()
            return
        self.done_ok = True
        self.accept()

    def _back(self) -> None:
        if self.sync.back():
            self._show_pair()

    # ------------------------------------------------------------ the end
    def done(self, result: int) -> None:
        state, sync = self.state, self.sync
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
    sync = EasySync(window.state.project)
    if sync.pairs < 1:
        QMessageBox.information(window, "Easy sync",
                                "Easy sync needs at least two speakers that play. Tick your outputs "
                                "and give their speakers a role first.")
        return
    dialog = EasySyncDialog(window, sync)
    dialog.setWindowModality(Qt.WindowModal)
    dialog.exec()
