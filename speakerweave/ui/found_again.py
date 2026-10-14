"""The note that pops up beside the "Hidden by user" folder when a hidden output is
plugged in again, with what to do about it."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from . import theme

ACTIVATE = "activate"
IGNORE = "ignore"
IGNORE_ALWAYS = "ignore always"
WIDTH = 330


class FoundAgainNote(QFrame):
    """A card with a small pointer on its left, sitting over the window."""
    chosen = Signal(str, str)               # output name, ACTIVATE / IGNORE / IGNORE_ALWAYS

    def __init__(self, window, name: str, title: str):
        super().__init__(window)
        self.name = name
        self.setObjectName("foundNote")
        self.setFixedWidth(WIDTH)
        self.setStyleSheet(
            f"QFrame#foundNote {{ background: {theme.PANEL_2}; border: 2px solid {theme.ACCENT}; "
            f"border-radius: 10px; }}")
        col = QVBoxLayout(self)
        col.setContentsMargins(14, 12, 14, 12)
        col.setSpacing(6)
        head = QLabel("This device has been found again")
        head.setStyleSheet("font-weight: 700;")
        col.addWidget(head)
        body = QLabel(f"{title} is connected again. You hid it earlier.")
        body.setWordWrap(True)
        col.addWidget(body)
        self.activate_btn = QPushButton("Activate device")
        self.activate_btn.setObjectName("primary")
        self.activate_btn.setToolTip("Bring it back into the list, ticked, so it plays")
        self.ignore_btn = QPushButton("Ignore")
        self.ignore_btn.setToolTip("Leave it hidden. You are told again the next time it is plugged in")
        self.never_btn = QPushButton("Ignore and don't show again")
        self.never_btn.setToolTip("Leave it hidden and never mention it again")
        row = QHBoxLayout()
        row.addWidget(self.activate_btn)
        row.addWidget(self.ignore_btn)
        col.addLayout(row)
        col.addWidget(self.never_btn)
        self.activate_btn.clicked.connect(lambda: self._choose(ACTIVATE))
        self.ignore_btn.clicked.connect(lambda: self._choose(IGNORE))
        self.never_btn.clicked.connect(lambda: self._choose(IGNORE_ALWAYS))
        self.adjustSize()

    def _choose(self, what: str) -> None:
        self.hide()
        self.chosen.emit(self.name, what)
        self.deleteLater()

    def point_at(self, target: QPoint) -> None:
        """Places the card just right of target (a point in window coordinates),
        always inside the window."""
        parent = self.parentWidget()
        self.adjustSize()
        x = target.x() + 12
        y = target.y() - 24
        if parent is not None:
            x = max(8, min(x, parent.width() - self.width() - 8))
            y = max(8, min(y, parent.height() - self.height() - 8))
        self.move(x, y)
        self.raise_()
        self.show()


class UpdateNote(QFrame):
    """A small note under the Errors button when a newer SpeakerWeave is out."""
    chosen = Signal(str)                    # "install", "details" or "later"

    def __init__(self, window, version: str, can_install: bool):
        super().__init__(window)
        self.version = version
        self.setObjectName("updateNote")
        self.setFixedWidth(WIDTH)
        self.setStyleSheet(
            f"QFrame#updateNote {{ background: {theme.PANEL_2}; border: 2px solid {theme.ACCENT}; "
            f"border-radius: 10px; }}")
        col = QVBoxLayout(self)
        col.setContentsMargins(14, 12, 14, 12)
        col.setSpacing(6)
        head = QLabel(f"SpeakerWeave {version} is available")
        head.setStyleSheet("font-weight: 700;")
        col.addWidget(head)
        body = QLabel("It is listed under Notices on the Errors page, with what's new.")
        body.setWordWrap(True)
        col.addWidget(body)
        self.install_btn = QPushButton("Download and install" if can_install else "Open the download page")
        self.install_btn.setObjectName("primary")
        self.details_btn = QPushButton("Details")
        self.later_btn = QPushButton("Later")
        self.later_btn.setToolTip("Hide this note. The notice stays on the Errors page")
        col.addWidget(self.install_btn)
        row = QHBoxLayout()
        row.addWidget(self.details_btn)
        row.addWidget(self.later_btn)
        col.addLayout(row)
        self.install_btn.clicked.connect(lambda: self._choose("install"))
        self.details_btn.clicked.connect(lambda: self._choose("details"))
        self.later_btn.clicked.connect(lambda: self._choose("later"))
        self.adjustSize()

    def _choose(self, what: str) -> None:
        self.hide()
        self.chosen.emit(what)
        self.deleteLater()

    def place_under(self, button) -> None:
        """Just below button, its right edge in line with the button's."""
        parent = self.parentWidget()
        self.adjustSize()
        corner = button.mapTo(parent, QPoint(button.width(), button.height()))
        x = max(8, min(corner.x() - self.width(), parent.width() - self.width() - 8))
        y = max(8, min(corner.y() + 6, parent.height() - self.height() - 8))
        self.move(x, y)
        self.raise_()
        self.show()
