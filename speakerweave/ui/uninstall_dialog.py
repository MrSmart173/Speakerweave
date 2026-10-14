"""Settings page, Uninstall SpeakerWeave: the steps from the button to the uninstaller.

    1. why are you leaving?     the feedback window (prepared, not built yet)
    2. what should go?          UninstallDialog
    3. remove it                SpeakerWeave hands Windows a real sound output back,
                                starts the uninstaller and closes
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QVBoxLayout)

from .. import simhub, uninstall
from ..uninstall import Feedback
from .panels import dim
from .state import config_dir

# Step 1. The feedback window, once it is built: a QDialog class taking the parent
# window, with a feedback() method that returns an uninstall.Feedback. While this is
# None nothing is asked and the uninstall goes straight to step 2.
FEEDBACK_WINDOW = None


def ask_why(parent):
    """The person's reasons for uninstalling, an empty Feedback while the window does
    not exist yet, or None when they pressed Cancel there (then nothing is removed)."""
    if FEEDBACK_WINDOW is None:
        return Feedback()
    window = FEEDBACK_WINDOW(parent)
    if window.exec() != QDialog.Accepted:
        return None
    return window.feedback()


class UninstallDialog(QDialog):
    """Step 2: what will happen, and whether the person's own data goes too."""

    def __init__(self, parent, installed: bool, data_dir: str, project_dir: str = "",
                 simhub_running: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Uninstall SpeakerWeave")
        self.setMinimumWidth(500)
        col = QVBoxLayout(self)
        col.setSpacing(10)
        col.setContentsMargins(20, 18, 20, 16)
        head = QLabel("Uninstall SpeakerWeave from this PC?")
        head.setStyleSheet("font-size: 16px; font-weight: 700;")
        col.addWidget(head)
        if installed:
            text = ("SpeakerWeave closes and Windows plays through a normal sound output again. Then "
                    "the program, its shortcuts, its start with Windows entry and its SimHub plugin "
                    "are removed.")
        else:
            text = ("This copy runs from its project folder, so it has no uninstaller. SpeakerWeave "
                    "hands Windows a normal sound output back, removes its start with Windows entry "
                    "and its SimHub plugin, and closes. Delete the project folder by hand afterwards"
                    + (f":\n{project_dir}" if project_dir else "."))
        body = QLabel(text)
        body.setWordWrap(True)
        col.addWidget(body)
        self.remove_data = QCheckBox("Also delete my settings, speaker setups, game setups and test sounds")
        self.remove_data.setChecked(True)
        col.addWidget(self.remove_data)
        col.addWidget(dim(f"They are kept in {data_dir}. Setups you saved somewhere else yourself "
                          f"stay where they are."))
        if simhub_running:
            note = QLabel("SimHub is running. Close it first, so its SpeakerWeave plugin can be "
                          "removed too.")
            note.setObjectName("warn")
            note.setWordWrap(True)
            col.addWidget(note)
        col.addWidget(dim("VB-CABLE, the virtual sound device, stays installed, as other apps may use "
                          "it too."))
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        self.go = QPushButton("Uninstall" if installed else "Remove and close")
        self.go.setObjectName("danger")
        row.addWidget(cancel)
        row.addWidget(self.go)
        col.addLayout(row)
        cancel.clicked.connect(self.reject)
        self.go.clicked.connect(self.accept)
        cancel.setDefault(True)
        cancel.setFocus(Qt.OtherFocusReason)


def start_uninstall(window) -> bool:
    """Runs the steps. Returns True when SpeakerWeave is being removed (it then closes)."""
    state = window.state
    feedback = ask_why(window)
    if feedback is None:
        return False
    uninstaller = uninstall.find_uninstaller()
    folder = simhub.find_folder()
    plugin_in = bool(folder) and os.path.isfile(os.path.join(folder, simhub.PLUGIN_FILE))
    data_dir = config_dir()
    project_dir = "" if uninstaller else os.path.dirname(os.path.dirname(os.path.abspath(uninstall.__file__)))
    dialog = UninstallDialog(window, bool(uninstaller), data_dir, project_dir,
                             simhub_running=plugin_in and simhub.simhub_running())
    if dialog.exec() != QDialog.Accepted:
        return False
    remove_data = dialog.remove_data.isChecked()
    uninstall.send_feedback(feedback)

    # the sound stops and Windows plays into real speakers again
    was_running = state.runner.running
    state.stop(keep_windows=True)
    uninstall.hand_back_windows_output(state.settings, state.project)
    state.save_settings()

    if uninstaller:
        uninstall.mark_data_for_removal(data_dir, remove_data)
        problem = uninstall.launch(uninstaller, uninstall.uninstaller_arguments(remove_data, data_dir))
        if problem:
            uninstall.mark_data_for_removal(data_dir, False)
            QMessageBox.warning(window, "Uninstall SpeakerWeave", problem)
            if was_running:
                state.start()               # nothing was removed: carry on as before
            return False
        if remove_data:
            state.saving_blocked = True     # the uninstaller deletes the folder once we are gone
        window.quit_app()
        return True

    # a copy without an uninstaller: SpeakerWeave removes what it can itself
    notes = []
    uninstall.remove_autostart()
    done, message = simhub.remove_plugin(folder)
    if not done and message:
        notes.append(message)
    if remove_data:
        state.saving_blocked = True
        problem = uninstall.remove_data(data_dir)
        if problem:
            notes.append(problem)
    text = "SpeakerWeave closes now."
    if project_dir:
        text += f" Delete its project folder by hand:\n{project_dir}"
    if notes:
        text += "\n\n" + "\n\n".join(notes)
    QMessageBox.information(window, "Uninstall SpeakerWeave", text)
    window.quit_app()
    return True
