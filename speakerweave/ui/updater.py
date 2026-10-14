"""The update dialogs. The work itself is in speakerweave/updates.py."""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from .. import __version__, paths, updates
from ..release import APP_NAME


class UpdateController(QObject):
    checked = Signal(object, str, bool)     # release or None, error text, asked by the user
    available = Signal()                    # a newer version was found (or is gone again)
    progress = Signal(int, int)
    downloaded = Signal(str, str)           # path, error text

    def __init__(self, window, state):
        super().__init__(window)
        self.window = window
        self.state = state
        self._busy = False
        self._dialog = None
        self.info = None                    # the newer version found by the last check, or None
        self.checked.connect(self._on_checked)
        self.progress.connect(self._on_progress)
        self.downloaded.connect(self._on_downloaded)

    # ------------------------------------------------------------ checking
    def check(self, manual: bool) -> None:
        """manual = the user pressed the menu item, so always say what was found."""
        if self._busy:
            return
        if not updates.configured():
            if manual:
                QMessageBox.information(
                    self.window, APP_NAME,
                    f"You have version {__version__}.\n\nThis copy has no update address yet. "
                    f"It is set in speakerweave/release.py before the installer is built.")
            return
        self._busy = True

        def work():
            try:
                self.checked.emit(updates.check(), "", manual)
            except Exception as exc:
                self.checked.emit(None, str(exc), manual)

        threading.Thread(target=work, daemon=True).start()

    def _on_checked(self, info, error: str, manual: bool) -> None:
        self._busy = False
        if error:
            if manual:
                QMessageBox.warning(self.window, APP_NAME, f"Could not check for updates.\n\n{error}")
            return
        self.info = info
        self.available.emit()
        if info is None:
            if manual:
                QMessageBox.information(self.window, APP_NAME,
                                        f"You have the newest version ({__version__}).")
            return
        if manual:
            self.offer(info)
        else:
            # found by the check in the background: a notice on the Errors page and a
            # small note by the Errors button, never a window in the way
            self.window.show_update_note(info)

    def install(self, info=None) -> None:
        """Download and install, or open the download page when this copy cannot
        install by itself (it runs from its project folder, or the release has no file)."""
        info = info or self.info
        if info is None:
            return
        if info.url and paths.is_built():
            self.start_download(info)
        elif info.page or info.url:
            QDesktopServices.openUrl(QUrl(info.page or info.url))

    # ------------------------------------------------------------ offering
    def offer(self, info) -> None:
        box = QMessageBox(self.window)
        box.setWindowTitle(f"{APP_NAME} update")
        box.setIcon(QMessageBox.Information)
        box.setText(f"Version {info.version.lstrip('vV')} is available. You have {__version__}.")
        notes = (info.notes or "").strip()
        if notes:
            box.setInformativeText(notes if len(notes) < 900 else notes[:900].rstrip() + " ...")
        install = page = None
        if info.url and paths.is_built():
            install = box.addButton("Download and install", QMessageBox.AcceptRole)
        if info.page or info.url:
            page = box.addButton("Open the download page", QMessageBox.ActionRole)
        box.addButton("Later", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if install is not None and clicked is install:
            self.start_download(info)
        elif page is not None and clicked is page:
            QDesktopServices.openUrl(QUrl(info.page or info.url))

    # ------------------------------------------------------------ installing
    def start_download(self, info) -> None:
        if self._busy:
            return
        self._busy = True
        self._dialog = QProgressDialog("Downloading the update...", None, 0, 0, self.window)
        self._dialog.setWindowTitle(f"{APP_NAME} update")
        self._dialog.setWindowModality(Qt.WindowModal)
        self._dialog.setMinimumDuration(0)
        self._dialog.setAutoClose(False)
        self._dialog.show()

        def work():
            try:
                path = updates.download(info, progress=lambda done, total: self.progress.emit(
                    done // 1024, total // 1024))
                self.downloaded.emit(path, "")
            except Exception as exc:
                self.downloaded.emit("", str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _on_progress(self, done_kb: int, total_kb: int) -> None:
        if self._dialog is None:
            return
        if total_kb > 0:
            self._dialog.setMaximum(total_kb)
            self._dialog.setValue(min(done_kb, total_kb))
            self._dialog.setLabelText(f"Downloading the update...  "
                                      f"{done_kb / 1024:.0f} of {total_kb / 1024:.0f} MB")

    def _on_downloaded(self, path: str, error: str) -> None:
        self._busy = False
        if self._dialog is not None:
            self._dialog.close()
            self._dialog = None
        if error:
            QMessageBox.warning(self.window, APP_NAME, f"The update was not installed.\n\n{error}")
            return
        try:
            updates.launch_installer(path)
        except Exception as exc:
            QMessageBox.warning(self.window, APP_NAME,
                                f"The installer could not be started.\n\n{exc}\n\nIt was saved to\n{path}")
            return
        self.state.shutdown()
        QApplication.quit()
