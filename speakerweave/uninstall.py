"""Removing SpeakerWeave from this PC (Settings page, Uninstall SpeakerWeave).

The installed app has the uninstaller its installer left behind (unins000.exe).
SpeakerWeave hands Windows a real sound output back, starts that uninstaller with
what the person chose, and quits. The uninstaller waits until SpeakerWeave has closed
(the running app holds APP_MUTEX), then removes:
  * the program files and the Start menu and desktop shortcuts
  * SpeakerWeave from the list of apps that start with Windows
  * the SpeakerWeave plugin in SimHub
  * when chosen, the folder with the settings, speaker setups, game setups and test sounds
Uninstalling from Windows Settings, Apps runs the same uninstaller, which then asks
about that folder itself.

A copy that runs from its project folder has no uninstaller. SpeakerWeave then removes
its own data, its start with Windows entry and the SimHub plugin, and the project
folder can be deleted by hand.

The person can later be asked why they are leaving (see Feedback). That window is
prepared for but not built yet.
"""
from __future__ import annotations

import glob
import os
import shutil
import sys
from dataclasses import dataclass, field

from . import default_output, paths, windefault
from .speaker_library import recognise

APP_ID = "{EDB9FFFE-5B25-4100-AC8F-3D212E27D4EA}_is1"     # the AppId in SpeakerWeave.iss
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall" + "\\" + APP_ID
APP_MUTEX = "SpeakerWeaveAppRunning"                      # the uninstaller waits for it to go
REMOVE_MARK = "remove on uninstall"     # left in the data folder when it should go as well

_mutex = None


# ---------------------------------------------------------------- feedback (prepared)
@dataclass
class Feedback:
    """Why someone uninstalls SpeakerWeave.

    Filled in by the feedback window, which is not built yet. Until then it stays
    empty and nothing is asked or sent. When the window is added it fills in
    reasons (the keys of the reasons that were clicked) and comment (anything typed).
    """
    reasons: list = field(default_factory=list)
    comment: str = ""

    def empty(self) -> bool:
        return not self.reasons and not self.comment.strip()


def send_feedback(feedback: Feedback) -> None:
    """Passes the answers on before SpeakerWeave closes. Where they go is decided
    together with the feedback window, so for now nothing leaves this PC."""
    if feedback is None or feedback.empty():
        return


# ---------------------------------------------------------------- the running app
def hold_running_mutex() -> None:
    """Called once when the app opens: while SpeakerWeave runs this name exists,
    so its uninstaller knows to wait for it to close."""
    global _mutex
    if _mutex is not None or not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, APP_MUTEX)
    except Exception:
        _mutex = None


# ---------------------------------------------------------------- finding the uninstaller
def _registry_uninstaller() -> str:
    if not sys.platform.startswith("win"):
        return ""
    import winreg
    places = [(winreg.HKEY_CURRENT_USER, 0), (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
              (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY)]
    for hive, view in places:
        try:
            with winreg.OpenKey(hive, UNINSTALL_KEY, 0, winreg.KEY_READ | view) as key:
                value = str(winreg.QueryValueEx(key, "UninstallString")[0])
        except OSError:
            continue
        path = value.strip()
        if path.startswith('"'):
            path = path[1:].split('"', 1)[0]
        else:
            path = path.split(" /", 1)[0]
        if os.path.isfile(path):
            return path
    return ""


def find_uninstaller(app_dir: str = None) -> str:
    """The uninstaller of the installed SpeakerWeave, or "" when this copy has none.
    The one next to the running SpeakerWeave.exe comes first."""
    if app_dir is None and paths.is_built():
        app_dir = os.path.dirname(sys.executable)
    if app_dir:
        found = sorted(glob.glob(os.path.join(app_dir, "unins[0-9][0-9][0-9].exe")))
        if found:
            return found[-1]
    return _registry_uninstaller()


def uninstaller_arguments(remove_data: bool, data_dir: str) -> str:
    """/SILENT: no "are you sure" (the person already said yes in SpeakerWeave) and no
    message at the end, just the progress window. The other switches are read by the
    [Code] part of SpeakerWeave.iss."""
    parts = ["/SILENT", "/NORESTART"]
    if remove_data and is_data_folder(data_dir):
        parts.append(f'/REMOVEDATA="{os.path.normpath(data_dir)}"')
    else:
        parts.append("/KEEPDATA")
    return " ".join(parts)


def launch(uninstaller: str, arguments: str) -> str:
    """Starts the uninstaller. Returns a problem to show, or "" when it started.
    Windows asks for administrator rights itself when SpeakerWeave was installed
    for everyone."""
    if not sys.platform.startswith("win"):
        return "Only Windows has an uninstaller to start."
    try:
        os.startfile(uninstaller, "open", arguments)
    except OSError as exc:
        if getattr(exc, "winerror", 0) == 1223:      # the person said no to Windows
            return "Windows did not allow it, so nothing was removed."
        return f"The uninstaller did not start ({exc.strerror or exc})."
    return ""


# ---------------------------------------------------------------- data
def is_data_folder(folder: str) -> bool:
    """Only SpeakerWeave's own folder may be deleted, never anything that merely
    contains it (a broken path must not empty a user folder or a drive)."""
    if not folder:
        return False
    folder = os.path.normpath(os.path.abspath(folder))
    name = os.path.basename(folder).lower()
    if not name.startswith("speakerweave"):
        return False
    home = os.path.normpath(os.path.expanduser("~"))
    return folder != home and os.path.dirname(folder) != folder


def remove_data(folder: str) -> str:
    """Deletes SpeakerWeave's data folder. Returns a problem, or ""."""
    if not is_data_folder(folder):
        return f"{folder} does not look like SpeakerWeave's own folder, so it was left alone."
    if not os.path.isdir(folder):
        return ""
    failed = []
    shutil.rmtree(folder, onerror=lambda _f, path, _e: failed.append(path))
    if failed:
        return f"{len(failed)} file(s) in {folder} could not be deleted. Delete the folder by hand."
    return ""


def mark_data_for_removal(folder: str, on: bool = True) -> None:
    """A second way of telling the uninstaller the data goes too, next to /REMOVEDATA.
    Taken away again when SpeakerWeave opens, so a cancelled uninstall leaves no mark."""
    path = os.path.join(folder, REMOVE_MARK)
    try:
        if on and is_data_folder(folder):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("SpeakerWeave's uninstaller deletes this folder.\n")
        elif os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def remove_autostart() -> None:
    if not sys.platform.startswith("win"):
        return
    import winreg
    from .autostart import RUN_KEY, VALUE
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE)
    except OSError:
        pass


# ---------------------------------------------------------------- the Windows sound output
def _is_virtual(name: str) -> bool:
    entry = recognise(name or "")
    return entry is not None and entry.category == "virtual"


def hand_back_windows_output(settings, project) -> str:
    """Once SpeakerWeave is gone nothing passes the virtual device on to the speakers,
    so Windows must play into a real output again. Puts back the output Windows used
    before SpeakerWeave, or else one of the outputs of the speaker setup, or else any
    real output. Returns the name of the output Windows plays into afterwards."""
    if not windefault.supported():
        return ""
    try:
        default_output.restore(settings)
    except Exception:
        settings.managed_output, settings.previous_outputs = "", {}
    try:
        outputs = windefault.list_outputs()
        names = dict(outputs)
        current = windefault.defaults()
        if not any(_is_virtual(names.get(dev_id, "")) for dev_id in current.values() if dev_id):
            return names.get(current.get("0", ""), "")
        choice = ""
        for dev in project.devices if project is not None else []:
            if dev.enabled and not _is_virtual(dev.name):
                choice = windefault.find(dev.name, outputs)
                if choice:
                    break
        if not choice:
            choice = next((dev_id for dev_id, name in outputs if not _is_virtual(name)), "")
        if choice:
            windefault.set_default(choice)
        return names.get(choice, "")
    except Exception:
        return ""
