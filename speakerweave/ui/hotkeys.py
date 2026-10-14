"""Keyboard shortcuts that work everywhere, also while a game has the focus.

On Windows they are registered with the system (RegisterHotKey), which makes
them global. Elsewhere they fall back to shortcuts that work while the
SpeakerWeave window is active.
"""
from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication

WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000


class _Filter(QAbstractNativeEventFilter):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) == b"windows_generic_MSG":
            from ctypes import wintypes
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                self.owner.fired.emit(int(msg.wParam))
                return True, 0
        return False, 0


class GlobalHotkeys(QObject):
    fired = Signal(int)                 # internal: id of the hotkey Windows reported
    triggered = Signal(str)             # action key

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.windows = sys.platform.startswith("win")
        self._ids: dict[int, str] = {}
        self._shortcuts: list = []
        self.failed: list = []          # texts of keys another program already owns
        self.fired.connect(self._on_fired)
        if self.windows:
            self._filter = _Filter(self)
            QApplication.instance().installNativeEventFilter(self._filter)

    def _on_fired(self, hotkey_id: int) -> None:
        action = self._ids.get(hotkey_id)
        if action:
            self.triggered.emit(action)

    def clear(self) -> None:
        if self.windows:
            hwnd = int(self.window.winId())
            for hotkey_id in self._ids:
                ctypes.windll.user32.UnregisterHotKey(hwnd, hotkey_id)
        for shortcut in self._shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._ids, self._shortcuts = {}, []

    def apply(self, bindings: list) -> list:
        """Registers every keyboard binding. Returns the ones that could not be
        registered because another program already uses that key."""
        self.clear()
        self.failed = []
        next_id = 0xB000
        for binding in bindings:
            if binding.get("kind") != "key":
                continue
            action = binding["action"]
            if self.windows and binding.get("vk"):
                hwnd = int(self.window.winId())
                ok = ctypes.windll.user32.RegisterHotKey(hwnd, next_id,
                                                         int(binding.get("mods", 0)) | MOD_NOREPEAT,
                                                         int(binding["vk"]))
                if ok:
                    self._ids[next_id] = action
                else:
                    self.failed.append(binding.get("text", "?"))
                next_id += 1
            elif binding.get("qt"):
                shortcut = QShortcut(QKeySequence(binding["qt"]), self.window)
                shortcut.setContext(Qt.ApplicationShortcut)
                shortcut.activated.connect(lambda a=action: self.triggered.emit(a))
                self._shortcuts.append(shortcut)
        return self.failed
