"""What is playing on the PC: a strip under the map with previous, play or pause and next,
and a small popup in the corner of the screen when a new song or video starts, which
counts down from 5 and closes by itself (or with its X)."""
from __future__ import annotations

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from ..media import MediaWatcher
from . import theme

POPUP_S = 5                     # the popup closes itself after this many seconds
POPUP_WIDTH = 360
ART = 56


def _art(data: bytes, size: int) -> QPixmap:
    """The album art, cropped square with round corners (an empty tile when there is none)."""
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), 6, 6)
    p.setClipPath(path)
    picture = QPixmap()
    if data and picture.loadFromData(data):
        side = min(picture.width(), picture.height())
        crop = picture.copy((picture.width() - side) // 2, (picture.height() - side) // 2, side, side)
        p.drawPixmap(0, 0, crop.scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
    else:
        p.fillPath(path, QColor(theme.PANEL_2))
        p.setPen(QColor(theme.DIM))
        font = p.font()
        font.setPointSizeF(size / 3.2)
        p.setFont(font)
        p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, "♫")
    p.end()
    return out


def icon(kind: str, size: int = 16) -> QIcon:
    """Drawn rather than taken from a font, so they look the same on every PC and theme:
    "previous", "play", "pause", "next", "close", "plus" or "minus"."""
    scale = 3                                   # drawn large, so it stays sharp when scaled
    side = size * scale
    pix = QPixmap(side, side)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    ink = QColor(theme.TEXT)
    p.setPen(Qt.NoPen)
    p.setBrush(ink)
    s = side / 16.0

    def tri(points):
        p.drawPolygon(QPolygonF([QPointF(x * s, y * s) for x, y in points]))
    if kind == "play":
        tri([(4.5, 2.5), (13.5, 8), (4.5, 13.5)])
    elif kind == "pause":
        p.drawRoundedRect(QRectF(3.5 * s, 2.5 * s, 3.2 * s, 11 * s), s, s)
        p.drawRoundedRect(QRectF(9.3 * s, 2.5 * s, 3.2 * s, 11 * s), s, s)
    elif kind == "next":
        tri([(2.5, 3), (9.5, 8), (2.5, 13)])
        p.drawRoundedRect(QRectF(10.5 * s, 3 * s, 2.5 * s, 10 * s), 0.8 * s, 0.8 * s)
    elif kind == "previous":
        tri([(13.5, 3), (6.5, 8), (13.5, 13)])
        p.drawRoundedRect(QRectF(3 * s, 3 * s, 2.5 * s, 10 * s), 0.8 * s, 0.8 * s)
    elif kind in ("plus", "minus"):
        pen = QPen(ink, 1.8 * s)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(3.5 * s, 8 * s), QPointF(12.5 * s, 8 * s))
        if kind == "plus":
            p.drawLine(QPointF(8 * s, 3.5 * s), QPointF(8 * s, 12.5 * s))
    elif kind == "close":
        pen = QPen(ink, 1.8 * s)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(4 * s, 4 * s), QPointF(12 * s, 12 * s))
        p.drawLine(QPointF(12 * s, 4 * s), QPointF(4 * s, 12 * s))
    p.end()
    return QIcon(pix)


def _button(kind: str, tip: str) -> QPushButton:
    button = QPushButton()
    button.setIcon(icon(kind))
    button.setIconSize(QSize(16, 16))
    button.setToolTip(tip)
    button.setFixedSize(38, 30)
    button.setFocusPolicy(Qt.NoFocus)
    return button


class _Controls(QWidget):
    """Previous, play or pause, next."""
    pressed = Signal(str)

    def __init__(self):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.prev = _button("previous", "Previous")
        self.play = _button("play", "Play")
        self.next = _button("next", "Next")
        for b in (self.prev, self.play, self.next):
            row.addWidget(b)
        self.prev.clicked.connect(lambda: self.pressed.emit("previous"))
        self.play.clicked.connect(lambda: self.pressed.emit("toggle"))
        self.next.clicked.connect(lambda: self.pressed.emit("next"))

    def show_state(self, now) -> None:
        playing = now is not None and now.playing
        self.play.setIcon(icon("pause" if playing else "play"))
        self.play.setToolTip("Pause" if playing else "Play")
        can = now.can if now is not None else {}
        self.prev.setEnabled(can.get("previous", True))
        self.next.setEnabled(can.get("next", True))
        self.play.setEnabled(can.get("pause", True) if playing else can.get("play", True))


def _describe(now) -> tuple:
    title = now.title or "Something is playing"
    by = " · ".join(x for x in (now.artist, now.app) if x)
    state = {"paused": "Paused", "stopped": "Stopped"}.get(now.status, "")
    return title, (f"{state} · {by}" if state and by else (state or by))


class NowPlayingBar(QFrame):
    """The strip under the room map. Hidden while nothing is playing."""
    pressed = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("nowBar")
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 10, 6)
        row.setSpacing(10)
        self.art = QLabel()
        self.art.setFixedSize(40, 40)
        row.addWidget(self.art)
        text = QVBoxLayout()
        text.setSpacing(0)
        self.title = QLabel("")
        self.title.setStyleSheet("font-weight: 700;")
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.by = QLabel("")
        self.by.setObjectName("dim")
        self.by.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        text.addWidget(self.title)
        text.addWidget(self.by)
        row.addLayout(text, 1)
        self.controls = _Controls()
        self.controls.pressed.connect(self.pressed)
        row.addWidget(self.controls)
        self.restyle()
        self.hide()

    def restyle(self) -> None:
        self.setStyleSheet(f"QFrame#nowBar {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER}; "
                           f"border-radius: 8px; }}")

    def show_now(self, now, art_changed: bool = True) -> None:
        if now is None:
            self.hide()
            return
        title, by = _describe(now)
        self.title.setText(title)
        self.title.setToolTip(title)
        self.by.setText(by)
        if art_changed:
            self.art.setPixmap(_art(now.art, 40))
        self.controls.show_state(now)
        self.show()


class NowPlayingPopup(QFrame):
    """A card in the corner of the screen, above the taskbar. It never takes the focus
    from a game, counts down from 5, and waits while the mouse is on it."""
    pressed = Signal(str)

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setObjectName("nowPopup")
        self.setFixedWidth(POPUP_WIDTH)
        col = QVBoxLayout(self)
        col.setContentsMargins(12, 10, 10, 10)
        col.setSpacing(8)
        head = QHBoxLayout()
        self.heading = QLabel("Now playing")
        self.heading.setObjectName("dim")
        head.addWidget(self.heading)
        head.addStretch(1)
        self.countdown = QLabel("")
        self.countdown.setObjectName("dim")
        head.addWidget(self.countdown)
        self.close_btn = QPushButton()
        self.close_btn.setIcon(icon("close", 12))
        self.close_btn.setIconSize(QSize(12, 12))
        self.close_btn.setToolTip("Close")
        self.close_btn.setFixedSize(26, 24)
        self.close_btn.setFocusPolicy(Qt.NoFocus)
        head.addWidget(self.close_btn)
        col.addLayout(head)
        body = QHBoxLayout()
        body.setSpacing(12)
        self.art = QLabel()
        self.art.setFixedSize(ART, ART)
        body.addWidget(self.art)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = QLabel("")
        self.title.setStyleSheet("font-weight: 700; font-size: 14px;")
        self.title.setWordWrap(True)
        self.by = QLabel("")
        self.by.setObjectName("dim")
        self.by.setWordWrap(True)
        text.addWidget(self.title)
        text.addWidget(self.by)
        text.addStretch(1)
        body.addLayout(text, 1)
        col.addLayout(body)
        bottom = QHBoxLayout()
        self.bar = QFrame()
        self.bar.setFixedHeight(3)
        bottom.addWidget(self.bar, 1)
        self.controls = _Controls()
        self.controls.pressed.connect(self._pressed)
        bottom.addWidget(self.controls)
        col.addLayout(bottom)
        self.close_btn.clicked.connect(self.dismiss)
        self._left_ms = 0
        self._hovered = False
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._tick)
        self.restyle()

    def restyle(self) -> None:
        self.setStyleSheet(f"QFrame#nowPopup {{ background: {theme.PANEL}; border: 1px solid {theme.ACCENT}; "
                           f"border-radius: 10px; }}")

    def show_now(self, now, restart: bool = True) -> None:
        title, by = _describe(now)
        self.title.setText(title)
        self.by.setText(by)
        self.art.setPixmap(_art(now.art, ART))
        self.controls.show_state(now)
        if restart:
            self._left_ms = POPUP_S * 1000
            self._timer.start()
            self._tick(step=False)
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()

    def _place(self) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        room = screen.availableGeometry()
        self.move(room.right() - self.width() - 16, room.bottom() - self.height() - 16)

    def _pressed(self, what: str) -> None:
        self._left_ms = POPUP_S * 1000          # pressing a button counts as still using it
        self.pressed.emit(what)

    def _tick(self, step: bool = True) -> None:
        if step and not self._hovered:
            self._left_ms -= self._timer.interval()
        if self._left_ms <= 0:
            self.dismiss()
            return
        seconds = (self._left_ms + 999) // 1000
        self.countdown.setText("Paused" if self._hovered else f"Closes in {seconds}")
        share = self._left_ms / (POPUP_S * 1000)
        self.bar.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {theme.ACCENT}, "
            f"stop:{share:.3f} {theme.ACCENT}, stop:{min(1.0, share + 0.001):.3f} {theme.BORDER}, "
            f"stop:1 {theme.BORDER}); border-radius: 1px;")

    def enterEvent(self, ev):
        self._hovered = True
        self._tick(step=False)
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hovered = False
        self._tick(step=False)
        super().leaveEvent(ev)

    def dismiss(self) -> None:
        self._timer.stop()
        self.hide()


class _Relay(QObject):
    changed = Signal(object)


class NowPlaying(QObject):
    """Keeps the strip and the popup up to date with what Windows says is playing."""

    def __init__(self, window, bar: NowPlayingBar, reader=None):
        super().__init__(window)
        self.window = window
        self.state = window.state
        self.bar = bar
        self.popup = NowPlayingPopup()
        self.now = None
        self._first = True
        self._shown_for = None                  # the track the popup last appeared for
        self._relay = _Relay()
        self._relay.changed.connect(self._changed)
        self.watcher = MediaWatcher(self._relay.changed.emit, reader=reader)
        bar.pressed.connect(self.command)
        self.popup.pressed.connect(self.command)

    @property
    def available(self) -> bool:
        return self.watcher.available

    def start(self) -> None:
        self.watcher.start()

    def stop(self) -> None:
        self.watcher.stop()
        self.popup.dismiss()

    def command(self, what: str) -> None:
        self.watcher.command(what)

    def restyle(self) -> None:
        self.bar.restyle()
        self.popup.restyle()

    def _changed(self, now) -> None:
        before, self.now = self.now, now
        first, self._first = self._first, False
        settings = self.state.settings
        new_track = now is not None and (before is None or now.track() != before.track())
        if settings.show_now_playing:
            self.bar.show_now(now, art_changed=new_track or before is None)
        else:
            self.bar.hide()
        if now is None:
            return
        if first:
            self._shown_for = now.track()       # already playing when SpeakerWeave opened
        if self.popup.isVisible():
            # the card on screen follows along: a new track starts its countdown again
            self.popup.show_now(now, restart=new_track)
            if now.playing:
                self._shown_for = now.track()
        elif now.playing and now.track() != self._shown_for and settings.media_popup:
            # once per song or video, when it starts playing (not again after a pause)
            self._shown_for = now.track()
            self.popup.show_now(now)
