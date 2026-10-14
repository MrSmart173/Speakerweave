"""Pick any combination of speaker positions: a custom mode."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QSpinBox, QVBoxLayout)

from ..model import (MAIN_POSITIONS, ROLE_COLORS, ROLE_NAMES, SUB_ROLES, is_sub, mode_label,
                     standard_mode_for)
from .panels import dim
from .theme import pad_number_boxes

# where each position sits in the picture: (row, column)
SPOTS = {"FL": (0, 0), "FC": (0, 1), "FR": (0, 2), "SL": (1, 0), "SR": (1, 2),
         "BL": (2, 0), "BC": (2, 1), "BR": (2, 2)}


def _chip(color: str) -> QIcon:
    pix = QPixmap(12, 12)
    pix.fill(QColor(color))
    return QIcon(pix)


class PositionsDialog(QDialog):
    def __init__(self, parent, project):
        super().__init__(parent)
        self.setWindowTitle("Speaker positions")
        current = set(project.mode_roles())
        v = QVBoxLayout(self)
        title = QLabel("Which speaker positions does your room have?")
        title.setObjectName("title")
        v.addWidget(title)
        v.addWidget(dim("Tick any combination. Several speakers can share one position. If your "
                        "choice matches a standard mode, that mode is used, otherwise it becomes Custom."))

        grid = QGridLayout()
        grid.setSpacing(8)
        self.buttons = {}
        for role in MAIN_POSITIONS:
            button = QPushButton(ROLE_NAMES[role])
            button.setCheckable(True)
            button.setChecked(role in current)
            button.setIcon(_chip(ROLE_COLORS[role]))
            button.setMinimumSize(150, 44)
            # a ticked position lights up in its own colour, the same one the room map uses
            button.setStyleSheet(f"QPushButton:checked {{ background: {ROLE_COLORS[role]}; "
                                 f"border-color: {ROLE_COLORS[role]}; color: #0b1220; "
                                 f"font-weight: 600; }}")
            button.toggled.connect(self._update)
            row, col = SPOTS[role]
            grid.addWidget(button, row, col)
            self.buttons[role] = button
        you = QLabel("You")
        you.setAlignment(Qt.AlignCenter)
        you.setObjectName("dim")
        grid.addWidget(you, 1, 1)
        v.addLayout(grid)

        subs = QHBoxLayout()
        subs.addWidget(QLabel("Subwoofers"))
        self.subs = QSpinBox()
        self.subs.setRange(0, len(SUB_ROLES))
        self.subs.setValue(len([r for r in current if is_sub(r)]))
        self.subs.setMinimumWidth(70)
        self.subs.valueChanged.connect(self._update)
        subs.addWidget(self.subs)
        subs.addWidget(dim("Every subwoofer plays the same bass. Give each its own delay and "
                           "equaliser on the Speaker tab."), 1)
        v.addLayout(subs)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        v.addWidget(self.summary)
        self.box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.box.accepted.connect(self.accept)
        self.box.rejected.connect(self.reject)
        v.addWidget(self.box)
        self.setMinimumWidth(560)
        pad_number_boxes(self)
        self._update()

    def roles(self) -> list:
        mains = [r for r, b in self.buttons.items() if b.isChecked()]
        return mains + list(SUB_ROLES[:self.subs.value()])

    def _update(self, *_args) -> None:
        roles = self.roles()
        ok = any(not is_sub(r) for r in roles)
        self.box.button(QDialogButtonBox.Ok).setEnabled(ok)
        if not ok:
            self.summary.setText("Tick at least one position.")
            return
        match = standard_mode_for(roles)
        if match:
            self.summary.setText(f"This is <b>{mode_label(*match)}</b>.")
        else:
            mains = len([r for r in roles if not is_sub(r)])
            subs = self.subs.value()
            text = f"<b>Custom</b>: {mains} position{'s' if mains != 1 else ''}"
            if subs:
                text += f" and {subs} subwoofer{'s' if subs != 1 else ''}"
            self.summary.setText(text + ".")
