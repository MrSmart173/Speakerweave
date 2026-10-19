"""The Controls page: keys, controller, wheel and button box buttons, and
Stream Deck links for the things you do most."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QGridLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton,
                               QSpinBox, QTableWidget, QVBoxLayout, QWidget)

from ..controls import (MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, all_actions, binding_for,
                        clear_binding, set_binding)
from .panels import dim, scrolled
from .state import remember_setup_folder, setups_dir

MODIFIER_KEYS = {Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr,
                 Qt.Key_Super_L, Qt.Key_Super_R}


# ======================================================================= capture dialogs

class KeyCaptureDialog(QDialog):
    """Waits for one key combination."""

    def __init__(self, parent, action_label: str):
        super().__init__(parent)
        self.setWindowTitle("Choose a key")
        self.binding = None
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"<b>{action_label}</b>"))
        v.addWidget(QLabel("Press the key or key combination to use, for example Ctrl+Alt+M or F9."))
        v.addWidget(dim("It will work everywhere, also while a game is in front. "
                        "Press Escape to cancel."))
        self.setMinimumWidth(420)

    def keyPressEvent(self, ev):
        key = ev.key()
        if key in MODIFIER_KEYS or key == 0:
            return
        if key == Qt.Key_Escape and not ev.modifiers():
            self.reject()
            return
        mods = 0
        m = ev.modifiers()
        if m & Qt.ControlModifier:
            mods |= MOD_CONTROL
        if m & Qt.AltModifier:
            mods |= MOD_ALT
        if m & Qt.ShiftModifier:
            mods |= MOD_SHIFT
        if m & Qt.MetaModifier:
            mods |= MOD_WIN
        combo = QKeySequence(ev.keyCombination())
        self.binding = {
            "kind": "key",
            "vk": int(ev.nativeVirtualKey()) if sys.platform.startswith("win") else 0,
            "mods": mods,
            "qt": combo.toString(QKeySequence.PortableText),
            "text": combo.toString(QKeySequence.NativeText),
        }
        self.accept()


class PadCaptureDialog(QDialog):
    """Waits for one button press on any controller, wheel or button box."""

    def __init__(self, parent, action_label: str, pads):
        super().__init__(parent)
        self.setWindowTitle("Choose a button")
        self.pads = pads
        self.binding = None
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"<b>{action_label}</b>"))
        v.addWidget(QLabel("Press the button to use on your controller, wheel, button box or pedals."))
        self.status = dim("")
        v.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)
        self.setMinimumWidth(460)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(20)
        self._describe()

    def _describe(self) -> None:
        if not self.pads.available:
            self.status.setText(self.pads.error or "Controller support could not be started.")
            return
        names = [d.name for d in self.pads.devices()]
        self.status.setText("Found: " + ", ".join(names) if names else
                            "No controllers found yet. Plug one in, it will be noticed.")

    def _poll(self) -> None:
        for event in self.pads.poll():
            self.binding = {"kind": "pad", "guid": event.guid, "device": event.device,
                            "input": event.input, "text": event.text}
            self.timer.stop()
            self.accept()
            return

    def done(self, result):
        self.timer.stop()
        super().done(result)


# ======================================================================= the page

class ControlsPage(QWidget):
    bindingsChanged = Signal()          # a key or button was given to an action, or taken away

    def __init__(self, state, window):
        super().__init__()
        self.state = state
        self.window = window
        self.capturing = False

        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(16, 16, 16, 16)
        col.setSpacing(8)
        page = QVBoxLayout(self)
        page.setContentsMargins(0, 0, 0, 0)
        page.addWidget(scrolled(inner))

        title = QLabel("Controls")
        title.setObjectName("title")
        col.addWidget(title)
        col.addWidget(dim("Give an action a key, or a button on a game controller, racing wheel, button "
                          "box or pedals. They work while a game is in front. For a Stream Deck, use a "
                          "key, or the link of the action (see below)."))

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Action", "Key", "Controller, wheel or button box",
                                              "Link"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column, width in ((1, 190), (2, 330), (3, 110)):
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            header.resizeSection(column, width)
        self.table.setMinimumHeight(420)
        col.addWidget(self.table, 1)

        row = QHBoxLayout()

        box = QGroupBox("Stream Deck and other apps")
        v = QVBoxLayout(box)
        self.remote_on = QCheckBox("Let apps on this PC trigger actions through links")
        v.addWidget(self.remote_on)
        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Port"))
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setKeyboardTracking(False)
        port_row.addWidget(self.port)
        port_row.addStretch(1)
        v.addLayout(port_row)
        self.remote_status = dim("")
        v.addWidget(self.remote_status)
        v.addWidget(dim("In the Stream Deck app, drag a 'Website' action onto a key, paste the link of an "
                        "action, and tick 'GET request in background'. Touch Portal, SimHub and similar "
                        "tools can open the same links. Only programs on this PC can use them."))
        row.addWidget(box, 1)

        box = QGroupBox("Controllers found")
        v = QVBoxLayout(box)
        self.pads_on = QCheckBox("Listen to controllers, wheels and button boxes")
        v.addWidget(self.pads_on)
        self.pad_list = QLabel("")
        self.pad_list.setWordWrap(True)
        self.pad_list.setTextFormat(Qt.PlainText)
        v.addWidget(self.pad_list)
        v.addStretch(1)
        row.addWidget(box, 1)
        col.addLayout(row)

        box = QGroupBox("Setup slots")
        grid = QGridLayout(box)
        grid.addWidget(dim("Save different speaker setups (Setup menu, Save this setup as) and put them "
                           "in slots. The 'Load setup slot' actions above switch between them."), 0, 0, 1, 4)
        self.slot_labels = []
        for n in range(len(state.settings.setup_slots)):
            label = QLabel("")
            choose = QPushButton("Choose file")
            clear = QPushButton("Empty")
            grid.addWidget(QLabel(f"Slot {n + 1}"), n + 1, 0)
            grid.addWidget(label, n + 1, 1)
            grid.addWidget(choose, n + 1, 2)
            grid.addWidget(clear, n + 1, 3)
            grid.setColumnStretch(1, 1)
            choose.clicked.connect(lambda _c=False, i=n: self._choose_slot(i))
            clear.clicked.connect(lambda _c=False, i=n: self._set_slot(i, ""))
            self.slot_labels.append(label)
        col.addWidget(box)

        self.remote_on.toggled.connect(self._remote_toggled)
        self.port.valueChanged.connect(self._port_changed)
        self.pads_on.toggled.connect(self._pads_toggled)
        state.structureChanged.connect(self._outputs_changed)
        self._pad_timer = QTimer(self)
        self._pad_timer.timeout.connect(self._refresh_pads)
        self._pad_timer.start(2000)
        self.load()

    # ---------------------------------------------------------- building
    def load(self) -> None:
        s = self.state.settings
        for w in (self.remote_on, self.port, self.pads_on):
            w.blockSignals(True)
        self.remote_on.setChecked(s.remote_enabled)
        self.port.setValue(int(s.remote_port))
        self.pads_on.setChecked(s.controllers_enabled)
        for w in (self.remote_on, self.port, self.pads_on):
            w.blockSignals(False)
        self._fill_table()
        self._fill_slots()
        self._refresh_remote()
        self._refresh_pads()

    def _outputs_changed(self) -> None:
        if self.table.rowCount() != len(all_actions(self.state.project)):
            self._fill_table()

    def _fill_table(self) -> None:
        actions = all_actions(self.state.project)
        bindings = self.state.settings.bindings
        for r in range(self.table.rowCount()):         # take the old buttons away at once
            for c in range(self.table.columnCount()):
                old = self.table.cellWidget(r, c)
                if old is not None:
                    old.hide()
                    self.table.removeCellWidget(r, c)
        self.table.setRowCount(len(actions))
        for r, action in enumerate(actions):
            item = QLabel(f"  {action.label}")
            item.setToolTip(f"{action.group}")
            self.table.setCellWidget(r, 0, item)
            for c, kind in ((1, "key"), (2, "pad")):
                self.table.setCellWidget(r, c, self._binding_cell(action, kind,
                                                                  binding_for(bindings, action.key, kind)))
            link = QPushButton("Copy link")
            link.setEnabled(self.window.remote.running)
            link.setToolTip(self.window.remote.url(action.key))
            link.clicked.connect(lambda _c=False, a=action.key: self._copy_link(a))
            self.table.setCellWidget(r, 3, link)
        self.table.resizeRowsToContents()

    def _binding_cell(self, action, kind, binding) -> QWidget:
        cell = QWidget()
        h = QHBoxLayout(cell)
        h.setContentsMargins(4, 2, 4, 2)
        text = binding["text"] if binding else ("Set key" if kind == "key" else "Set button")
        set_btn = QPushButton(text if len(text) <= 36 else text[:34] + "...")
        if binding:
            set_btn.setStyleSheet("font-weight: 600;")
            set_btn.setToolTip(f"{binding['text']}. Click to choose another.")
        set_btn.clicked.connect(lambda _c=False: self.capture(action, kind))
        h.addWidget(set_btn)
        if binding:
            clear = QPushButton("×")
            clear.setFixedWidth(30)
            clear.setToolTip("Remove")
            clear.clicked.connect(lambda _c=False: self._clear(action.key, kind))
            h.addWidget(clear)
        return cell

    # ---------------------------------------------------------- binding
    def capture(self, action, kind) -> None:
        if kind == "pad":
            if not self.state.settings.controllers_enabled:
                QMessageBox.information(self, "Controls", "Switch on 'Listen to controllers' first.")
                return
            dialog = PadCaptureDialog(self, action.label, self.window.pads)
        else:
            dialog = KeyCaptureDialog(self, action.label)
        self.capturing = True
        try:
            accepted = dialog.exec() == QDialog.Accepted and dialog.binding
        finally:
            self.capturing = False
        if accepted:
            self.bind(action.key, dialog.binding)

    def bind(self, action_key: str, binding: dict) -> None:
        lost = set_binding(self.state.settings.bindings, action_key, binding)
        self._bindings_changed()
        if lost:
            names = ", ".join(self.window.actions.label(a) for a in lost)
            self.state.notice.emit(f"{binding['text']} was taken away from: {names}")

    def _clear(self, action_key: str, kind: str) -> None:
        clear_binding(self.state.settings.bindings, action_key, kind)
        self._bindings_changed()

    def _bindings_changed(self) -> None:
        self.state.save_settings()
        failed = self.window.apply_hotkeys()
        self._fill_table()
        self.bindingsChanged.emit()
        if failed:
            QMessageBox.warning(self, "Controls", "Another program already uses: " + ", ".join(failed) +
                                "\n\nChoose a different key for that action.")

    # ---------------------------------------------------------- remote
    def _remote_toggled(self, on: bool) -> None:
        self.state.settings.remote_enabled = on
        self.state.save_settings()
        self.window.apply_remote()
        self._refresh_remote()
        self._fill_table()

    def _port_changed(self, port: int) -> None:
        self.state.settings.remote_port = int(port)
        self.state.save_settings()
        if self.state.settings.remote_enabled or self.state.settings.simhub_link:
            self.window.apply_remote()
        self._refresh_remote()
        self._fill_table()

    def _refresh_remote(self) -> None:
        remote = self.window.remote
        if not self.state.settings.remote_enabled:
            self.remote_status.setText("Off" + (" (the SimHub link on the Effects tab still uses this port)"
                                                if self.state.settings.simhub_link else ""))
        elif remote.running:
            self.remote_status.setText(f"On. Example: {remote.url('mute')}")
        else:
            self.remote_status.setText(remote.error or "Could not start")

    def _copy_link(self, action_key: str) -> None:
        QGuiApplication.clipboard().setText(self.window.remote.url(action_key))
        self.state.notice.emit("Link copied. Paste it into the Website action of your Stream Deck.")

    # ---------------------------------------------------------- controllers
    def _pads_toggled(self, on: bool) -> None:
        self.state.settings.controllers_enabled = on
        self.state.save_settings()
        self.window.apply_pads()
        self._refresh_pads()

    def _refresh_pads(self) -> None:
        if not self.isVisible() and self.pad_list.text():
            return
        pads = self.window.pads
        if not self.state.settings.controllers_enabled:
            self.pad_list.setText("Off")
        elif not pads.available:
            self.pad_list.setText(pads.error or "Controller support could not be started.")
        else:
            found = pads.devices()
            self.pad_list.setText("\n".join(f"{d.name}  ({d.buttons} buttons)" for d in found)
                                  or "None plugged in right now")

    # ---------------------------------------------------------- setup slots
    def _fill_slots(self) -> None:
        for label, path in zip(self.slot_labels, self.state.settings.setup_slots):
            label.setText(os.path.basename(path) if path else "Empty")
            label.setToolTip(path)

    def _choose_slot(self, index: int) -> None:
        path, _ = QFileDialog.getOpenFileName(self, f"Setup for slot {index + 1}",
                                              setups_dir(self.state.settings), "SpeakerWeave setup (*.json)")
        if path:
            remember_setup_folder(self.state.settings, path)
            self._set_slot(index, path)

    def _set_slot(self, index: int, path: str) -> None:
        self.state.settings.setup_slots[index] = path
        self.state.save_settings()
        self._fill_slots()
