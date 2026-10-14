"""A small window listing the Bluetooth devices paired with this PC."""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout)

from .. import bluetooth
from . import theme
from .panels import dim


class _Fetcher(QObject):
    finished = Signal(list, str)


class BluetoothDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Bluetooth devices")
        self.setMinimumSize(460, 420)
        v = QVBoxLayout(self)
        title = QLabel("Bluetooth devices paired with this PC")
        title.setObjectName("title")
        v.addWidget(title)
        self.status = dim("Looking...")
        v.addWidget(self.status)
        self.list = QListWidget()
        v.addWidget(self.list, 1)
        v.addWidget(dim("Bluetooth speakers and headphones show up in the Sound outputs list once "
                        "they are connected. Bluetooth adds a noticeable delay, so use Extra delay on "
                        "your other outputs (Output tab) to line them up with it. To pair a new "
                        "device or connect one, open the Windows Bluetooth settings."))
        row = QHBoxLayout()
        self.open_btn = QPushButton("Open Windows Bluetooth settings")
        self.open_btn.setObjectName("primary")
        self.refresh_btn = QPushButton("Refresh")
        close = QPushButton("Close")
        row.addWidget(self.open_btn)
        row.addWidget(self.refresh_btn)
        row.addStretch(1)
        row.addWidget(close)
        v.addLayout(row)
        self.open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("ms-settings:bluetooth")))
        self.refresh_btn.clicked.connect(self.refresh)
        close.clicked.connect(self.accept)
        self._fetcher = _Fetcher()
        self._fetcher.finished.connect(self._show)
        self.refresh()

    def refresh(self) -> None:
        self.status.setText("Looking...")
        self.refresh_btn.setEnabled(False)

        def work():
            try:
                self._fetcher.finished.emit(bluetooth.list_devices(), "")
            except Exception as exc:
                self._fetcher.finished.emit([], str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _show(self, devices: list, error: str) -> None:
        self.refresh_btn.setEnabled(True)
        self.list.clear()
        if error:
            self.status.setText(f"The list could not be read: {error}")
            return
        if not devices:
            self.status.setText("No Bluetooth devices are paired with this PC.")
            return
        available = sum(1 for d in devices if d.available)
        self.status.setText(f"{len(devices)} paired, {available} available right now.")
        for dev in devices:
            kind = "Bluetooth LE" if dev.low_energy else "Bluetooth"
            text = f"{dev.name}    ({kind}, {'available' if dev.available else 'not available'})"
            item = QListWidgetItem(text)
            item.setForeground(QColor(theme.TEXT if dev.available else theme.DIM))
            self.list.addItem(item)
