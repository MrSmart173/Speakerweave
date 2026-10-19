"""Data model: surround modes, speaker roles, devices, speakers, profiles."""
from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass, field, asdict, fields
from typing import Optional

# ---------------------------------------------------------------- roles / modes

OFF = "OFF"

ROLE_NAMES = {
    "FL": "Front left",
    "FR": "Front right",
    "FC": "Centre",
    "LFE": "Subwoofer (LFE)",
    "LFE2": "Subwoofer 2",
    "LFE3": "Subwoofer 3",
    "LFE4": "Subwoofer 4",
    "SL": "Side left",
    "SR": "Side right",
    "BL": "Rear left",
    "BR": "Rear right",
    "BC": "Rear centre",
    "SHAKER": "Bass shaker",
    OFF: "Off (silent)",
}

# Short tags drawn on the room map.
ROLE_SHORT = {
    "FL": "FL", "FR": "FR", "FC": "C", "LFE": "SUB", "SL": "SL", "SR": "SR",
    "BL": "RL", "BR": "RR", "BC": "RC", "LFE2": "SUB2", "LFE3": "SUB3", "LFE4": "SUB4",
    "SHAKER": "SHK", OFF: "",
}

# A bass shaker (ButtKicker, tactile transducer) is not a position of any mode,
# so it can be used in every mode. It feels the game's bass and any effects sent
# to it from an extra source such as SimHub.
SHAKER = "SHAKER"


def is_shaker(role: str) -> bool:
    return role == SHAKER

# Every subwoofer position plays the same thing: the bass channel plus, if
# switched on, the bass of all other channels.
SUB_ROLES = ("LFE", "LFE2", "LFE3", "LFE4")


def is_sub(role: str) -> bool:
    return role in SUB_ROLES

# Ideal direction of each role as seen from the listener. 0 = straight ahead,
# positive = clockwise (to the right). The subwoofer has no direction.
ROLE_ANGLES = {
    "FL": -30.0, "FR": 30.0, "FC": 0.0,
    "SL": -90.0, "SR": 90.0,
    "BL": -150.0, "BR": 150.0, "BC": 180.0,
}

ROLE_COLORS = {
    "FL": "#4da3ff", "FR": "#ff6b6b", "FC": "#f5d76e", "LFE": "#b388ff",
    "SL": "#4dd0c8", "SR": "#ff9f5a", "BL": "#69d17a", "BR": "#f48fb1",
    "BC": "#c0c7d1", "LFE2": "#9a70f0", "LFE3": "#c7a4ff", "LFE4": "#8459d6", "SHAKER": "#9ccc65",
    OFF: "#5b6370",
}

# name -> (description, roles)
MODES = {
    "2.0": ("Stereo", ["FL", "FR"]),
    "2.1": ("Stereo + sub", ["FL", "FR", "LFE"]),
    "3.0": ("Front three", ["FL", "FR", "FC"]),
    "3.1": ("Front three + sub", ["FL", "FR", "FC", "LFE"]),
    "4.0": ("Quad", ["FL", "FR", "SL", "SR"]),
    "4.1": ("Quad + sub", ["FL", "FR", "LFE", "SL", "SR"]),
    "5.0": ("Surround", ["FL", "FR", "FC", "SL", "SR"]),
    "5.1": ("Surround + sub", ["FL", "FR", "FC", "LFE", "SL", "SR"]),
    "6.0": ("Three stereo pairs", ["FL", "FR", "SL", "SR", "BL", "BR"]),
    "6.1": ("Surround + rear centre + sub", ["FL", "FR", "FC", "LFE", "SL", "SR", "BC"]),
    "7.0": ("Full surround", ["FL", "FR", "FC", "SL", "SR", "BL", "BR"]),
    "7.1": ("Full surround + sub", ["FL", "FR", "FC", "LFE", "SL", "SR", "BL", "BR"]),
}

# A mode made of any positions you pick. Its positions are kept in Project.custom_roles.
CUSTOM = "custom"
# Modes with one surround pair, which can be beside you (side) or behind you (rear).
SURROUND_SWITCHABLE = ("4.0", "4.1", "5.0", "5.1")
# The order positions are listed and offered in.
POSITION_ORDER = ["FL", "FR", "FC", "LFE", "LFE2", "LFE3", "LFE4", "SL", "SR", "BL", "BR", "BC"]
MAIN_POSITIONS = ["FL", "FC", "FR", "SL", "SR", "BL", "BC", "BR"]
_PAIR_SWAP = {"SL": "BL", "SR": "BR", "BL": "SL", "BR": "SR"}


def mode_label(mode: str, rear: bool = False) -> str:
    if mode == CUSTOM:
        return "Custom"
    text = f"{mode}   {MODES[mode][0]}"
    if mode in SURROUND_SWITCHABLE:
        text += ", rear pair RL RR" if rear else ", side pair SL SR"
    return text


def mode_choices() -> list:
    """(mode, rear) for every entry of the mode list, in order."""
    out = []
    for mode in MODES:
        out.append((mode, False))
        if mode in SURROUND_SWITCHABLE:
            out.append((mode, True))
    out.append((CUSTOM, False))
    return out


def standard_mode_for(roles) -> Optional[tuple]:
    """The standard mode (and side or rear choice) with exactly these positions, if any."""
    wanted = set(roles)
    for mode, rear in mode_choices():
        if mode == CUSTOM:
            continue
        probe = Project(mode=mode, surround_rear=rear)
        if set(probe.mode_roles()) == wanted:
            return mode, rear
    return None

# What each channel of the *incoming* audio means (Windows channel order).
SOURCE_LAYOUTS = {
    "mono": ["FC"],
    "stereo": ["FL", "FR"],
    "quad": ["FL", "FR", "BL", "BR"],
    "5.1": ["FL", "FR", "FC", "LFE", "SL", "SR"],
    "7.1": ["FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"],
}


def source_layout_for(channels: int, preferred: str = "auto") -> list[str]:
    """Roles of each incoming channel. Extra channels are ignored (OFF)."""
    if preferred != "auto" and preferred in SOURCE_LAYOUTS:
        roles = list(SOURCE_LAYOUTS[preferred])
    else:
        by_count = {1: "mono", 2: "stereo", 4: "quad", 6: "5.1", 8: "7.1"}
        best = max((c for c in by_count if c <= max(1, channels)), default=1)
        roles = list(SOURCE_LAYOUTS[by_count[best]])
    roles = roles[:channels]
    return roles + [OFF] * (channels - len(roles))


DEFAULT_CHANNEL_ROLES = ["FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"]
DEFAULT_CHANNEL_NAMES = ["Left", "Right", "Centre", "Sub", "Rear L", "Rear R", "Side L", "Side R"]

MAX_DEVICE_CHANNELS = 8

SUB_HP_HZ = 10.0
SUB_LP_HZ = 75.0

ISO_BANDS = [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]


def _id() -> str:
    return uuid.uuid4().hex[:10]


# ---------------------------------------------------------------- dataclasses

@dataclass
class EQBand:
    kind: str = "peak"          # peak | lowshelf | highshelf
    freq: float = 1000.0
    gain_db: float = 0.0
    q: float = 1.41
    enabled: bool = True


def default_eq() -> list[EQBand]:
    bands = [EQBand("peak", f) for f in ISO_BANDS]
    bands[0].kind = "lowshelf"
    bands[0].q = 0.71
    bands[-1].kind = "highshelf"
    bands[-1].q = 0.71
    return bands


@dataclass
class Speaker:
    """One output channel of a device = one physical speaker."""
    id: str = field(default_factory=_id)
    name: str = "Speaker"
    channel: int = 0
    role: str = OFF
    gain_db: float = 0.0
    delay_ms: float = 0.0
    mute: bool = False
    solo: bool = False
    invert: bool = False
    # frequency limits
    hp_on: bool = False
    hp_freq: float = 80.0
    hp_slope: int = 24          # dB per octave: 12, 24 or 48
    lp_on: bool = False
    lp_freq: float = 120.0
    lp_slope: int = 24
    eq_on: bool = True
    eq: list[EQBand] = field(default_factory=default_eq)
    # position in the room in metres (used when the device is "external")
    x: float = 0.0
    y: float = 0.0
    # RGB
    rgb_device: str = ""        # OpenRGB device name, "" = none
    rgb_zone: str = ""          # zone of that device, "" = the whole device
    rgb_mode: str = "pulse"     # static | pulse | vu | rainbow
    rgb_color: str = ""         # "" = use the role colour
    range_preset: str = ""      # speaker type preset last applied (see presets.py)

    def apply_sub_preset(self) -> None:
        self.hp_on, self.hp_freq, self.hp_slope = True, SUB_HP_HZ, 24
        self.lp_on, self.lp_freq, self.lp_slope = True, SUB_LP_HZ, 24
        self.range_preset = "sub"

    def apply_shaker_preset(self) -> None:
        self.hp_on, self.hp_freq, self.hp_slope = True, 10.0, 24
        self.lp_on, self.lp_freq, self.lp_slope = True, 80.0, 48
        self.range_preset = "shaker"

    def clear_band_limit(self) -> None:
        self.hp_on = False
        self.lp_on = False
        self.range_preset = "full"


@dataclass
class Route:
    """One channel of an extra source and the speakers it is sent to."""
    channel: int = 0
    label: str = ""                     # your own name for it: "Tyres", "Spotter" ...
    targets: list = field(default_factory=list)     # speaker ids
    gain_db: float = 0.0


@dataclass
class ExtraSource:
    """A second sound coming in next to the PC's sound, for example the effects
    SimHub's ShakeIt plays into a virtual device, or a spotter app that Windows
    sends to its own device. Each of its channels goes to the speakers chosen."""
    id: str = field(default_factory=_id)
    name: str = ""                      # the device, as under Listen to
    kind: str = "loopback"              # loopback | device
    label: str = "Extra sound"
    enabled: bool = True
    routes: list = field(default_factory=list)       # Route per channel

    def route(self, channel: int) -> "Route":
        found = next((r for r in self.routes if r.channel == channel), None)
        if found is None:
            found = Route(channel=channel)
            self.routes.append(found)
            self.routes.sort(key=lambda r: r.channel)
        return found


@dataclass
class Device:
    """One sound output of the computer (a TV over HDMI, a sound card, ...)."""
    id: str = field(default_factory=_id)
    name: str = ""              # system name, used to find it again
    label: str = ""             # your own name for it
    channels: int = 2
    enabled: bool = True
    kind: str = "builtin"       # builtin = speakers attached to the unit (they move with it)
                                # external = loose speakers, each on its own spot
    x: float = 0.0              # centre of the unit, metres
    y: float = -1.5
    rotation: float = 0.0       # degrees, clockwise
    width: float = 1.0          # metres, distance between its outer speakers
    trim_ms: float = 0.0        # extra delay for this whole device
    model: str = ""             # speaker library entry (see speaker_library.py), "" = none
    gain_db: float = 0.0
    speakers: list[Speaker] = field(default_factory=list)
    # True once the loose positions of the speakers (Speaker.x, .y) were set, so
    # detaching them again brings each one back to where it was
    free_placed: bool = False
    # the speakers the hardware really has, when Windows offers more channels than that:
    # "2.1" (two speakers and a subwoofer, such as a Logitech G560 offered as 7.1) or ""
    layout: str = ""

    @property
    def title(self) -> str:
        return self.label or self.name


@dataclass
class Mic:
    """A microphone placed on the room map, around the speakers: where it is, and which of
    the PC's recording devices it is."""
    id: str = field(default_factory=_id)
    name: str = ""                      # the recording device, as Windows names it
    label: str = ""                     # your own name for it
    enabled: bool = True
    x: float = 0.0                      # metres, like the speakers
    y: float = 0.0

    @property
    def title(self) -> str:
        return self.label or self.name


@dataclass
class Project:
    mode: str = "5.1"
    input_kind: str = "test"    # device | loopback | test
    input_name: str = ""
    source_layout: str = "auto"
    blocksize: int = 480
    buffer_ms: float = 0.0      # extra safety buffer. 0: as little delay as the devices allow
    # the lowest delay: each output is used by SpeakerWeave alone (WASAPI exclusive mode),
    # past the Windows sound mixer, which saves that mixer's own buffer on every output
    exclusive_outputs: bool = False
    upmix: bool = True
    # while no subwoofer plays, a speaker's "Nothing below" cut is left out: the lows it
    # would hand to a subwoofer have nowhere else to go, and cutting them sounds thin
    keep_lows: bool = True
    bass_redirect: bool = True
    bass_redirect_db: float = -6.0
    lfe_to_mains: bool = True
    master_db: float = 0.0       # the volume slider at the top: full volume to start with
    muted: bool = False         # everything silent (Mute action)
    room_w: float = 5.0
    room_h: float = 5.0
    map_zoom: float = 1.0       # how far the room map is zoomed in (1: the whole room)
    map_auto: bool = True       # the map zooms itself to keep everything in view
    listener_x: float = 0.0
    listener_y: float = 0.5
    rgb_host: str = "127.0.0.1"
    rgb_port: int = 6742
    rgb_enabled: bool = False
    autostart: bool = False     # start the sound as soon as the app opens
    auto_face: bool = True      # units turn to face the listener while dragged
    mirror: bool = False        # moving one speaker moves its partner the mirrored way
    check_updates: bool = True  # look for a newer version when the app opens
    surround_rear: bool = False  # 4.x and 5.x: the surround pair is behind (rear), not beside
    custom_roles: list = field(default_factory=lambda: ["FL", "FR", "FC", "LFE", "SL", "SR"])
    shaker_game_on: bool = True     # bass shakers feel the game's bass, not only the effects
    shaker_game_db: float = -3.0
    devices: list[Device] = field(default_factory=list)
    extra_sources: list[ExtraSource] = field(default_factory=list)
    mics: list[Mic] = field(default_factory=list)       # microphones placed on the map
    setup_version: int = 2      # 2: the safety buffer defaults to 0 ms

    # ---- lookups
    def mode_roles(self) -> list[str]:
        if self.mode == CUSTOM:
            return [r for r in POSITION_ORDER if r in self.custom_roles]
        roles = list(MODES.get(self.mode, MODES["2.0"])[1])
        if self.surround_rear and self.mode in SURROUND_SWITCHABLE:
            roles = [{"SL": "BL", "SR": "BR"}.get(r, r) for r in roles]
        return roles

    def mode_text(self) -> str:
        if self.mode == CUSTOM:
            mains = [r for r in self.mode_roles() if not is_sub(r)]
            subs = len([r for r in self.mode_roles() if is_sub(r)])
            # written the usual way: 4.2 is four positions and two subwoofers
            return f"Custom {len(mains)}.{subs}   " + " ".join(ROLE_SHORT[r] for r in mains)
        return mode_label(self.mode, self.surround_rear)

    def all_speakers(self):
        for dev in self.devices:
            for spk in dev.speakers:
                yield dev, spk

    def roles_in_use(self, playing_only: bool = False) -> list[str]:
        """Roles of the current mode that at least one switched on speaker plays
        (plus the bass shaker, which every mode has). playing_only leaves out muted
        speakers, and with a speaker on solo every speaker that is not."""
        present = {s.role for d, s in self.all_speakers() if d.enabled and s.channel < d.channels
                   and (not playing_only or self.speaker_plays(s))}
        used = [r for r in self.mode_roles() if r in present]
        return used + ([SHAKER] if SHAKER in present else [])

    def speaker_plays(self, spk) -> bool:
        """Not muted, and not silenced by another speaker's solo."""
        any_solo = any(s.solo for d, s in self.all_speakers() if d.enabled)
        return not spk.mute and (spk.solo or not any_solo)

    def has_playing_sub(self) -> bool:
        return any(is_sub(s.role) and self.speaker_plays(s)
                   for d, s in self.all_speakers() if d.enabled and s.channel < d.channels)

    def role_choices(self) -> list[str]:
        """Every role a speaker can be given in this mode."""
        return self.mode_roles() + [SHAKER, OFF]

    def roles_missing(self) -> list[str]:
        used = self.roles_in_use()
        return [r for r in self.mode_roles() if r not in used]

    def find_speaker(self, spk_id: str):
        for dev, spk in self.all_speakers():
            if spk.id == spk_id:
                return dev, spk
        return None, None

    def find_device(self, dev_id: str) -> Optional[Device]:
        return next((d for d in self.devices if d.id == dev_id), None)

    def device_by_name(self, name: str) -> Optional[Device]:
        return next((d for d in self.devices if d.name == name), None)

    # ---- editing
    # ---- microphones
    def add_mic(self, name: str) -> Mic:
        """A microphone joins the map, near you: the first just in front, the next ones
        round you, so none sits on another."""
        n = len(self.mics)
        angle = math.radians((0.0, 45.0, -45.0, 90.0, -90.0, 135.0, -135.0, 180.0)[n % 8])
        mic = Mic(name=name, x=round(self.listener_x + MIC_START_M * math.sin(angle), 3),
                  y=round(self.listener_y - MIC_START_M * math.cos(angle), 3))
        self.mics.append(mic)
        return mic

    def find_mic(self, mic_id: str) -> Optional[Mic]:
        return next((m for m in self.mics if m.id == mic_id), None)

    def remove_mic(self, mic_id: str) -> None:
        self.mics = [m for m in self.mics if m.id != mic_id]

    def add_device(self, name: str, channels: int) -> Device:
        n = len(self.devices)
        channels = max(1, min(int(channels), MAX_DEVICE_CHANNELS))
        dev = Device(name=name, label="", channels=channels)
        self._place_new(dev, n)
        roles = self.mode_roles()
        for ch in range(channels):
            role = DEFAULT_CHANNEL_ROLES[ch] if ch < len(DEFAULT_CHANNEL_ROLES) else OFF
            if role not in roles:
                role = OFF
            cname = DEFAULT_CHANNEL_NAMES[ch] if ch < len(DEFAULT_CHANNEL_NAMES) else f"Ch {ch + 1}"
            spk = Speaker(name=cname, channel=ch, role=role)
            if is_sub(role):
                spk.apply_sub_preset()
            dev.speakers.append(spk)
        self.devices.append(dev)
        place_external_defaults(dev)
        dev.free_placed = False         # loose spots are taken from the unit when first detached
        return dev

    def _place_new(self, dev: Device, n: int) -> None:
        if dev.channels > 2:
            # a surround system: a shape around the listener, front speakers ahead
            dev.x, dev.y = self.listener_x, self.listener_y
            dev.width, dev.rotation = 2 * SHAPE_RADIUS, 0.0
            return
        dev.x, dev.y = self._front_slot(n)

    def _front_slot(self, n: int) -> tuple:
        """Fans new devices out in front of the listener so they do not overlap."""
        slots = [0.0, -1.3, 1.3, -2.1, 2.1]
        return slots[n % len(slots)], self.listener_y - 2.0 + 0.45 * (n // len(slots))

    def fit_layout(self, dev: Device, layout: str) -> bool:
        """An output whose hardware has fewer speakers than Windows offers channels: a
        headset or 2.0 speakers offered as 7.1 (layout "2.0"), or a 2.1 system such as a
        Logitech G560 offered as 7.1 (layout "2.1"). Only its real speakers stay, in
        front of you instead of in a surround shape, and its other channels stay silent.
        Returns True if the speakers changed."""
        if layout not in REAL_SPEAKERS:
            return False
        keep = layout_channels(dev.channels, layout)
        if dev.channels <= 2 or (dev.layout == layout and sorted(s.channel for s in dev.speakers) == keep):
            if dev.channels > 2:
                dev.layout = layout
            return False
        roles = self.mode_roles()
        by_channel = {s.channel: s for s in dev.speakers}
        speakers = []
        for (name, want), ch in zip(REAL_SPEAKERS[layout], keep):
            spk = by_channel.get(ch) or Speaker(name=name, channel=ch, role=OFF)
            spk.name = name
            # a role left as it came (silent, or the usual one for that channel) becomes the
            # speaker's real one. A role you chose yourself stays.
            usual = DEFAULT_CHANNEL_ROLES[ch] if ch < len(DEFAULT_CHANNEL_ROLES) else OFF
            if spk.role in (OFF, usual) and spk.role != want:
                self.set_role(spk, want if want in roles else OFF)
            speakers.append(spk)
        dev.speakers = speakers
        dev.layout = layout
        # in front of you like any pair of speakers, a subwoofer on the floor beside them
        index = self.devices.index(dev) if dev in self.devices else len(self.devices)
        dev.x, dev.y = self._front_slot(index)
        dev.width, dev.rotation = PAIR_WIDTH, 0.0
        spots = ((-PAIR_WIDTH / 2, 0.0), (PAIR_WIDTH / 2, 0.0), (-PAIR_WIDTH, 0.3))
        for spk, (dx, dy) in zip(speakers, spots):
            spk.x, spk.y = round(dev.x + dx, 3), round(dev.y + dy, 3)
        dev.kind = "external" if layout == TWO_ONE else "builtin"
        dev.free_placed = True
        return True

    def use_all_channels(self, dev: Device) -> bool:
        """Undoes fit_layout: every channel Windows offers gets its speaker again (chosen
        by you, so it is not fitted again). Returns True if speakers were added."""
        had = dev.layout
        dev.layout = ALL_CHANNELS
        if not had or had == ALL_CHANNELS:
            return False
        channels, dev.channels = dev.channels, 0
        return self.set_device_channels(dev, channels)

    def set_device_channels(self, dev: Device, channels: int) -> bool:
        """Windows now offers a different number of channels for this output
        (for example the sound card was set from stereo to 5.1). Adds or removes
        speakers to match. Returns True if anything changed."""
        channels = max(1, min(int(channels), MAX_DEVICE_CHANNELS))
        wanted = layout_channels(channels, dev.layout)
        if channels == dev.channels and sorted(s.channel for s in dev.speakers) == wanted:
            return False
        was_shape = is_shape(dev)
        roles = self.mode_roles()
        used = {s.role for _, s in self.all_speakers()}
        if dev.layout in REAL_SPEAKERS and channels > 2:
            # the same real speakers, on the channels Windows now gives them
            layout, dev.layout = dev.layout, ""
            dev.channels = channels
            dev.speakers = [s for s in dev.speakers if s.channel in wanted]
            self.fit_layout(dev, layout)
            return True
        dev.speakers = [s for s in dev.speakers if s.channel in wanted]
        have = {s.channel for s in dev.speakers}
        for ch in wanted:
            if ch in have:
                continue
            role = DEFAULT_CHANNEL_ROLES[ch] if ch < len(DEFAULT_CHANNEL_ROLES) else OFF
            if role not in roles or (role in used and not is_sub(role)):
                role = OFF
            cname = DEFAULT_CHANNEL_NAMES[ch] if ch < len(DEFAULT_CHANNEL_NAMES) else f"Ch {ch + 1}"
            spk = Speaker(name=cname, channel=ch, role=role)
            if is_sub(role):
                spk.apply_sub_preset()
            dev.speakers.append(spk)
        dev.speakers.sort(key=lambda s: s.channel)
        dev.channels = channels
        if is_shape(dev) and not was_shape:
            self._place_new(dev, 0)
            dev.kind = "builtin"            # a new surround system starts in its shape
            dev.free_placed = False
        elif dev.kind == "external":
            for spk in dev.speakers:        # a new speaker starts where its shape puts it
                if spk.x == 0.0 and spk.y == 0.0:
                    kind, dev.kind = dev.kind, "builtin"
                    spk.x, spk.y = speaker_position(dev, spk)
                    dev.kind = kind
        return True

    def fit_mode_to(self, dev: Device) -> bool:
        """When a surround system has more channels than the mode has positions,
        switches to the mode that matches it (6 channels: 5.1, 8: 7.1) and gives
        its silent speakers their usual roles. Returns True if the mode changed."""
        mains = len([r for r in self.mode_roles() if not is_sub(r)])
        target = {6: ("5.1", True), 8: ("7.1", False)}.get(dev.channels)
        if target is None or mains >= dev.channels - 1:
            return False
        self.set_mode(target[0], rear=target[1])
        roles = self.mode_roles()
        for spk in dev.speakers:
            if spk.role == OFF and spk.channel < len(DEFAULT_CHANNEL_ROLES):
                role = DEFAULT_CHANNEL_ROLES[spk.channel]
                if role in roles:
                    self.set_role(spk, role)
        return True

    def remove_device(self, dev_id: str) -> None:
        self.devices = [d for d in self.devices if d.id != dev_id]

    def set_role(self, spk: Speaker, role: str) -> None:
        """Change a role. Labelling a speaker as the subwoofer limits it to
        low notes, taking the label away removes that limit again."""
        was = spk.role
        spk.role = role
        if is_shaker(role) and not is_shaker(was):
            spk.apply_shaker_preset()
        elif is_sub(role) and not is_sub(was):
            spk.apply_sub_preset()
        elif (is_sub(was) or is_shaker(was)) and not (is_sub(role) or is_shaker(role)):
            spk.clear_band_limit()

    def set_mode(self, mode: str, rear: Optional[bool] = None, custom=None) -> None:
        """Switch mode. Speakers whose position the new mode does not have fall
        silent. When only the surround pair moves (side to rear or back), its
        speakers follow it instead."""
        before = set(self.mode_roles())
        self.mode = mode if mode in MODES or mode == CUSTOM else "2.0"
        if rear is not None:
            self.surround_rear = bool(rear)
        if custom is not None:
            self.custom_roles = [r for r in POSITION_ORDER if r in custom]
        roles = self.mode_roles()
        for _, spk in self.all_speakers():
            if spk.role == OFF or spk.role in roles or is_shaker(spk.role):
                continue
            moved = _PAIR_SWAP.get(spk.role)
            if moved and moved in roles and moved not in before:
                self.set_role(spk, moved)
            elif is_sub(spk.role) and "LFE" in roles:
                self.set_role(spk, "LFE")
            else:
                self.set_role(spk, OFF)

    # ---- persistence
    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @staticmethod
    def from_json(text: str) -> "Project":
        return _project_from_dict(json.loads(text))

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.to_json())

    @staticmethod
    def load(path: str) -> "Project":
        with open(path, "r", encoding="utf-8") as fh:
            return Project.from_json(fh.read())


def _build(cls, data: dict):
    """Build a dataclass from a dict, ignoring unknown keys (forward compatible)."""
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


def device_from_dict(d: dict) -> Device:
    """An output as saved in a setup file (see asdict), back as a Device."""
    speakers = []
    for s in d.get("speakers", []):
        s = dict(s)
        s["eq"] = [_build(EQBand, b) for b in s.get("eq", [])]
        speakers.append(_build(Speaker, s))
    d = dict(d)
    d["speakers"] = speakers
    if "free_placed" not in d:
        d["free_placed"] = d.get("kind") == "external"     # older setups
    return _build(Device, d)


def _project_from_dict(data: dict) -> Project:
    devices = [device_from_dict(d) for d in data.get("devices", [])]
    data = dict(data)
    if "setup_version" not in data and data.get("buffer_ms") == 60.0:
        data["buffer_ms"] = 0.0     # the old default: setups get the new lowest delay as well
    data["devices"] = devices
    sources = []
    for src in data.get("extra_sources", []) or []:
        src = dict(src)
        src["routes"] = [_build(Route, r) for r in src.get("routes", []) if isinstance(r, dict)]
        sources.append(_build(ExtraSource, src))
    data["extra_sources"] = sources
    data["mics"] = [_build(Mic, m) for m in data.get("mics", []) or [] if isinstance(m, dict)]
    proj = _build(Project, data)
    custom = [r for r in POSITION_ORDER if r in (proj.custom_roles or [])]
    proj.custom_roles = custom if any(not is_sub(r) for r in custom) else ["FL", "FR"]
    if proj.mode not in MODES and proj.mode != CUSTOM:
        proj.mode = "2.0"
    return proj


# ---------------------------------------------------------------- geometry

def speaker_offset(dev: Device, spk: Speaker) -> float:
    """Position of a built in speaker along the unit, from -0.5 to +0.5."""
    n = max(1, len(dev.speakers))
    if n == 1:
        return 0.0
    if n > 2:
        # two speakers and a subwoofer: the speakers at the ends, the subwoofer in the middle
        mains = _mains(dev)
        if spk not in mains or len(mains) < 2:
            return 0.0
        return mains.index(spk) / (len(mains) - 1) - 0.5
    return spk.channel / (n - 1) - 0.5


MIC_START_M = 0.6           # a new microphone starts this far from you


# Device.layout: the speakers the hardware really has, when Windows offers more channels
TWO_ZERO = "2.0"            # two speakers, or a headset
TWO_ONE = "2.1"             # two speakers and a subwoofer
ALL_CHANNELS = "all"        # every channel Windows offers, as you chose
REAL_SPEAKERS = {
    TWO_ZERO: (("Left", "FL"), ("Right", "FR")),
    TWO_ONE: (("Left", "FL"), ("Right", "FR"), ("Sub", "LFE")),
}
PAIR_WIDTH = 0.9            # metres between the two speakers of a fitted output, to start with


def layout_channels(channels: int, layout: str = "") -> list:
    """The channels of an output that have a speaker, in order. Two speakers: the first
    two channels. A 2.1 system: its left speaker, right speaker and subwoofer, wherever
    Windows puts them (5.1 and 7.1 put the subwoofer on the fourth channel, an output
    with three channels on the third)."""
    if layout == TWO_ZERO and channels > 2:
        return [0, 1]
    if layout == TWO_ONE and channels >= 4:
        return [0, 1, 3]
    return list(range(channels))


def _mains(dev: Device) -> list:
    """The speakers of an output that are not subwoofers, in channel order."""
    return sorted((s for s in dev.speakers if not is_sub(shape_role(s))), key=lambda s: s.channel)


SHAPE_RADIUS = 1.6          # metres from the middle of a surround system to its speakers


def is_shape(dev: Device) -> bool:
    """Outputs with more than two speakers besides subwoofers (5.1, 7.1 systems) are
    shown as a shape around the listener instead of a bar. Two speakers and a
    subwoofer (2.1) are not."""
    return len(dev.speakers) > 2 and len(_mains(dev)) > 2


def shape_role(spk: Speaker) -> str:
    if spk.role in ROLE_ANGLES or is_sub(spk.role):
        return spk.role
    if spk.channel < len(DEFAULT_CHANNEL_ROLES):
        return DEFAULT_CHANNEL_ROLES[spk.channel]
    return OFF


def shape_offset(dev: Device, spk: Speaker) -> tuple[float, float]:
    """Where a speaker of a surround system sits relative to the middle of the
    system, before turning: its role's direction, the subwoofer off to the left."""
    r = max(dev.width, MIN_WIDTH) / 2.0
    role = shape_role(spk)
    if is_sub(role):
        subs = [s for s in dev.speakers if is_sub(shape_role(s))]
        k = subs.index(spk) if spk in subs else 0
        return -r * 1.18 - 0.38 * k, -r * 0.5
    if role in ROLE_ANGLES:
        a = math.radians(ROLE_ANGLES[role])
        same = [s for s in dev.speakers if shape_role(s) == role]
        shift = (same.index(spk) - (len(same) - 1) / 2.0) * 0.32 if spk in same else 0.0
        return r * math.sin(a) + shift * math.cos(a), -r * math.cos(a) + shift * math.sin(a)
    a = 2 * math.pi * spk.channel / max(1, len(dev.speakers))
    return 0.55 * r * math.sin(a), 0.55 * r * math.cos(a)


def speaker_position(dev: Device, spk: Speaker) -> tuple[float, float]:
    """Where a speaker is in the room, in metres."""
    if dev.kind == "external":
        return spk.x, spk.y
    a = math.radians(dev.rotation)
    if is_shape(dev):
        ox, oy = shape_offset(dev, spk)
        return (dev.x + ox * math.cos(a) - oy * math.sin(a),
                dev.y + ox * math.sin(a) + oy * math.cos(a))
    off = speaker_offset(dev, spk) * dev.width
    return dev.x + off * math.cos(a), dev.y + off * math.sin(a)


def place_external_defaults(dev: Device) -> None:
    """Put the separate speakers where the attached ones would be."""
    kind = dev.kind
    dev.kind = "builtin"
    for spk in dev.speakers:
        spk.x, spk.y = speaker_position(dev, spk)
    dev.kind = kind
    dev.free_placed = True


def set_attached(dev: Device, attached: bool) -> None:
    """Attached: the speakers sit on the unit (or in its surround shape) and
    move with it. Detached: each speaker goes back to the spot it had the last
    time it was loose (the first time: right where it was drawn)."""
    if attached:
        dev.kind = "builtin"
        return
    if not dev.free_placed:
        place_external_defaults(dev)
    dev.kind = "external"


def speaker_angle(proj: Project, dev: Device, spk: Speaker) -> float:
    """Direction of a speaker from the listener. 0 = ahead (up on the map)."""
    x, y = speaker_position(dev, spk)
    dx, dy = x - proj.listener_x, y - proj.listener_y
    return math.degrees(math.atan2(dx, -dy))


def speaker_distance(proj: Project, dev: Device, spk: Speaker) -> float:
    x, y = speaker_position(dev, spk)
    return math.hypot(x - proj.listener_x, y - proj.listener_y)


MIN_WIDTH = 0.1


def unit_ends(dev: Device):
    """The two outer speakers of a unit with built in speakers, or (None, None)."""
    if dev.kind != "builtin" or len(dev.speakers) < 2 or is_shape(dev):
        return None, None
    ordered = sorted(dev.speakers, key=lambda s: s.channel) if len(dev.speakers) == 2 else _mains(dev)
    if len(ordered) < 2:
        return None, None
    return ordered[0], ordered[-1]


def partner_speaker(dev: Device, spk: Speaker) -> Optional[Speaker]:
    """The speaker on the other side that belongs with this one: the other end
    of a unit, or the other half of a left / right pair of loose speakers."""
    if dev.kind == "builtin":
        first, last = unit_ends(dev)
        if spk is first:
            return last
        if spk is last:
            return first
        return None
    if len(dev.speakers) == 2:
        return dev.speakers[1] if spk is dev.speakers[0] else dev.speakers[0]
    if spk.channel in (2, 3):           # centre and subwoofer have no partner
        return None
    return next((s for s in dev.speakers if s.channel == (spk.channel ^ 1)), None)


def can_move_alone(dev: Device, spk: Speaker) -> bool:
    """True if this speaker has a position of its own that can be dragged."""
    if dev.kind == "external":
        return True
    return spk in unit_ends(dev)


def move_speaker(dev: Device, spk: Speaker, x: float, y: float, mirror: bool = False) -> None:
    """Put one speaker at a spot in the room.

    Loose speakers simply move. For a unit with built in speakers, moving one
    end stretches and turns the unit while the other end stays where it is.
    With mirror on, the partner does the mirror image instead: the opposite
    way sideways, the same way front to back.
    """
    old_x, old_y = speaker_position(dev, spk)
    dx, dy = x - old_x, y - old_y
    partner = partner_speaker(dev, spk)
    if dev.kind == "external":
        spk.x, spk.y = round(x, 3), round(y, 3)
        if mirror and partner is not None:
            partner.x, partner.y = round(partner.x - dx, 3), round(partner.y + dy, 3)
        return
    if partner is None:                 # a middle speaker: the whole unit moves
        dev.x, dev.y = round(dev.x + dx, 3), round(dev.y + dy, 3)
        return
    px, py = speaker_position(dev, partner)
    if mirror:
        px, py = px - dx, py + dy
    first, _last = unit_ends(dev)
    (ax, ay), (bx, by) = ((x, y), (px, py)) if spk is first else ((px, py), (x, y))
    length = math.hypot(bx - ax, by - ay)
    if length > 1e-6:
        dev.rotation = round(math.degrees(math.atan2(by - ay, bx - ax)), 2)
    dev.width = round(max(MIN_WIDTH, length), 3)
    dev.x, dev.y = round((ax + bx) / 2.0, 3), round((ay + by) / 2.0, 3)


def face_listener(proj: Project, dev: Device) -> None:
    """Turn a unit so its front points at the listener."""
    dx, dy = dev.x - proj.listener_x, dev.y - proj.listener_y
    if abs(dx) + abs(dy) > 1e-6:
        dev.rotation = round(math.degrees(math.atan2(dx, -dy)), 1)


def _angle_diff(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def auto_assign_roles(proj: Project) -> int:
    """Give every speaker the role that best matches where it sits around the
    listener. Speakers labelled as subwoofer keep that label. Each role goes to
    the best placed free speaker, spare speakers double up the nearest role.
    A role stays empty when the only speaker left for it would be badly wrong
    (on the other side, or more than a quarter turn away). The engine shares
    the sound of an empty role between its neighbours, so nothing is lost.
    Returns how many speakers changed."""
    from scipy.optimize import linear_sum_assignment
    import numpy as np

    roles = [r for r in proj.mode_roles() if not is_sub(r)]
    spks = [(d, s) for d, s in proj.all_speakers()
            if d.enabled and not is_sub(s.role) and not is_shaker(s.role)]
    if not roles or not spks:
        return 0
    angles = [speaker_angle(proj, d, s) for d, s in spks]

    def price(role: str, angle: float) -> float:
        # squared, so one badly placed role costs more than several slightly off ones
        cost = _angle_diff(ROLE_ANGLES[role], angle) ** 2
        want = ROLE_ANGLES[role]
        off_centre = 8.0 < abs(angle) < 172.0
        if off_centre and want not in (0.0, 180.0) and (want > 0) != (angle > 0):
            cost += 180.0 ** 2      # a left role on a right speaker is never worth it
        return cost

    cost = np.array([[price(r, a) for a in angles] for r in roles])
    leave_empty = np.full((len(roles), len(roles)), 95.0 ** 2)
    chosen: dict[int, str] = {}
    ri, si = linear_sum_assignment(np.hstack([cost, leave_empty]))
    for r, s in zip(ri, si):
        if s < len(spks):
            chosen[int(s)] = roles[int(r)]
    for s in range(len(spks)):
        if s not in chosen:
            chosen[s] = roles[int(np.argmin(cost[:, s]))]
    changed = 0
    for idx, (_, spk) in enumerate(spks):
        if spk.role != chosen[idx]:
            proj.set_role(spk, chosen[idx])
            changed += 1
    return changed


SPEED_OF_SOUND = 343.0


def common_delay(proj: Project) -> float:
    """The delay every playing speaker has (its own delay plus its output's Extra delay).
    It only makes everything later: taking it off all of them changes nothing else."""
    totals = [d.trim_ms + s.delay_ms for d, s in proj.all_speakers() if d.enabled and s.role != OFF]
    return max(0.0, min(totals)) if totals else 0.0


def remove_common_delay(proj: Project) -> float:
    """Takes the delay that every playing speaker shares off all of them (from the outputs'
    Extra delay first, then from the speakers). Returns the milliseconds taken off."""
    m = common_delay(proj)
    if m < 0.05:
        return 0.0
    for dev in proj.devices:
        if not dev.enabled:
            continue
        from_trim = min(max(dev.trim_ms, 0.0), m)
        dev.trim_ms = round(dev.trim_ms - from_trim, 2)
        rest = m - from_trim
        for spk in dev.speakers:
            spk.delay_ms = round(max(0.0, spk.delay_ms - rest), 2)
    return m


def auto_align_delays(proj: Project) -> None:
    """Delay the nearer speakers so sound from all of them reaches the
    listener at the same moment."""
    items = [(d, s) for d, s in proj.all_speakers() if d.enabled and s.role != OFF]
    if not items:
        return
    dist = [speaker_distance(proj, d, s) for d, s in items]
    far = max(dist)
    for (_, spk), d in zip(items, dist):
        spk.delay_ms = round((far - d) / SPEED_OF_SOUND * 1000.0, 2)
    remove_common_delay(proj)          # the latest speaker gets none at all
