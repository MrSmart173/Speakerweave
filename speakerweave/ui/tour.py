"""The first run tour: a spotlight walks over every part of the window with a short
explanation, like the tours of Moza Pit House or Fanatec's app. It can be skipped at
any step and taken again from the Setup menu."""
from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..speaker_library import recognise
from . import theme

CARD_WIDTH = 380
DEFAULT_CABLE = "SpeakerWeave Virtual Speaker output (VB-Audio Virtual Cable)"
GAP = 14                # between the spotlight and the card
PAD = 6                 # around the spotlit part


@dataclass
class Step:
    title: str
    text: str
    target: Optional[Callable] = None        # returns the widget to spotlight, or None
    prepare: Optional[Callable] = None       # shows the page or tab the widget is on
    tip: str = ""                            # shown under the text, after "TIP:"


class Tour(QWidget):
    finished = Signal(bool)                  # True: seen to the end, False: skipped

    def __init__(self, window, steps: list):
        super().__init__(window)
        self.window, self.steps, self.index = window, steps, 0
        self.setObjectName("tour")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_DeleteOnClose)

        self.card = QFrame(self)
        self.card.setObjectName("tourCard")
        self.card.setFixedWidth(CARD_WIDTH)
        self.card.setStyleSheet(
            f"QFrame#tourCard {{ background: {theme.PANEL}; border: 1px solid {theme.ACCENT}; "
            f"border-radius: 10px; }}")
        col = QVBoxLayout(self.card)
        col.setContentsMargins(18, 14, 18, 14)
        col.setSpacing(8)
        self.counter = QLabel("")
        self.counter.setObjectName("dim")
        self.heading = QLabel("")
        self.heading.setStyleSheet("font-size: 16px; font-weight: 700;")
        self.heading.setWordWrap(True)
        self.body = QLabel("")
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.PlainText)
        col.addWidget(self.counter)
        col.addWidget(self.heading)
        col.addWidget(self.body)
        self.tip = QLabel("")
        self.tip.setWordWrap(True)
        self.tip.setTextFormat(Qt.RichText)
        self.tip.setStyleSheet(f"color: {theme.ACCENT};")
        col.addWidget(self.tip)
        row = QHBoxLayout()
        self.skip_btn = QPushButton("Skip tour")
        self.back_btn = QPushButton("Back")
        self.next_btn = QPushButton("Next")
        self.next_btn.setObjectName("primary")
        self.next_btn.setDefault(True)
        row.addWidget(self.skip_btn)
        row.addStretch(1)
        row.addWidget(self.back_btn)
        row.addWidget(self.next_btn)
        col.addLayout(row)
        self.skip_btn.clicked.connect(lambda: self.close_tour(False))
        self.back_btn.clicked.connect(self.back)
        self.next_btn.clicked.connect(self.next)

        self._hole = QRect()
        window.installEventFilter(self)
        self.setGeometry(window.rect())
        self.raise_()
        self.show()
        self.go(0)

    # ------------------------------------------------------------ moving through
    def go(self, index: int) -> None:
        self.index = max(0, min(index, len(self.steps) - 1))
        step = self.steps[self.index]
        if step.prepare is not None:
            try:
                step.prepare()
            except Exception:
                pass
        self.counter.setText(f"Step {self.index + 1} of {len(self.steps)}")
        self.heading.setText(step.title)
        self.body.setText(step.text)
        self.tip.setText(f"<b>TIP:</b> {html.escape(step.tip)}" if step.tip else "")
        self.tip.setVisible(bool(step.tip))
        self.back_btn.setEnabled(self.index > 0)
        last = self.index == len(self.steps) - 1
        self.next_btn.setText("Finish" if last else "Next")
        self.skip_btn.setVisible(not last)
        self.raise_()
        self.setFocus()
        # the page or tab that was just shown needs a moment to lay itself out
        QTimer.singleShot(0, self._place)
        QTimer.singleShot(120, self._place)

    def next(self) -> None:
        if self.index >= len(self.steps) - 1:
            self.close_tour(True)
        else:
            self.go(self.index + 1)

    def back(self) -> None:
        if self.index > 0:
            self.go(self.index - 1)

    def close_tour(self, completed: bool) -> None:
        self.window.removeEventFilter(self)
        self.hide()
        self.finished.emit(completed)
        self.close()

    # ------------------------------------------------------------ placing
    def _target_rect(self) -> QRect:
        step = self.steps[self.index]
        widget = None
        if step.target is not None:
            try:
                widget = step.target()
            except Exception:
                widget = None
        if widget is None or not widget.isVisible():
            return QRect()
        scroller = getattr(self.window, "scroller", None)
        if scroller is not None and scroller.widget() is not None \
                and scroller.widget().isAncestorOf(widget):
            scroller.ensureWidgetVisible(widget, PAD * 2, PAD * 2)   # a small window: scroll to it
        top_left = widget.mapTo(self.window, QPoint(0, 0))
        rect = QRect(top_left, widget.size()).adjusted(-PAD, -PAD, PAD, PAD)
        return rect.intersected(self.rect().adjusted(2, 2, -2, -2))

    def _place(self) -> None:
        if not self.isVisible():
            return
        self.setGeometry(self.window.rect())
        self._hole = self._target_rect()
        layout = self.card.layout()
        layout.activate()
        height = layout.totalHeightForWidth(CARD_WIDTH) if layout.hasHeightForWidth() else -1
        self.card.resize(CARD_WIDTH, max(height, layout.totalSizeHint().height()))
        size = self.card.size()
        area = self.rect().adjusted(12, 12, -12, -12)
        hole = self._hole
        if hole.isNull():
            pos = QPoint(area.center().x() - size.width() // 2, area.center().y() - size.height() // 2)
        else:
            centre_x = hole.center().x() - size.width() // 2
            centre_y = hole.center().y() - size.height() // 2
            options = [
                QPoint(centre_x, hole.bottom() + GAP),                     # below
                QPoint(centre_x, hole.top() - GAP - size.height()),        # above
                QPoint(hole.right() + GAP, centre_y),                      # right
                QPoint(hole.left() - GAP - size.width(), centre_y),        # left
            ]
            pos = None
            for option in options:
                placed = QRect(self._clamp(option, size, area), size)
                if not placed.intersects(hole):
                    pos = placed.topLeft()
                    break
            if pos is None:                     # a very large target: sit inside it, at the bottom
                pos = QPoint(hole.center().x() - size.width() // 2, hole.bottom() - size.height() - GAP)
        self.card.move(self._clamp(pos, size, area))
        self.card.raise_()
        self.update()

    @staticmethod
    def _clamp(pos: QPoint, size, area: QRect) -> QPoint:
        x = max(area.left(), min(pos.x(), area.right() - size.width()))
        y = max(area.top(), min(pos.y(), area.bottom() - size.height()))
        return QPoint(x, y)

    # ------------------------------------------------------------ Qt
    def eventFilter(self, obj, event) -> bool:
        if obj is self.window and event.type() in (QEvent.Resize, QEvent.Show):
            QTimer.singleShot(0, self._place)
        return False

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        shade = QPainterPath()
        shade.addRect(QRectF(self.rect()))
        if not self._hole.isNull():
            hole = QPainterPath()
            hole.addRoundedRect(QRectF(self._hole), 8, 8)
            shade = shade.subtracted(hole)
        painter.fillPath(shade, QColor(0, 0, 0, 165))
        if not self._hole.isNull():
            pen = QPen(QColor(theme.ACCENT), 2)
            painter.setPen(pen)
            painter.drawRoundedRect(QRectF(self._hole), 8, 8)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key_Escape:
            self.close_tour(False)
        elif key in (Qt.Key_Right, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.next()
        elif key == Qt.Key_Left:
            self.back()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        event.accept()                          # the window underneath waits until the tour ends


def window_steps(win) -> list:
    """Every stop of the tour through SpeakerWeave's main window."""
    def room():
        win.show_page(0)

    def tab(widget):
        def show():
            win.show_page(0)
            win.tabs.setCurrentWidget(widget)
        return show

    def page(index):
        return lambda: win.show_page(index)

    # the virtual device's own name, as games list it among their sound outputs
    listened = win.state.project.input_name.replace(" [Loopback]", "")
    entry = recognise(listened) if listened else None
    cable = listened if entry is not None and entry.category == "virtual" else DEFAULT_CABLE

    return [
        Step("Welcome to SpeakerWeave",
             "SpeakerWeave plays everything your PC plays on all your speakers at once, arranged "
             "as a stereo or surround system from 2.0 up to 7.1. This tour shows where everything "
             "is and takes about two minutes. Press Skip tour to leave it. You can take it again "
             "any time from the Setup menu."),
        Step("Your sound outputs",
             "Every sound output currently connected to this PC is listed here. Everything from "
             "headphones, wired & Bluetooth speakers, speakers in your monitors etc.\n\n"
             "Tick each one (the box should fill in with your selected colour) that you would like "
             "to use together. Open an output to see its speakers, and click on a speaker to set "
             "it up.",
             lambda: win.tree, room,
             tip="Right click an output you never use to hide it. It moves to Hidden by user at "
                 "the bottom of the list."),
        Step("What SpeakerWeave listens to",
             "Normally the virtual sound device (VB-CABLE). While SpeakerWeave runs it makes that "
             "device the Windows sound output, so games, music and videos play into it and "
             "SpeakerWeave shares the sound out to your speakers. It is set to 7.1, so games send "
             "real surround.",
             lambda: win.input, room,
             tip=f"If your game or program has the option to choose a specific sound output, "
                 f"change it to \"{cable}\"."),
        Step("Start and stop",
             "The sound starts by itself when SpeakerWeave opens. Stop hands Windows its old sound "
             "output back. Closing the window keeps the sound running in the tray.",
             lambda: win.start_btn, room),
        Step("Speaker mode",
             "Choose 2.0, 2.1, 4.0, 5.1, 7.1 or create a layout of your own with Custom, at the "
             "bottom of this list. Positions shows which role every speaker plays in the mode.",
             lambda: win.mode, room),
        Step("Volume",
             "One volume for everything. Each speaker also has its own level on the Speaker tab.",
             lambda: win.master, room),
        Step("The room map",
             "You sit in the middle. Drag the speakers, or use the side menu for finer "
             "adjustments, to move the speakers to where they physically are from you, and the "
             "sound follows them. A screen or soundbar carries its speakers, and a unit with more than "
             "two channels, such as a Logitech Z906, shows its speakers as a shape with the "
             "subwoofer beside it. Select a unit and press Speakers attached to move its speakers "
             "one by one. Right click anything for more.",
             lambda: win.map, room),
        Step("Test and tune",
             "Test sound plays on the selected speaker only. Set roles gives every speaker the role "
             "of the place it sits in. Easy sync lines up the timing of your speakers by ear, two "
             "at a time, and Line up delays does it from the distances on the map. Mirror moves "
             "pairs of speakers together, and Metronome ticks on your speakers so you can hear "
             "whether they play in time.",
             lambda: win.sync_btn, room),
        Step("Level meters",
             "At the bottom of your screen are sound bars to help visualize the sound that is "
             "being played. The first block is the sound of the PC, and every output has its own "
             "block with a bar for each channel. The Levels button shows or hides them.",
             lambda: win.levels if win.levels.isVisible() else win.levels_btn, room),
        Step("Speaker tab",
             "Everything about the selected speaker: its role, volume and delay, its own "
             "equaliser, the lowest and highest sounds it plays, and its light.",
             lambda: win.tabs, tab(win.speaker_panel)),
        Step("Output tab",
             "The selected output as a whole: its name, what kind of unit it is, its speaker "
             "model, its place in the room and a trim for all its speakers.",
             lambda: win.tabs, tab(win.device_panel)),
        Step("Sound tab",
             "How the sound is shared out: the incoming channel layout, filling speakers the "
             "source has no channel for, bass to the subwoofer, the safety buffer and the size "
             "of the room.",
             lambda: win.tabs, tab(win.sound_panel)),
        Step("Lights tab",
             "Make RGB lights move with the sound through OpenRGB, with a colour for every "
             "speaker role.",
             lambda: win.tabs, tab(win.lights_panel)),
        Step("Effects tab",
             "Link SimHub so every game loads its own speaker setup, set up a ButtKicker or other "
             "bass shaker, and send SimHub effects such as tyres and impacts, or a spotter app, to "
             "the speakers you pick.",
             lambda: win.tabs, tab(win.extras_panel)),
        Step("Errors",
             "If something keeps the sound from your speakers, or the surround is not right, it "
             "is listed on this page with a button that fixes it. The number on the button shows "
             "how many problems there are.",
             lambda: win.errors_btn, page(3)),
        Step("Controls",
             "Put SpeakerWeave's actions on keys, wheel and button box buttons, a Stream Deck or "
             "SimHub: volume, mute, speaker modes and saved setups.",
             lambda: win.nav.button(1), page(1)),
        Step("Settings",
             "Colours, your own test sounds, the Windows sound output, starting with Windows, "
             "updates, and Uninstall at the bottom.",
             lambda: win.nav.button(2), page(2)),
        Step("Fun",
             "Sound effects for everything the PC plays: bass boost, chipmunk or deep voice, robot, "
             "echo, the whole sound spinning round the room and more. Switch one on, or play it "
             "for a few seconds from a key.",
             lambda: win.fun_btn, page(5)),
        Step("Performance",
             "How much of the processor and memory SpeakerWeave uses, and how well the sound keeps "
             "up on every output.",
             lambda: win.nav.button(4), page(4)),
        Step("The Setup menu",
             "Save a setup and open it again, open the full guide, and take this tour again.",
             lambda: win.setup_btn, room),
        Step("You are ready",
             "Tick your outputs, place your speakers on the map and play something. If anything "
             "sounds wrong, the Errors page tells you why.",
             None, room),
    ]
