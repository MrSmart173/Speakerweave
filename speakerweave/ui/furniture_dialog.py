"""The size and options of a desk or sim rig on the room map."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QLabel, QVBoxLayout)

from .. import furniture


def _cm(value_m: float, low: int, high: int) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(0)
    box.setSingleStep(5)
    box.setSuffix(" cm")
    box.setValue(round(value_m * 100))
    return box


class FurnitureDialog(QDialog):
    def __init__(self, room_map, piece):
        super().__init__(room_map.window())
        self.map = room_map
        self.piece = piece
        self.setWindowTitle(piece.title)
        col = QVBoxLayout(self)
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        self.fields = {}
        if not piece.is_rig:
            self.fields["width"] = _cm(piece.width, 40, 400)
            self.fields["depth"] = _cm(piece.depth, 30, 150)
            form.addRow("Width", self.fields["width"])
            form.addRow("Depth", self.fields["depth"])
            if piece.kind in ("desk_u", "desk_corner"):
                self.fields["wing"] = _cm(piece.wing, 20, 250)
                self.fields["wing_depth"] = _cm(piece.wing_depth, 20, 120)
                form.addRow("Sides come out" if piece.kind == "desk_u" else "Corner comes out",
                            self.fields["wing"])
                form.addRow("Side width", self.fields["wing_depth"])
            if piece.kind == "desk_corner":
                box = QComboBox()
                box.addItem("On the right", "right")
                box.addItem("On the left", "left")
                box.setCurrentIndex(box.findData(piece.corner_side))
                self.fields["corner_side"] = box
                form.addRow("Corner", box)
        elif piece.kind == "racing":
            self.fields["shifter"] = QCheckBox("Shifter")
            self.fields["shifter"].setChecked(piece.shifter)
            self.fields["handbrake"] = QCheckBox("Handbrake")
            self.fields["handbrake"].setChecked(piece.handbrake)
            box = QComboBox()
            box.addItem("On the right", "right")
            box.addItem("On the left", "left")
            box.setCurrentIndex(box.findData(piece.shifter_side))
            self.fields["shifter_side"] = box
            form.addRow("", self.fields["shifter"])
            form.addRow("", self.fields["handbrake"])
            form.addRow("Shifter and handbrake", box)
        else:
            box = QComboBox()
            for key, name in furniture.FLIGHT_CONTROLS.items():
                box.addItem(name, key)
            box.setCurrentIndex(box.findData(piece.controls))
            self.fields["controls"] = box
            form.addRow("Controls", box)
        turn = QDoubleSpinBox()
        turn.setRange(-180, 180)
        turn.setDecimals(0)
        turn.setSingleStep(5)
        turn.setSuffix("°")
        turn.setValue(round(piece.rotation))
        turn.setToolTip("0° faces the front of the room. The mouse wheel over it turns it too.")
        self.fields["rotation"] = turn
        form.addRow("Turned", turn)
        col.addLayout(form)
        if piece.is_rig:
            note = QLabel("Drawn as a typical aluminium profile cockpit. Moving or turning it while "
                          "you sit in it brings you along.")
            note.setObjectName("dim")
            note.setWordWrap(True)
            col.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)

    def values(self) -> dict:
        out = {}
        for key, box in self.fields.items():
            if isinstance(box, QCheckBox):
                out[key] = box.isChecked()
            elif isinstance(box, QComboBox):
                out[key] = box.currentData()
            elif key == "rotation":
                out[key] = float(box.value())
            else:
                out[key] = box.value() / 100.0
        return out

    def _apply(self) -> None:
        values = self.values()
        turn = values.pop("rotation", self.piece.rotation)
        self.map.change_furniture(self.piece, **values)
        if abs(turn - self.piece.rotation) > 0.01:
            self.map.turn_furniture(self.piece, turn - self.piece.rotation)
        self.accept()
