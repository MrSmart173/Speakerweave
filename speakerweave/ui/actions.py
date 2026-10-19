"""Carries out the actions that keys, controller buttons and remote links trigger."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from ..controls import VOLUME_STEP_DB, label_of, next_mode
from ..model import SURROUND_SWITCHABLE, Project


class ActionRunner(QObject):
    requested = Signal(str)             # may be emitted from any thread
    done = Signal(str, str)             # action key, short message

    def __init__(self, window, state):
        super().__init__(window)
        self.window = window
        self.state = state
        self._input_before_test = ("", "")
        self.requested.connect(self.run)

    @Slot(str)
    def run(self, action: str) -> None:
        state, win, p = self.state, self.window, self.state.project
        message = ""
        if action == "toggle_sound":
            win._toggle_running()
            message = "Sound started" if state.runner.running else "Sound stopped"
        elif action in ("volume_up", "volume_down"):
            step = VOLUME_STEP_DB if action == "volume_up" else -VOLUME_STEP_DB
            if p.muted:
                state.set_muted(False)
            state.set_master(p.master_db + step)
            message = f"Volume {p.master_db:+.0f} dB"
        elif action == "mute":
            state.set_muted(not p.muted)
            message = "Muted" if p.muted else "Unmuted"
        elif action in ("next_mode", "prev_mode"):
            current = (p.mode, p.surround_rear if p.mode in SURROUND_SWITCHABLE else False)
            mode, rear = next_mode(current, 1 if action == "next_mode" else -1)
            p.set_mode(mode, rear=rear)
            state.touch_routing()
            message = f"Mode {p.mode_text()}"
        elif action == "toggle_bass":
            p.bass_redirect = not p.bass_redirect
            state.touch_routing()
            message = "Bass to the subwoofer " + ("on" if p.bass_redirect else "off")
        elif action == "toggle_upmix":
            p.upmix = not p.upmix
            state.touch_routing()
            message = "Fill every speaker " + ("on" if p.upmix else "off")
        elif action == "toggle_metronome":
            if state.engine.metronome_on:
                state.stop_metronome()
                message = "Metronome off"
            else:
                message = "Metronome on" if state.start_metronome() else ""
        elif action == "test_signal":
            if p.input_kind == "test":
                kind, name = self._input_before_test
                if kind:
                    p.input_kind, p.input_name = kind, name
            else:
                self._input_before_test = (p.input_kind, p.input_name)
                p.input_kind, p.input_name = "test", ""
            state.touch_streams()
            win._load_inputs()
            message = "Test signal " + ("on" if p.input_kind == "test" else "off")
        elif action == "toggle_lights":
            if state.rgb.connected:
                state.rgb.disconnect()
                message = "Lights off"
            else:
                message = "Lights on" if state.rgb.connect() else "Lights: " + state.rgb.error
            win.lights_panel.refresh_status()
        elif action == "show_window":
            win.toggle_visible()
        elif action.startswith("slot_"):
            message = self._load_slot(int(action.split("_")[1]))
        elif action.startswith("fun:") or action.startswith("fun_for:"):
            from ..fun import BY_KEY
            key = action.split(":", 1)[1]
            effect = BY_KEY.get(key)
            if effect is not None:
                if action.startswith("fun_for:"):
                    seconds = state.fun_for(key)
                    message = f"{effect.name} for {seconds:g} s"
                else:
                    message = f"{effect.name} " + ("on" if state.toggle_fun(key) else "off")
        elif action == "fun_stop":
            state.stop_fun()
            message = "Every sound effect off"
        elif action.startswith("mute_output:"):
            dev = p.find_device(action.split(":", 1)[1])
            if dev is not None:
                mute = not all(s.mute for s in dev.speakers)
                for spk in dev.speakers:
                    spk.mute = mute
                state.touch_routing()
                message = f"{dev.title} " + ("muted" if mute else "unmuted")
        if message:
            state.notice.emit(message)
            self.done.emit(action, message)

    def _load_slot(self, number: int) -> str:
        slots = self.state.settings.setup_slots
        path = slots[number - 1] if 0 < number <= len(slots) else ""
        if not path:
            return f"Setup slot {number} is empty. Fill it on the Controls page."
        try:
            project = Project.load(path)
        except Exception as exc:
            return f"Setup slot {number} could not be loaded ({exc})"
        self.state.replace_project(project)
        self.window._load_top()
        return f"Loaded setup slot {number}"

    def label(self, action: str) -> str:
        return label_of(action, self.state.project)
