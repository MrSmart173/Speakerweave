"""Shared state of the running app: the setup, the engine and what is selected."""
from __future__ import annotations

import math
import os
import sys
import time

from PySide6.QtCore import QObject, QStandardPaths, QTimer, Signal

from .. import backend, cable, default_output, fun, hidden, sounds, speaker_library, windefault
from ..engine import Engine
from ..model import OFF, Project, is_shaker, is_sub, speaker_position
from ..mics import MicMeters, is_microphone
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


def can_write(folder: str) -> bool:
    """True if SpeakerWeave can really create a file in this existing folder. A folder can
    exist and still say no: anything under Program Files, or Documents when Windows
    Security's ransomware protection (Controlled folder access) does not know the app."""
    if not folder or not os.path.isdir(folder):
        return False
    probe = os.path.join(folder, f".speakerweave write test {os.getpid()}.tmp")
    try:
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def own_setups_dir() -> str:
    """SpeakerWeave's own setups folder in AppData, which Windows always lets it write to."""
    path = os.path.join(config_dir(), "Setups")
    os.makedirs(path, exist_ok=True)
    return path


def _in_app_folder(folder: str) -> bool:
    """True for the folder SpeakerWeave is installed in, or one inside it."""
    from .. import paths
    if not paths.is_built():
        return False
    app = os.path.normcase(os.path.abspath(os.path.dirname(sys.executable)))
    here = os.path.normcase(os.path.abspath(folder))
    return here == app or here.startswith(app + os.sep)


def setups_dir(settings=None) -> str:
    """Where the Open and Save windows for setups start: the folder last used, else
    "SpeakerWeave setups" in Documents, else SpeakerWeave's own folder in AppData. Only a
    folder SpeakerWeave can really write to, never the folder it is installed in."""
    last = getattr(settings, "last_setup_folder", "") if settings is not None else ""
    if last and not _in_app_folder(last) and can_write(last):
        return last
    path = os.path.join(documents_dir(), "SpeakerWeave setups")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    if can_write(path):
        return path
    return own_setups_dir()


def remember_setup_folder(settings, path: str) -> None:
    """The next Open or Save window starts in this setup's folder, if it can be written to."""
    folder = os.path.dirname(os.path.abspath(path)) if path else ""
    if folder and not _in_app_folder(folder) and can_write(folder):
        settings.last_setup_folder = folder


SWEEP_FRONT_DEG = 75.0      # "sides" sweeps the front speakers: no further round than this (side ones sit at 90)


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
    sweepChanged = Signal()         # a speaker sweep started or ended
    windowsVolumeChanged = Signal()  # the Windows volume of the device listened to changed
    funChanged = Signal()           # a sound effect for fun was switched on or off, or changed

    def __init__(self, profile_path: str = ""):
        super().__init__()
        self.last_path = os.path.join(config_dir(), "last setup.json")
        self.settings_path = os.path.join(config_dir(), "settings.json")
        self.settings = AppSettings.load(self.settings_path)
        self.project = self._load_initial(profile_path)
        hidden.pull_hidden(self.settings, self.project)     # outputs hidden on this PC
        self._fix_layouts(self.project)
        self.engine = Engine(self.project)
        self.engine.rebuild()
        self.runner = backend.AudioRunner(self.project, self.engine)
        self.rgb = RgbController(self.project, self.engine.level)
        self.winvol = VolumeFollower(self._windows_volume)
        self.mic_meters = MicMeters()
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
        self.sweep_kind = ""                # the speaker sweep playing: "circle" or "sides"
        self._sweep_number = 0
        self._sweep_timer = QTimer(self)
        self._sweep_timer.setInterval(200)
        self._sweep_timer.timeout.connect(self._watch_sweep)
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
        # sound effects for fun: {effect key: when a timed run ends (time.monotonic), 0: on
        # until switched off}. They start off every time SpeakerWeave opens.
        self.fun_on: dict = {}
        self._fun_timers: dict = {}
        self._fun_save = QTimer(self)
        self._fun_save.setSingleShot(True)
        self._fun_save.setInterval(800)
        self._fun_save.timeout.connect(self.save_settings)

    # ------------------------------------------------------------ profiles
    def _fix_layouts(self, project: Project) -> None:
        """Outputs saved before SpeakerWeave knew their real speakers get them now: a
        Logitech G560 that Windows offers as 7.1 becomes its two speakers and subwoofer."""
        if self.settings.apply_library:
            speaker_library.fix_layouts(project)

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
        self._fix_layouts(project)
        self.project = project
        self.mic_meters.follow(project.mics, self.inputs)
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

    # ------------------------------------------------------------ microphones
    def microphones(self) -> list:
        """The PC's recording devices that are microphones (not VB-CABLE or Stereo Mix)."""
        return [d for d in self.inputs if is_microphone(d.name)]

    def add_mic(self, name: str):
        mic = self.project.add_mic(name)
        self.mics_changed()
        return mic

    def remove_mic(self, mic_id: str) -> None:
        self.project.remove_mic(mic_id)
        self.mics_changed()

    def mics_changed(self) -> None:
        """Microphones were added, removed, ticked or unticked."""
        self.mic_meters.follow(self.project.mics, self.inputs)
        self.structureChanged.emit()
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
        self._play_test([spk_id], kind, entry, f"{spk.name} of {dev.title}")

    def playing_speakers(self) -> list:
        """The ids of every speaker that plays: its output ticked, a role, not muted and, while
        any speaker is soloed, soloed itself."""
        p = self.project
        any_solo = any(s.solo for d, s in p.all_speakers() if d.enabled)
        return [s.id for d, s in p.all_speakers()
                if d.enabled and s.role != OFF and not s.mute and (s.solo or not any_solo)
                and s.channel < d.channels]

    def identify_all(self, kind: str = "noise") -> None:
        """A test sound on every speaker that plays at once (nothing is selected)."""
        ids = self.playing_speakers()
        if not ids:
            self.notice.emit("No speaker plays: tick an output and give its speakers a role first.")
            return
        entry = None
        if kind.startswith("custom"):
            slot = int(kind[6:] or 0) - 1
            entry = self.settings.test_sounds[slot] if 0 <= slot < len(self.settings.test_sounds) else {}
            if not entry:
                self.notice.emit("That test sound place is empty. Add a sound on the Settings page.")
                return
        self._play_test(ids, kind, entry, f"all {len(ids)} speakers" if len(ids) > 1 else "your speaker")

    def _play_test(self, ids: list, kind: str, entry, where: str) -> None:
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
            self.engine.identify(ids, seconds, "custom", samples)
            what = f"\"{entry['name']}\""
        else:
            seconds = 4.0 if kind == "sweep" else 1.5
            self.engine.identify(ids, seconds, kind)
            what = "a sweep from low to high" if kind == "sweep" else "a short noise"
        self.notice.emit(f"Playing {what} on {where}")
        if self._temporary_run:
            QTimer.singleShot(int(seconds * 1000) + 400, self._end_temporary_run)

    def _end_temporary_run(self) -> None:
        if self._temporary_run and self.runner.running and not self.engine.identifying \
                and not self.engine.metronome_on and not self.engine.sweeping:
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

    # ------------------------------------------------------------ speaker sweeps
    def sweep_targets(self, kind: str) -> list:
        """[(speaker id, angle)] of the speakers a sweep visits: every speaker except the
        subwoofers and shakers, and for "sides" only those in front of you (all of them
        when fewer than two are in front)."""
        p = self.project
        found = []
        for dev in p.devices:
            if not dev.enabled:
                continue
            for spk in dev.speakers:
                if spk.role == OFF or spk.mute or spk.channel >= dev.channels \
                        or is_sub(spk.role) or is_shaker(spk.role):
                    continue
                x, y = speaker_position(dev, spk)
                found.append((spk.id, math.degrees(math.atan2(x - p.listener_x, -(y - p.listener_y)))))
        if kind == "sides":
            front = [t for t in found if abs(t[1]) <= SWEEP_FRONT_DEG]
            if len(front) >= 2:
                found = front
        return found

    def start_sweep(self, kind: str) -> bool:
        """A sound that moves round the speakers ("circle") or from left to right across
        the front ("sides"). Starts the sound for it when it is stopped."""
        targets = self.sweep_targets(kind)
        if not targets:
            self.notice.emit("Tick an output with speakers first.")
            return False
        if self.engine.metronome_on:
            self.stop_metronome()
        if not self.runner.running:
            self.start(temporary=True)
            if not self.runner.running:
                return False
        self._sweep_number += 1
        self.sweep_kind = kind
        self.engine.set_sweep(kind, targets, self._sweep_number)
        self._sweep_timer.start()
        self.sweepChanged.emit()
        return True

    def stop_sweep(self) -> None:
        self.engine.stop_sweep()
        self._sweep_ended()

    def _watch_sweep(self) -> None:
        if not self.engine.sweeping:
            self._sweep_ended()

    def _sweep_ended(self) -> None:
        self._sweep_timer.stop()
        self.sweep_kind = ""
        self.engine.stop_sweep()
        self.sweepChanged.emit()
        self._end_temporary_run()

    def start_metronome(self, mode: str = "", bpm: int = 0) -> bool:
        """Steady clicks on the speakers instead of the PC sound, to hear whether they
        are in time with each other. Starts the sound for it when it is stopped."""
        s = self.settings
        if self.engine.sweeping:                    # one test at a time
            self.engine.stop_sweep()
            self._sweep_timer.stop()
            self.sweep_kind = ""
            self.sweepChanged.emit()
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

    TEST_BOOST_RANGE = (-12.0, 12.0)

    def boost_tests(self, db) -> None:
        """Test sounds this many dB louder (or quieter), for as long as a test panel is open.
        None: back to normal. The amount is remembered for the next time."""
        if db is None:
            self.engine.test_gain = 1.0
            return
        lo, hi = self.TEST_BOOST_RANGE
        db = float(min(max(float(db), lo), hi))
        if self.settings.test_boost_db != db:
            self.settings.test_boost_db = db
            self.save_settings()
        self.engine.test_gain = 10.0 ** (db / 20.0)

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
        self.loopbacks = self._read_loopbacks()
        self._follow_renamed_input()
        self.mic_meters.follow(self.project.mics, self.inputs)
        self.devicesScanned.emit()
        if was_running:
            self.start()

    def _read_loopbacks(self) -> list:
        """The outputs that can be listened in on. Right after the virtual device is renamed
        Windows can leave it out for a moment, so when the device listened to is VB-CABLE
        and Windows has it, the list is read again until it is there (a second at most)."""
        p = self.project
        tries = 1
        if p.input_kind == "loopback" and cable.is_cable_input(p.input_name) and windefault.supported():
            try:
                tries = 6 if cable.find()[0] else 1
            except Exception:
                tries = 1
        found = []
        for attempt in range(tries):
            try:
                found = backend.list_loopbacks()
            except Exception:
                found = []
            if cable.pick(p.input_name, [d.name for d in found]) or attempt == tries - 1:
                break
            time.sleep(0.2)
        return found

    def _follow_renamed_input(self) -> None:
        """The virtual device was renamed (CABLE Input is now SpeakerWeave Virtual Speaker
        output, or back): Listen to follows it, also in setups saved before."""
        p = self.project
        if p.input_kind != "loopback" or not p.input_name:
            return
        now = cable.pick(p.input_name, [d.name for d in self.loopbacks])
        if now and now != p.input_name:
            p.input_name = now
            self.engine.rebuild()
            self.save_soon()
            self.inputChanged.emit()

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

    # ------------------------------------------------------------ delay
    LOW_RATE = 48000

    def set_listen_rate(self, rate: int = LOW_RATE) -> str:
        """Sets the virtual device SpeakerWeave listens to to this sample rate (keeping its
        channels) and starts the sound again. Returns a problem, or ""."""
        listened = self.project.input_name.replace(" [Loopback]", "")
        if not windefault.supported():
            return "Only Windows has sound devices to set up."
        dev_id = windefault.find(listened)
        if not dev_id and cable.is_cable_input(listened):
            dev_id = cable.find()[0]
        if not dev_id:
            return f"Windows has no output called {listened} right now."
        was = self.runner.running
        if was:
            self.stop(keep_windows=True)
        try:
            windefault.set_channels(dev_id, windefault.channel_count(dev_id) or 8, rate=int(rate))
        except OSError as exc:
            problem = f"Windows did not take the new rate ({exc})."
        else:
            problem = ""
        self.scan_devices()
        if was:
            self.start()
        return problem

    def trim_common_delay(self) -> float:
        """Takes the delay every speaker shares off all of them. Returns the milliseconds."""
        from ..model import remove_common_delay
        taken = remove_common_delay(self.project)
        if taken:
            self.touch_routing()
            self.structureChanged.emit()
        return taken

    # ------------------------------------------------------------ sound effects for fun
    def fun_amount(self, key: str) -> float:
        saved = self.settings.fun.get(key, {})
        return fun.clean_amount(key, saved.get("amount", fun.BY_KEY[key].default))

    def fun_seconds(self, key: str) -> float:
        saved = self.settings.fun.get(key, {})
        return fun.clean_seconds(key, saved.get("seconds", fun.BY_KEY[key].seconds))

    def _fun_entry(self, key: str) -> dict:
        return self.settings.fun.setdefault(key, {"amount": self.fun_amount(key),
                                                  "seconds": self.fun_seconds(key)})

    def set_fun_amount(self, key: str, value: float) -> None:
        self._fun_entry(key)["amount"] = fun.clean_amount(key, value)
        self._push_fun()
        self._fun_save.start()
        self.funChanged.emit()

    def set_fun_seconds(self, key: str, value: float) -> None:
        self._fun_entry(key)["seconds"] = fun.clean_seconds(key, value)
        self._fun_save.start()
        self.funChanged.emit()

    def set_fun(self, key: str, on: bool, seconds: float = 0.0) -> None:
        """Switches an effect on (for good, or for seconds) or off."""
        if key not in fun.BY_KEY:
            return
        timer = self._fun_timers.pop(key, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        if on:
            self.fun_on[key] = time.monotonic() + seconds if seconds > 0 else 0.0
            if seconds > 0:
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.timeout.connect(lambda k=key: self.set_fun(k, False))
                timer.start(int(seconds * 1000))
                self._fun_timers[key] = timer
        else:
            self.fun_on.pop(key, None)
        self._push_fun()
        self.funChanged.emit()

    def toggle_fun(self, key: str) -> bool:
        """On becomes off, off (or a timed run) becomes on for good. Returns on."""
        on = key not in self.fun_on or self.fun_on[key] > 0
        self.set_fun(key, on)
        return on

    def fun_for(self, key: str, seconds: float = 0.0) -> float:
        """On for a while (the effect's own time unless seconds is given). Pressing it again
        starts the time again. Returns the seconds."""
        seconds = seconds or self.fun_seconds(key)
        self.set_fun(key, True, seconds)
        return seconds

    def fun_left(self, key: str) -> float:
        """Seconds left of a timed run, 0 when it is on for good or off."""
        end = self.fun_on.get(key, 0.0)
        return max(0.0, end - time.monotonic()) if end else 0.0

    def stop_fun(self) -> None:
        for key in list(self.fun_on):
            self.set_fun(key, False)

    def _push_fun(self) -> None:
        self.engine.set_fun({key: self.fun_amount(key) for key in self.fun_on})

    def shutdown(self) -> None:
        if self._fun_save.isActive():
            self._fun_save.stop()
            self.save_settings()
        self.mic_meters.close_all()
        self.winvol.stop()
        self.restore_default_output()
        self.runner.stop()
        self.rgb.disconnect()
        self.save_now()
