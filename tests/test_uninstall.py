"""Uninstalling from the Settings page: what is removed, and the prepared feedback step."""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget

from fake_audio import FakeSoundDevice
from speakerweave import backend, uninstall, windefault
from speakerweave.model import Project
from speakerweave.settings import AppSettings


def data_folder():
    folder = os.path.join(tempfile.mkdtemp(), "SpeakerWeave")
    os.makedirs(os.path.join(folder, "Game setups"))
    for name in ("settings.json", "last setup.json", os.path.join("Game setups", "iRacing.json")):
        with open(os.path.join(folder, name), "w") as fh:
            fh.write("{}")
    return folder


def test_only_speakerweaves_own_folder_can_be_deleted():
    folder = data_folder()
    assert uninstall.is_data_folder(folder)
    for wrong in ("", os.path.expanduser("~"), os.path.dirname(folder), os.path.abspath(os.sep)):
        assert not uninstall.is_data_folder(wrong)
    assert "left alone" in uninstall.remove_data(os.path.dirname(folder))
    assert os.path.isdir(folder)
    assert uninstall.remove_data(folder) == "" and not os.path.exists(folder)


def test_the_uninstaller_is_found_and_told_what_to_remove():
    app_dir = tempfile.mkdtemp()
    for name in ("unins000.exe", "unins001.exe", "SpeakerWeave.exe"):
        open(os.path.join(app_dir, name), "wb").close()
    assert uninstall.find_uninstaller(app_dir) == os.path.join(app_dir, "unins001.exe")
    folder = data_folder()
    args = uninstall.uninstaller_arguments(True, folder)
    assert args.startswith("/SILENT /NORESTART") and f'/REMOVEDATA="{folder}"' in args
    assert uninstall.uninstaller_arguments(False, folder).endswith("/KEEPDATA")
    assert uninstall.uninstaller_arguments(True, tempfile.mkdtemp()).endswith("/KEEPDATA")
    uninstall.mark_data_for_removal(folder)
    assert os.path.isfile(os.path.join(folder, uninstall.REMOVE_MARK))
    uninstall.mark_data_for_removal(folder, False)
    assert not os.path.exists(os.path.join(folder, uninstall.REMOVE_MARK))


def test_windows_never_stays_on_the_virtual_device(monkeypatch):
    outputs = [("cable", "CABLE Input (VB-Audio Virtual Cable)"), ("hdmi", "LG TV (NVIDIA High Definition Audio)"),
               ("rt", "Speakers (Realtek(R) Audio)")]
    current = {"0": "cable", "1": "cable", "2": "cable"}
    monkeypatch.setattr(windefault, "supported", lambda: True)
    monkeypatch.setattr(windefault, "list_outputs", lambda: outputs)
    monkeypatch.setattr(windefault, "defaults", lambda: dict(current))

    def set_default(dev_id, roles=(0, 1, 2)):
        for role in roles:
            current[str(role)] = dev_id
    monkeypatch.setattr(windefault, "set_default", set_default)
    project = Project()
    project.add_device("Speakers (Realtek(R) Audio)", 2)
    settings = AppSettings()
    # CABLE was already the default before SpeakerWeave: one of the setup's own outputs takes over
    assert uninstall.hand_back_windows_output(settings, project) == "Speakers (Realtek(R) Audio)"
    assert set(current.values()) == {"rt"}
    # the output Windows used before SpeakerWeave comes back first
    current.update({"0": "cable", "1": "cable", "2": "cable"})
    settings.managed_output, settings.previous_outputs = "cable", {"0": "hdmi", "1": "hdmi", "2": "hdmi"}
    assert uninstall.hand_back_windows_output(settings, project).startswith("LG TV")
    assert settings.managed_output == ""
    # already on real speakers: nothing changes
    assert uninstall.hand_back_windows_output(AppSettings(), Project()).startswith("LG TV")


class FakeWindow(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.quit = False

    def quit_app(self):
        self.quit = True


@pytest.fixture
def rig(monkeypatch):
    app = QApplication.instance() or QApplication([])
    folder = data_folder()
    from speakerweave.ui import state as state_module
    from speakerweave.ui import uninstall_dialog
    monkeypatch.setattr(state_module, "config_dir", lambda: folder)
    monkeypatch.setattr(uninstall_dialog, "config_dir", lambda: folder)
    monkeypatch.setattr(uninstall_dialog.simhub, "find_folder", lambda: "")
    backend._sd = lambda: FakeSoundDevice([{"name": "Speakers", "outputs": 2}])
    state = state_module.AppState("")
    state.settings.default_output = False
    launched = []
    monkeypatch.setattr(uninstall, "launch", lambda path, args: launched.append((path, args)) or "")
    answers = {"dialog": QDialog.Accepted}
    monkeypatch.setattr(uninstall_dialog.UninstallDialog, "exec", lambda self: answers["dialog"])
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    return app, folder, state, launched, answers, uninstall_dialog


def test_installed_copy_starts_its_uninstaller_and_closes(rig, monkeypatch):
    app, folder, state, launched, answers, dialog = rig
    monkeypatch.setattr(uninstall, "find_uninstaller", lambda: r"C:\SpeakerWeave\unins000.exe")
    window = FakeWindow(state)
    answers["dialog"] = QDialog.Rejected
    assert not dialog.start_uninstall(window) and launched == [] and not window.quit
    answers["dialog"] = QDialog.Accepted
    assert dialog.start_uninstall(window)
    assert launched[0][0].endswith("unins000.exe") and "/REMOVEDATA=" in launched[0][1]
    assert window.quit and state.saving_blocked
    assert os.path.isfile(os.path.join(folder, uninstall.REMOVE_MARK))
    assert os.path.isdir(folder)                     # the uninstaller deletes it once the app is gone


def test_a_refused_uninstall_keeps_everything(rig, monkeypatch):
    app, folder, state, launched, answers, dialog = rig
    monkeypatch.setattr(uninstall, "find_uninstaller", lambda: r"C:\SpeakerWeave\unins000.exe")
    monkeypatch.setattr(uninstall, "launch", lambda path, args: "Windows did not allow it")
    monkeypatch.setattr(dialog.QMessageBox, "warning", lambda *a, **k: None)
    started = []
    monkeypatch.setattr(state, "start", lambda *a, **k: started.append(True))
    window = FakeWindow(state)
    answers["dialog"] = QDialog.Accepted
    assert not dialog.start_uninstall(window) and not window.quit
    assert not state.saving_blocked and started == []     # the sound was off, so it stays off
    assert not os.path.exists(os.path.join(folder, uninstall.REMOVE_MARK))


def test_a_copy_without_uninstaller_removes_its_own_data(rig, monkeypatch):
    app, folder, state, launched, answers, dialog = rig
    monkeypatch.setattr(uninstall, "find_uninstaller", lambda: "")
    window = FakeWindow(state)
    assert dialog.start_uninstall(window)
    assert launched == [] and window.quit and not os.path.exists(folder)
    state.save_settings()
    state.save_now()
    assert not os.path.exists(folder)                # nothing writes it back while closing


def test_the_feedback_step_is_ready_but_asks_nothing_yet(rig, monkeypatch):
    app, folder, state, launched, answers, dialog = rig
    assert dialog.FEEDBACK_WINDOW is None
    assert dialog.ask_why(None).empty()
    monkeypatch.setattr(uninstall, "find_uninstaller", lambda: r"C:\SpeakerWeave\unins000.exe")
    sent = []
    monkeypatch.setattr(uninstall, "send_feedback", sent.append)

    class Window(QDialog):                           # what the real window will look like
        answer = QDialog.Rejected

        def exec(self):
            return self.answer

        def feedback(self):
            return uninstall.Feedback(reasons=["too_hard"], comment="testing")

    monkeypatch.setattr(dialog, "FEEDBACK_WINDOW", Window)
    window = FakeWindow(state)
    assert not dialog.start_uninstall(window) and launched == []     # Cancel there stops it all
    Window.answer = QDialog.Accepted
    assert dialog.start_uninstall(window)
    assert sent[0].reasons == ["too_hard"] and launched


def test_the_settings_page_has_the_uninstall_button():
    from speakerweave.ui import state as state_module
    folder = data_folder()
    state_module.config_dir = lambda: folder
    from speakerweave.ui.state import AppState
    from speakerweave.ui.window import MainWindow
    app = QApplication.instance() or QApplication([])
    backend._sd = lambda: FakeSoundDevice([{"name": "Speakers", "outputs": 2}])
    state = AppState("")
    state.settings.default_output = state.settings.start_sound = state.settings.simhub_link = False
    state.settings.tour_done = True
    window = MainWindow(state)
    button = window.settings_page.uninstall_btn
    assert button.text().startswith("Uninstall SpeakerWeave") and button.objectName() == "danger"
    window._quitting = True                 # a full close: timers, links and controllers stop
    window.close()
    app.processEvents()
