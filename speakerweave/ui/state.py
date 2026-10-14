"""Shared state of the running app: the setup, the engine and what is selected."""
from __future__ import annotations

import math
import os

from PySide6.QtCore import QObject, QStandardPaths, QTimer, Signal

from .. import backend, default_output, hidden, sounds, windefault
from ..engine import Engine
from ..model import OFF, Project, is_shaker, is_sub, speaker_position
from ..rgb import RgbController
from ..settings import AppSettings
from ..winvolume import VolumeFollower


def config_dir() -> str:
    base = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".speakerweave")
    os.makedirs(base, exist_ok=True)
    return base


def documents_dir() -> str:
    path = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
    return path or os.path.expanduser("~")


def setups_dir(settings=None) -> str:
    """Where the Open and Save windows for setups start: the folder last used, else
    "SpeakerWeave setups" in Documents. Never the folder SpeakerWeave runs from, which
    Windows does not let it write to when it is installed under Program Files."""
    last = getattr(settings, "last_setup_folder", "") if settings is not None else ""
    if last and os.path.isdir(last):
        return last
    path = os.path.join(documents_dir(), "SpeakerWeave setups")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return documents_dir()
    return path


def remember_setup_folder(settings, path: str) -> None:
    if path:
        settings.last_setup_folder = os.path.dirname(os.path.abspath(path))


class AppState(QObject):
    structureChanged = Signal()     # devices, roles, mode or routing changed
    selectionChanged = Signal()
    speakerChanged = Signal(str)    # sound settings of one speaker changed
    layoutChanged = Signal()        # something moved on the room map
    runningChanged = Signal()
    problems = Signal(list)         # things to tell the user after starting
    notice = Signal(str)            # short status bar message
    devicesScanned = Signal()
    masterChanged = Signal()        # volume or mute changed
    settingsChanged = Signal()
    inputChanged = Signal()         # Listen to was changed by the app itself
    metronomeChanged = Signal()     # the metronome was switched on or off, or changed
    windowsVolumeChanged = Signal()  # the Windows volume of the device listened to changed

    def __init__(self, profile_path: str = ""):
        super().__init__()
        self.last_path = os.path.join(config_dir(), "last setup.json")
        self.settings_path = os.path.join(config_dir(), "settings.json")
        self.settings = AppSettings.load(self.settings_path)
        self.project = self._load_initial(profile_path)
        hidden.pull_hidden(self.settings, self.project)     # outputs hidden on this PC
        self.engine = Engine(self.project)
        self.engine.rebuild()
        self.runner = backend.AudioRunner(self.project, self.engine)
        self.rgb = RgbController(self.project, self.engine.level)
        self.winvol = VolumeFollower(self._windows_volume)
        self.sel_dev = ""
        self.sel_spk = ""
        self.eq_clipboard = None
        self.outputs: list = []
        self.inputs: list = []
        self.loopbacks: list = []
        self.scan_error = ""
        self.new_outputs: set = set()       # outputs that appeared since the app started
        self._known_outputs = None
        self._temporary_run = False         # sound was started only to play a test sound
        self._restarting = False
        self._clicks_fixed = False          # Easy sync chose the clicking speakers itself
        self.saving_blocked = False         # SpeakerWeave's own data was just removed: write nothing
        self.last_errors: list = []         # problems from the last start, for the Errors page
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self.save_now)
        self._restart_timer = QTimer(self)
        self._restart_timer.setSingleShot(True)
        self._restart_timer.setInterval(350)
        self._restart_timer.timeout.connect(self._restart)

    # ------------------------------------------------------------ profiles
    def _load_initial(self, path: str) -> Project:
        for candidate in (path, self.last_path):
            if candidate and os.path.exists(candidate):
                try:
                    return Project.load(candidate)
                except Exception:
                    pass
        return Project()

    def save_now(self) -> None:
        if self.saving_blocked:
            return
        try:
            self.project.save(self.last_path)
        except Exception:
            pass

    def save_soon(self) -> None:
        self._save_timer.start()

    def save_settings(self) -> None:
        if self.saving_blocked:
            return
        try:
            self.settings.save(self.settings_path)
        except Exception:
            pass
        self.settingsChanged.emit()

    def replace_project(self, project: Project) -> None:
        was_running = self.runner.running
        self.stop(keep_windows=was_running)
        if hidden.pull_hidden(self.settings, project):
            self.save_settings()
        self.project = project
        self.engine.project = project
        self.follow_windows_volume()
        self.runner.project = project
        self.rgb.project = project
        self.engine.rebuild()
        self.sel_dev = self.sel_spk = ""
        self.structureChanged.emit()
        self.selectionChanged.emit()
        self.save_soon()
        if was_running:
            self.start()

    # ------------------------------------------------------------ selection
    def select(self, dev_id: str = "", spk_id: str = "") -> None:
        if (dev_id, spk_id) != (self.sel_dev, self.sel_spk):
            self.sel_dev, self.sel_spk = dev_id, spk_id
            self.selectionChanged.emit()

    def selected_device(self):
        return self.project.find_device(self.sel_dev) if self.sel_dev else None

    def selected_speaker(self):
        if not self.sel_spk:
            return None, None
        return self.project.find_speaker(self.sel_spk)

    # ------------------------------------------------------------ change notes
    def touch_speaker(self, spk_id: str) -> None:
        """EQ, volume, delay or frequency limits of one speaker changed."""
        self.engine.update_speaker(spk_id)
        self.speakerChanged.emit(spk_id)
        self.save_soon()

    def touch_routing(self) -> None:
        """Roles, mute, solo, mode or mixing options changed."""
        self.engine.rebuild()
        self.structureChanged.emit()
        self.save_soon()

    def touch_layout(self) -> None:
        self.layoutChanged.emit()
        self.save_soon()

    def touch_streams(self) -> None:
        """Devices were added, removed or switched on or off, or the input changed."""
        self.follow_windows_volume()
        self.engine.rebuild()
        if self.runner.running:
            self._restart_timer.start()     # a moment later, so a dragged slider restarts once
        self.structureChanged.emit()
        self.save_soon()

    def _restart(self) -> None:
        if self.runner.running:
            temporary = self._temporary_run
            self._restarting = True             # a restart keeps the metronome going
            try:
                self.stop(keep_windows=True)
                self.start(temporary=temporary)
            finally:
                self._restarting = False

    # ------------------------------------------------------------ audio
    def start(self, temporary: bool = False) -> None:
        """temporary: the sound is started only to play a test sound. Then nothing
        but that test sound is played, so no other speaker makes a noise, and
        Windows is left alone. Otherwise Windows is pointed at the device
        SpeakerWeave listens to for as long as the sound runs."""
        self.follow_windows_volume()
        claim_problem = "" if temporary else self.make_default_output()
        if self.project.input_kind == "test":
            claim_problem = ""                  # the test signal needs no virtual device
        self._temporary_run = temporary
        self.engine.test_only = temporary
        errors = self.runner.start()
        if not self.runner.running and not temporary:
            self.restore_default_output()       # never leave Windows playing into nothing
        self.last_errors = list(errors) + ([claim_problem] if claim_problem else [])
        self.problems.emit(list(self.last_errors))
        self.runningChanged.emit()

    def stop(self, keep_windows: bool = False) -> None:
        """Stops the sound. Windows goes back to the output it used before, so
        the PC is never left playing into a device nobody listens to."""
        was_temporary = self._temporary_run
        self._temporary_run = False
        self.engine.test_only = False
        if not self._restarting and self.engine.metronome_on:
            self._clicks_fixed = False
            self.engine.stop_metronome()
            self.metronomeChanged.emit()
        if self.runner.running:
            self.runner.stop()
            self.runningChanged.emit()
            if not was_temporary and not keep_windows:
                self.restore_default_output()
        self.last_errors = []
        self.problems.emit([])

    def test_sound_choices(self) -> list[tuple[str, str]]:
        """(kind, name) of every test sound: the built in ones, then the user's own."""
        out = [("noise", "Short noise"), ("sweep", "Sweep from low to high")]
        for i, entry in enumerate(self.settings.test_sounds):
            if entry:
                out.append((f"custom{i + 1}", entry["name"]))
        return out

    def identify(self, spk_id: str, kind: str = "noise") -> None:
        """Plays a test sound on one speaker only. If the sound is stopped, it is
        started just for the test (playing nothing else) and stopped again
        afterwards. kind is "noise", "sweep" or "custom1" to "custom5"."""
        dev, spk = self.project.find_speaker(spk_id)
        if spk is None:
            return
        if not dev.enabled:
            self.notice.emit(f"{dev.title} is switched off. Tick it in the list first.")
            return
        entry = None
        if kind.startswith("custom"):
            slot = int(kind[6:] or 0) - 1
            entry = self.settings.test_sounds[slot] if 0 <= slot < len(self.settings.test_sounds) else {}
            if not entry:
                self.notice.emit("That test sound place is empty. Add a sound on the Settings page.")
                return
        if not self.runner.running:
            self.start(temporary=True)
            if not self.runner.running:
                return
        samples = None
        if entry:
            samples = sounds.load(entry, config_dir(), self.engine.sr)
            if samples is None or len(samples) == 0:
                self.notice.emit(f"The sound \"{entry['name']}\" is missing. Choose it again on the "
                                 f"Settings page.")
                self._end_temporary_run()
                return
            seconds = len(samples) / self.engine.sr
            self.engine.identify(spk_id, seconds, "custom", samples)
            what = f"\"{entry['name']}\""
        else:
            seconds = 4.0 if kind == "sweep" else 1.5
            self.engine.identify(spk_id, seconds, kind)
            what = "a sweep from low to high" if kind == "sweep" else "a short noise"
        self.notice.emit(f"Playing {what} on {spk.name} of {dev.title}")
        if self._temporary_run:
            QTimer.singleShot(int(seconds * 1000) + 400, self._end_temporary_run)

    def _end_temporary_run(self) -> None:
        if self._temporary_run and self.runner.running and not self.engine.identifying \
                and not self.engine.metronome_on:
            self._temporary_run = False
            self.stop()

    # ------------------------------------------------------------ Windows volume
    def windows_volume_device(self) -> str:
        """The output whose Windows volume the speakers follow: the device listened to."""
        p = self.project
        if not self.settings.follow_windows_volume or p.input_kind != "loopback":
            return ""
        return p.input_name.replace(" [Loopback]", "")

    def follow_windows_volume(self) -> None:
        name = self.windows_volume_device()
        if not name:
            self.engine.windows_gain = 1.0
        self.winvol.follow(name)
        self.windowsVolumeChanged.emit()

    def _windows_volume(self, gain: float, muted: bool, _percent: float) -> None:
        # called from the follower's own thread: the engine reads this once per block
        if not self.windows_volume_device():
            self.engine.windows_gain = 1.0
        else:
            self.engine.windows_gain = 0.0 if muted else gain
        self.windowsVolumeChanged.emit()

    def windows_volume_text(self) -> str:
        """ "" at full volume, else how Windows has it, for the window to show."""
        w = self.winvol
        if not self.windows_volume_device() or not w.following:
            return ""
        if w.muted:
            return "Windows muted"
        return "" if w.percent >= 99.5 else f"Windows {w.percent:.0f}%"

    # ------------------------------------------------------------ metronome
    def metronome_targets(self, mode: str) -> list:
        """[(speaker id, low)] that click, in the order they take turns: round the room
        from front left, clockwise, then the subwoofers and shakers."""
        p = self.project
        found = []
        for dev in p.devices:
            if not dev.enabled:
                continue
            for spk in dev.speakers:
                if spk.role == OFF or spk.mute or spk.channel >= dev.channels:
                    continue
                if mode == "selected" and spk.id != self.sel_spk:
                    continue
                low = is_sub(spk.role) or is_shaker(spk.role) or (spk.lp_on and spk.lp_freq <= 250)
                x, y = speaker_position(dev, spk)
                angle = math.degrees(math.atan2(x - p.listener_x, -(y - p.listener_y)))
                found.append((low, (angle + 45.0) % 360.0, spk.id))
        found.sort()
        return [(spk_id, low) for low, _angle, spk_id in found]

    def start_metronome(self, mode: str = "", bpm: int = 0) -> bool:
        """Steady clicks on the speakers instead of the PC sound, to hear whether they
        are in time with each other. Starts the sound for it when it is stopped."""
        s = self.settings
        if mode:
            s.metronome_mode = mode
        if bpm:
            s.metronome_bpm = int(min(240, max(30, bpm)))
        targets = self.metronome_targets(s.metronome_mode)
        if not targets:
            self.notice.emit("Select a speaker on the map first." if s.metronome_mode == "selected"
                             else "Tick an output with speakers first.")
            if self.engine.metronome_on:
                self.stop_metronome()
            self.metronomeChanged.emit()
            return False
        if not self.runner.running:
            self.start(temporary=True)
            if not self.runner.running:
                self.metronomeChanged.emit()
                return False
        self.engine.set_metronome(s.metronome_bpm, targets, s.metronome_mode == "turns")
        self.save_settings()
        self.metronomeChanged.emit()
        return True

    def play_clicks(self, targets: list, bpm: int = 0) -> bool:
        """Clicks on exactly these speakers ([(speaker id, low)]), for Easy sync."""
        if not self.runner.running:
            self.start(temporary=True)
            if not self.runner.running:
                return False
        self._clicks_fixed = True
        self.engine.set_metronome(bpm or self.settings.metronome_bpm, targets, False)
        self.metronomeChanged.emit()
        return True

    def stop_metronome(self) -> None:
        self._clicks_fixed = False
        self.engine.stop_metronome()
        self.metronomeChanged.emit()
        self._end_temporary_run()

    def refresh_metronome(self) -> None:
        """Speakers, roles or the selection changed while it ticks."""
        if self.engine.metronome_on and not self._clicks_fixed:
            s = self.settings
            targets = self.metronome_targets(s.metronome_mode)
            if targets:
                self.engine.set_metronome(s.metronome_bpm, targets, s.metronome_mode == "turns")

    def set_master(self, db: float) -> None:
        self.project.master_db = float(min(max(db, -60.0), 12.0))
        self.engine.rebuild()
        self.masterChanged.emit()
        self.save_soon()

    def set_muted(self, muted: bool) -> None:
        self.project.muted = bool(muted)
        self.engine.rebuild()
        self.masterChanged.emit()
        self.save_soon()

    def scan_devices(self) -> None:
        """Read the list of sound devices from the system."""
        was_running = self.runner.running
        if was_running:
            self.runner.stop()
        self.scan_error = ""
        try:
            backend.refresh()
            self.outputs = backend.list_outputs()
            self.inputs = backend.list_inputs()
            names = {o.name for o in self.outputs}
            if self._known_outputs is not None:
                self.new_outputs |= names - self._known_outputs
            self.new_outputs &= names
            self._known_outputs = names
        except Exception as exc:
            self.outputs, self.inputs = [], []
            self.scan_error = f"Could not read the sound devices: {exc}"
        try:
            self.loopbacks = backend.list_loopbacks()
        except Exception:
            self.loopbacks = []
        self.devicesScanned.emit()
        if was_running:
            self.start()

    def input_choices(self) -> list[tuple[str, str, str]]:
        """(text, kind, name) for the input selector."""
        out = [("Test signal (steps through every channel)", "test", "")]
        for d in self.loopbacks:
            clean = d.name.replace(" [Loopback]", "")
            out.append((f"Everything this PC plays on: {clean}", "loopback", d.name))
        for d in self.inputs:
            out.append((f"Recording device: {d.name}", "device", d.name))
        return out

    # ------------------------------------------------------------ Windows default output
    def prepare_source(self) -> tuple[str, str]:
        """With the setting on and Listen to still on the test signal, switches
        it over to the virtual device. Returns (device Windows should play into,
        problem)."""
        if not self.settings.default_output:
            return "", ""
        device, loopback, problem = default_output.plan(self.project, self.loopbacks)
        if problem or not device:
            return "", problem
        if (self.project.input_kind, self.project.input_name) != ("loopback", loopback):
            self.project.input_kind, self.project.input_name = "loopback", loopback
            self.engine.rebuild()
            self.structureChanged.emit()
            self.save_soon()
            self.inputChanged.emit()
        return device, ""

    def ensure_surround(self, device: str) -> str:
        """Sets the virtual device to 7.1 when it is still on stereo, so games
        send real surround sound. Returns a problem to show, or ""."""
        if not self.settings.auto_surround or not windefault.supported():
            return ""
        from ..speaker_library import recognise
        entry = recognise(device)
        if entry is None or entry.category != "virtual":
            return ""
        try:
            dev_id = windefault.find(device)
            if dev_id and windefault.channel_count(dev_id) < 8:
                windefault.set_channels(dev_id, 8)
                self.notice.emit(f"{device} is now set to 7.1, so games send surround sound.")
        except Exception as exc:
            return f"Could not set {device} to 7.1 ({exc}). Set it in the Sound control panel."
        return ""

    def make_default_output(self) -> str:
        """With the setting on: makes Windows play into the device SpeakerWeave
        listens to (switching Listen to over to a virtual device first when it
        is on the test signal). Returns a problem to show, or ""."""
        device, problem = self.prepare_source()
        if problem or not device:
            return problem
        surround_problem = self.ensure_surround(device)
        try:
            changed, problem = default_output.apply(self.settings, device)
        except Exception as exc:
            return f"Windows did not accept {device} as its default output ({exc})."
        self.save_settings()
        if changed:
            self.notice.emit(f"Windows now plays into {device}. SpeakerWeave passes it on to your "
                             f"speakers.")
        return problem or surround_problem

    def restore_default_output(self) -> None:
        if not self.settings.managed_output:
            return
        try:
            if self.settings.restore_output:
                default_output.restore(self.settings)
            else:
                self.settings.managed_output, self.settings.previous_outputs = "", {}
        except Exception:
            pass
        self.save_settings()

    def shutdown(self) -> None:
        self.winvol.stop()
        self.restore_default_output()
        self.runner.stop()
        self.rgb.disconnect()
        self.save_now()
