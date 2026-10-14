"""SimHub on this PC: where it is installed, and putting the SpeakerWeave plugin into it.

The plugin (packaging/simhub) tells SpeakerWeave which game SimHub sees running, so
SpeakerWeave can load the speaker setup chosen for that game, and it gives SimHub
SpeakerWeave's actions (volume, mute, setups ...) and state as properties.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys

PLUGIN_FILE = "SpeakerWeave.SimHubPlugin.dll"
SIMHUB_EXE = "SimHubWPF.exe"

# SimHub's own short names of the games most people drive, and how to show them
GAME_TITLES = {
    "iracing": "iRacing",
    "assettocorsa": "Assetto Corsa",
    "assettocorsacompetizione": "Assetto Corsa Competizione",
    "assettocorsaevo": "Assetto Corsa EVO",
    "assettocorsarally": "Assetto Corsa Rally",
    "rfactor2": "rFactor 2",
    "rfactor1": "rFactor",
    "lmu": "Le Mans Ultimate",
    "lemansultimate": "Le Mans Ultimate",
    "rrre": "RaceRoom",
    "automobilista2": "Automobilista 2",
    "automobilista": "Automobilista",
    "pcars2": "Project CARS 2",
    "pcars": "Project CARS",
    "dr2": "DiRT Rally 2.0",
    "dirtrally2": "DiRT Rally 2.0",
    "dirtrally": "DiRT Rally",
    "eawrc23": "EA SPORTS WRC",
    "eawrc": "EA SPORTS WRC",
    "wrcgenerations": "WRC Generations",
    "rbr": "Richard Burns Rally",
    "richardburnsrally": "Richard Burns Rally",
    "beamng": "BeamNG.drive",
    "beamngdrive": "BeamNG.drive",
    "forzahorizon5": "Forza Horizon 5",
    "forzamotorsport": "Forza Motorsport",
    "gt7": "Gran Turismo 7",
    "ets2": "Euro Truck Simulator 2",
    "ats": "American Truck Simulator",
    "kartkraft": "KartKraft",
    "rennsport": "Rennsport",
}


def game_title(code: str) -> str:
    """A readable name for SimHub's game code, for example "AssettoCorsa" -> "Assetto Corsa"."""
    if not code:
        return "No game running"
    key = re.sub(r"[^a-z0-9]", "", code.lower())
    if key in GAME_TITLES:
        return GAME_TITLES[key]
    if key.startswith("f1") and key[2:].isdigit():
        return f"F1 {key[2:]}"
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z0-9])|(?<=[0-9])(?=[A-Z])", " ", code)
    return spaced.strip() or code


def _registry_folders() -> list:
    if sys.platform != "win32":
        return []
    import winreg
    found = []
    roots = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall")]
    for hive, path in roots:
        try:
            key = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with key:
            for i in range(4096):
                try:
                    sub = winreg.EnumKey(key, i)
                except OSError:
                    break
                try:
                    with winreg.OpenKey(key, sub) as entry:
                        name = str(winreg.QueryValueEx(entry, "DisplayName")[0])
                        if not name.lower().startswith("simhub version"):
                            continue
                        found.append(str(winreg.QueryValueEx(entry, "InstallLocation")[0]))
                except OSError:
                    continue
    return found


def find_folder() -> str:
    """The folder SimHub is installed in, or "" when SimHub is not on this PC."""
    candidates = [os.environ.get("SIMHUB_INSTALL_PATH", "")]
    candidates += _registry_folders()
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            candidates.append(os.path.join(base, "SimHub"))
    for folder in candidates:
        folder = (folder or "").strip().strip('"')
        if folder and os.path.isfile(os.path.join(folder, SIMHUB_EXE)):
            return os.path.normpath(folder)
    return ""


def plugin_source() -> str:
    """The plugin file that came with this copy of SpeakerWeave, or "" when it has none."""
    candidates = []
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        candidates += [os.path.join(base, "simhub", PLUGIN_FILE),
                       os.path.join(os.path.dirname(sys.executable), "simhub", PLUGIN_FILE)]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates.append(os.path.join(root, "packaging", "simhub", "out", PLUGIN_FILE))
    return next((c for c in candidates if os.path.isfile(c)), "")


def _digest(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return ""


def plugin_state(folder: str = None, source: str = None) -> str:
    """ "no simhub", "no plugin" (this copy has none to give), "missing", "old" or "current"."""
    folder = find_folder() if folder is None else folder
    if not folder:
        return "no simhub"
    target = os.path.join(folder, PLUGIN_FILE)
    source = plugin_source() if source is None else source
    if not os.path.isfile(target):
        return "missing" if source else "no plugin"
    if source and _digest(source) != _digest(target):
        return "old"
    return "current"


def simhub_running() -> bool:
    if sys.platform != "win32":
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {SIMHUB_EXE}", "/NH"],
                             capture_output=True, text=True, timeout=5,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return SIMHUB_EXE.lower() in out.lower()


def install(folder: str, source: str) -> tuple:
    """Copies the plugin into SimHub's folder. Returns (done, asked_windows, message).

    SimHub usually lives under Program Files, which only an administrator may change,
    so Windows is then asked to do the copy (its "allow changes" question). That copy
    finishes after this returns, asked_windows is then True: check plugin_state again
    a few seconds later.
    """
    if not folder or not source:
        return False, False, "SimHub or the plugin file was not found."
    if simhub_running():
        return False, False, "Close SimHub first (right click its tray icon, Exit), then press Install again."
    target = os.path.join(folder, PLUGIN_FILE)
    try:
        with open(source, "rb") as src, open(target, "wb") as dst:
            dst.write(src.read())
        return True, False, "The plugin is in SimHub. Start SimHub and say yes when it asks to enable it."
    except PermissionError:
        pass
    except OSError as exc:
        return False, False, f"Could not copy the plugin ({exc.strerror or exc})."
    if sys.platform != "win32":
        return False, False, "Could not copy the plugin: no permission."
    import ctypes
    args = f'/c copy /y "{source}" "{target}"'
    code = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", args, None, 0)
    if int(code) <= 32:
        return False, False, "Windows did not allow the copy, so the plugin is not installed."
    return False, True, "Waiting for Windows to copy the plugin..."


def remove_plugin(folder: str = None) -> tuple:
    """Takes the SpeakerWeave plugin out of SimHub. Returns (done, message).
    Like install, Windows is asked when SimHub's folder needs administrator rights."""
    folder = find_folder() if folder is None else folder
    target = os.path.join(folder, PLUGIN_FILE) if folder else ""
    if not target or not os.path.isfile(target):
        return True, ""
    if simhub_running():
        return False, "SimHub is running, so its SpeakerWeave plugin stays. Close SimHub and delete " \
                      f"{target} by hand."
    try:
        os.remove(target)
        return True, "The SpeakerWeave plugin was taken out of SimHub."
    except PermissionError:
        pass
    except OSError as exc:
        return False, f"The SimHub plugin could not be removed ({exc.strerror or exc})."
    if sys.platform != "win32":
        return False, "The SimHub plugin could not be removed: no permission."
    import ctypes
    code = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", f'/c del /f /q "{target}"', None, 0)
    if int(code) <= 32:
        return False, f"Windows did not allow it, so the SimHub plugin stays in {folder}."
    return True, "Windows was asked to take the SpeakerWeave plugin out of SimHub."
