"""The level meters along the bottom of the window, with a pin.

Pinned (the default) they stay up. Unpinned, only a thin strip stays: resting the mouse on it
for half a second slides the meters up over the panels, the way Word shows its collapsed
ribbon, and they slide away again once the mouse has left them."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout,
                               QWidget)

from .workspace import pin_icon


class LevelsDrawer(QWidget):
    pinChanged = Signal(bool)

    HOVER_MS = 500          # how long the mouse rests on the strip before the meters come up
    LEAVE_MS = 400          # how long it is away from them before they go down again
    SLIDE_MS = 180
    STRIP_HEIGHT = 22

    def __init__(self, levels, over: QWidget, pinned: bool = True):
        super().__init__()
        self.levels = levels
        self.over = over                    # the widget the meters slide up over
        self.pinned = bool(pinned)
        self._open = False
        self._away = 0                      # milliseconds the mouse has been away while open
        self.col = QVBoxLayout(self)
        self.col.setContentsMargins(0, 0, 0, 0)
        self.col.setSpacing(0)

        # unpinned: the strip that stays
        self.strip = QFrame()
        self.strip.setObjectName("levelsStrip")
        self.strip.setFixedHeight(self.STRIP_HEIGHT)
        row = QHBoxLayout(self.strip)
        row.setContentsMargins(10, 0, 4, 0)
        row.setSpacing(8)
        name = QLabel("Levels")
        name.setObjectName("dim")
        row.addWidget(name)
        hint = QLabel("Rest the mouse here to show the meters")
        hint.setObjectName("dim")
        row.addWidget(hint, 1)
        self.strip_pin = self._pin_button()
        row.addWidget(self.strip_pin)
        self.col.addWidget(self.strip)

        # the meters, with the pin in their top right corner
        self.sheet = QFrame()
        self.sheet.setObjectName("levelsSheet")
        sheet_col = QVBoxLayout(self.sheet)
        sheet_col.setContentsMargins(8, 4, 4, 2)
        sheet_col.setSpacing(0)
        sheet_col.addWidget(levels)
        self.pin = self._pin_button()
        self.pin.setParent(self.sheet)
        self.sheet.installEventFilter(self)

        self.hover_timer = QTimer(self)
        self.hover_timer.setSingleShot(True)
        self.hover_timer.setInterval(self.HOVER_MS)
        self.hover_timer.timeout.connect(self._hovered)
        self.watch = QTimer(self)
        self.watch.setInterval(100)
        self.watch.timeout.connect(self._watch)
        self.anim = QPropertyAnimation(self.sheet, b"geometry", self)
        self.anim.setDuration(self.SLIDE_MS)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.finished.connect(self._slid)
        self.strip.installEventFilter(self)
        self.sheet.installEventFilter(self)
        self._apply()

    def _pin_button(self) -> QToolButton:
        button = QToolButton()
        button.setObjectName("pin")
        button.setCheckable(True)
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.NoFocus)
        button.setIconSize(QSize(16, 16))
        button.clicked.connect(lambda on: self.set_pinned(on))
        return button

    # ---------------------------------------------------------- pinning
    def set_pinned(self, on: bool) -> None:
        on = bool(on)
        changed = on != self.pinned
        self.pinned = on
        self._apply()
        if changed:
            self.pinChanged.emit(on)

    def _apply(self) -> None:
        self.anim.stop()
        self.hover_timer.stop()
        self.watch.stop()
        self._open = False
        for button in (self.pin, self.strip_pin):
            button.blockSignals(True)
            button.setChecked(self.pinned)
            button.blockSignals(False)
            button.setToolTip("Unpin: the meters hide in a strip and slide up when you rest the mouse "
                              "on it" if self.pinned else "Pin the meters so they always show")
        self.restyle()
        if self.pinned:
            self.strip.hide()
            if self.sheet.parent() is not self:
                self.sheet.setParent(self)
            self.col.addWidget(self.sheet)
            self.sheet.show()
        else:
            self.col.removeWidget(self.sheet)
            self.sheet.hide()
            self.sheet.setParent(self.over)
            self.strip.show()

    def restyle(self) -> None:
        for button in (self.pin, self.strip_pin):
            button.setIcon(pin_icon(self.pinned))

    # ---------------------------------------------------------- sliding up and down
    @property
    def is_open(self) -> bool:
        return self._open

    def _rects(self):
        """Where the meters are when up, and the line they slide up from."""
        top_left = self.strip.mapTo(self.over, QPoint(0, 0))
        width = self.strip.width()
        bottom = top_left.y() + self.strip.height()
        height = min(self.sheet.sizeHint().height(), max(60, bottom - 40))
        up = QRect(top_left.x(), bottom - height, width, height)
        down = QRect(top_left.x(), bottom, width, 0)
        return up, down

    def slide_up(self) -> None:
        if self.pinned or self._open:
            return
        self._open = True
        self._away = 0
        up, down = self._rects()
        self.sheet.setGeometry(down)
        self.sheet.show()
        self.sheet.raise_()
        self.anim.stop()
        self.anim.setStartValue(down)
        self.anim.setEndValue(up)
        self.anim.start()
        self.watch.start()

    def slide_down(self) -> None:
        if self.pinned or not self._open:
            return
        self._open = False
        self.watch.stop()
        _up, down = self._rects()
        self.anim.stop()
        self.anim.setStartValue(self.sheet.geometry())
        self.anim.setEndValue(down)
        self.anim.start()

    def _slid(self) -> None:
        if not self._open and not self.pinned:
            self.sheet.hide()

    def _hovered(self) -> None:
        if self._mouse_on(self.strip):
            self.slide_up()

    def _mouse_on(self, widget: QWidget) -> bool:
        if not widget.isVisible():
            return False
        return widget.rect().contains(widget.mapFromGlobal(QCursor.pos()))

    def _watch(self) -> None:
        """While up: down again once the mouse has been away from them a moment."""
        if QApplication.activePopupWidget() is not None or self._mouse_on(self.sheet) \
                or self._mouse_on(self.strip):
            self._away = 0
            return
        self._away += self.watch.interval()
        if self._away >= self.LEAVE_MS:
            self.slide_down()

    def eventFilter(self, obj, event) -> bool:
        kind = event.type()
        if obj is self.sheet and kind == event.Type.Resize:
            self.pin.adjustSize()
            self.pin.move(self.sheet.width() - self.pin.width() - 6, 4)
            self.pin.raise_()
        if obj is self.strip:
            if kind == event.Type.Enter and not self.pinned and not self._open:
                self.hover_timer.start()
            elif kind == event.Type.Leave:
                self.hover_timer.stop()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._open:
            self.anim.stop()
            self.sheet.setGeometry(self._rects()[0])
