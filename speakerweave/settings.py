"""Settings of the app itself (not of a speaker setup), kept in settings.json."""
from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict, dataclass, field, fields

SETUP_SLOTS = 4
TEST_SOUNDS = 5


SETTINGS_VERSION = 2


@dataclass
class AppSettings:
    version: int = SETTINGS_VERSION
    start_with_windows: bool = False
    start_in_tray: bool = False         # open hidden, only the tray icon shows
    start_sound: bool = True            # press Start automatically when the app opens
    close_to_tray: bool = True          # the window's close button keeps the sound running
    check_updates: bool = True
    show_meters: bool = True
    watch_devices: bool = True          # notice sound outputs being plugged in
    apply_library: bool = True          # fill in presets for recognised outputs
    remote_enabled: bool = False        # Stream Deck and other apps may send actions
    remote_port: int = 47800
    remote_token: str = field(default_factory=lambda: secrets.token_hex(4))
    controllers_enabled: bool = True    # listen to game controllers, wheels and button boxes
    bindings: list = field(default_factory=list)          # see controls.py
    setup_slots: list = field(default_factory=lambda: [""] * SETUP_SLOTS)
    tray_hint_shown: bool = False
    theme: str = "midnight"             # a preset name from ui/theme.py, or "custom"
    custom_colors: dict = field(default_factory=dict)      # bg, panel, line, text, accent
    test_sounds: list = field(default_factory=lambda: [{} for _ in range(TEST_SOUNDS)])
    # make the device SpeakerWeave listens to the Windows default output when it opens
    default_output: bool = True
    restore_output: bool = True         # and switch back to the old one when it quits
    previous_outputs: dict = field(default_factory=dict)  # {role: device id} before we changed it
    managed_output: str = ""            # the device id SpeakerWeave made the default
    auto_surround: bool = True          # set the virtual device to 7.1 so games send surround
    name_virtual_device: bool = True    # call VB-CABLE's output "SpeakerWeave Virtual Speaker output"
    follow_windows_volume: bool = True  # the Windows volume (keys, mouse wheel) sets the speakers' too
    show_levels: bool = True            # the level meters under the room map
    show_now_playing: bool = True       # what is playing on the PC, under the room map
    media_popup: bool = True            # a popup in the corner when a new song or video starts
    simhub_link: bool = True            # answer the SpeakerWeave plugin in SimHub
    game_setups: dict = field(default_factory=dict)   # SimHub game name -> setup file ("" = no game)
    games_seen: list = field(default_factory=list)    # games the SimHub plugin has reported
    tour_done: bool = False             # the first run tour was finished or skipped
    update_note_seen: str = ""          # the newer version whose note was closed with Later
    last_setup_folder: str = ""         # where a setup was last opened or saved
    metronome_bpm: int = 100
    metronome_mode: str = "together"    # together, turns or selected
    # outputs the person hid in the output list, by name: see hidden.py
    hidden_outputs: dict = field(default_factory=dict)
    # sound effects for fun: {effect key: {"amount": slider value, "seconds": play for}}
    fun: dict = field(default_factory=dict)

    def save(self, path: str) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2)
        os.replace(tmp, path)

    @staticmethod
    def load(path: str) -> "AppSettings":
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return AppSettings()
        names = {f.name for f in fields(AppSettings)}
        settings = AppSettings(**{k: v for k, v in data.items() if k in names})
        if int(data.get("version", 1) or 1) < 2:
            # from settings version 2 on, the sound simply runs while SpeakerWeave is open
            settings.start_sound = True
        settings.version = SETTINGS_VERSION
        if not isinstance(settings.bindings, list):
            settings.bindings = []
        slots = list(settings.setup_slots or []) + [""] * SETUP_SLOTS
        settings.setup_slots = [str(s or "") for s in slots[:SETUP_SLOTS]]
        from .sounds import clean_slots
        settings.test_sounds = clean_slots(settings.test_sounds)
        if not isinstance(settings.custom_colors, dict):
            settings.custom_colors = {}
        if not isinstance(settings.previous_outputs, dict):
            settings.previous_outputs = {}
        if not isinstance(settings.game_setups, dict):
            settings.game_setups = {}
        settings.game_setups = {str(k): str(v or "") for k, v in settings.game_setups.items()}
        settings.metronome_bpm = int(min(240, max(30, int(settings.metronome_bpm or 100))))
        if settings.metronome_mode not in ("together", "turns", "selected"):
            settings.metronome_mode = "together"
        from .hidden import clean as clean_hidden
        settings.hidden_outputs = clean_hidden(settings.hidden_outputs)
        if not isinstance(settings.games_seen, list):
            settings.games_seen = []
        settings.games_seen = [str(g) for g in settings.games_seen if g][:40]
        from .fun import clean_settings
        settings.fun = clean_settings(settings.fun)
        return settings
