"""What SpeakerWeave knows about common speakers, screens, headsets and sound cards.

Windows tells us the name of every sound output, for example
"LG TV SSCR2 (NVIDIA High Definition Audio)" or "Speakers (G560 Gaming Speaker)".
Outputs whose name gives them away are recognised automatically when they are
added. Speakers on an ordinary audio jack cannot be seen by Windows, so their
models can be picked from a list instead.

Each entry fills in a frequency range preset (see presets.py) that suits its
driver size. The presets are starting points to fine tune by ear, not
measurements of the exact model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import SHAKER, Device, is_shape, is_sub, set_attached
from .presets import apply_range_preset

# category key -> heading in the model list
CATEGORIES = {
    "screen": "Screens and TVs",
    "system": "Speaker systems with their own subwoofer",
    "monitor": "Studio monitors and bookshelf speakers",
    "desktop": "Desktop and portable speakers",
    "sub": "Subwoofers and bass shakers",
    "headphones": "Headphones and headsets",
    "receiver": "AV receivers and soundbars",
    "interface": "Sound cards, audio interfaces and DACs",
    "generic": "Any other speaker, by size",
    "virtual": "Virtual sound devices",
}


@dataclass(frozen=True)
class SpeakerModel:
    key: str
    name: str
    category: str
    preset: str = ""            # range preset for every channel except the subwoofer
    sub_preset: str = ""        # range preset for a channel playing the subwoofer role
    kind: str = ""              # "builtin", "external" or "" to leave it as it is
    patterns: tuple = field(default_factory=tuple)   # matched against the Windows name
    note: str = ""


def _m(key, name, category, preset="", sub_preset="", kind="", patterns=(), note=""):
    return SpeakerModel(key, name, category, preset, sub_preset, kind, tuple(patterns), note)


OWN_SUB = "It has its own subwoofer and crossover, so SpeakerWeave sends it the full range."
SIZE_NOTE = "Preset chosen from the woofer size. Fine tune by ear."

LIBRARY = [
    # ---- not speakers at all
    _m("virtual", "Virtual sound device", "virtual",
       patterns=[r"VB-Audio", r"CABLE (Input|Output)", r"VoiceMeeter", r"Virtual Audio Cable",
                 r"Steam Streaming"],
       note="This is not a speaker. Choose it under Listen to as the source instead."),

    # ---- headphones and headsets
    _m("headphones", "Headphones or headset", "headphones", "full", kind="builtin",
       patterns=[r"\bHead(phones?|set)\b", r"\bEarphones?\b", r"Hands-Free", r"Arctis", r"HyperX",
                 r"\bAstro\b", r"Corsair (HS|Void|Virtuoso)", r"BlackShark", r"Kraken", r"Barracuda",
                 r"\bG ?PRO X\b", r"\bG(733|935|635|535|435)\b", r"WH-1000", r"AirPods", r"\bBuds",
                 r"QuietComfort"],
       note="Headphones play the full range. Several headphones can share one role."),

    # ---- receivers and soundbars (they manage their own bass)
    _m("receiver", "AV receiver", "receiver", "full", kind="external",
       patterns=[r"\bAVR\b", r"\bDENON\b", r"Marantz", r"\bONKYO\b", r"\bPioneer\b",
                 r"YAMAHA\s*(AV|RX|TSR)", r"\bRX-V\d", r"\bSTR-DH", r"\bIntegra\b"],
       note="The receiver handles bass itself. Set its speakers to Small or Large in its own menu."),
    _m("soundbar", "Soundbar", "receiver", "full", kind="builtin",
       patterns=[r"Sound ?bar", r"\bSONOS\b", r"\bBose\b", r"\bHW-[A-Z]\d", r"Leviathan", r"Katana"],
       note="Most soundbars manage their own bass. If yours has no subwoofer, choose the "
            "'Soundbar without a subwoofer' speaker type."),

    # ---- desktop systems with their own subwoofer
    _m("logitech_g560", "Logitech G560", "system", "full", kind="builtin", patterns=[r"G560"], note=OWN_SUB),
    _m("logitech_z906", "Logitech Z906 (5.1)", "system", "full", kind="external", patterns=[r"\bZ906\b"],
       note=OWN_SUB + " Connect it to a 5.1 sound card output with three cables."),
    _m("logitech_z623", "Logitech Z623", "system", "full", kind="builtin", patterns=[r"\bZ623\b"], note=OWN_SUB),
    _m("logitech_z533", "Logitech Z533", "system", "full", kind="builtin", patterns=[r"\bZ533\b"], note=OWN_SUB),
    _m("logitech_z407", "Logitech Z407", "system", "full", kind="builtin", patterns=[r"\bZ407\b"], note=OWN_SUB),
    _m("logitech_z333", "Logitech Z333", "system", "full", kind="builtin", patterns=[r"\bZ333\b"], note=OWN_SUB),
    _m("logitech_z313", "Logitech Z313", "system", "full", kind="builtin", patterns=[r"\bZ313\b"], note=OWN_SUB),
    _m("creative_pebble_plus", "Creative Pebble Plus", "system", "full", kind="builtin",
       patterns=[r"Pebble (X )?Plus"], note=OWN_SUB),
    _m("razer_nommo_v2", "Razer Nommo V2", "system", "full", kind="builtin",
       patterns=[r"Nommo (V2|Pro)"], note=OWN_SUB),
    _m("steelseries_arena_7_9", "SteelSeries Arena 7 or 9", "system", "full", kind="builtin",
       patterns=[r"Arena [79]\b"], note=OWN_SUB),

    # ---- studio monitors and bookshelf speakers (usually on a jack, so picked by hand)
    _m("yamaha_hs5", "Yamaha HS5", "monitor", "monitor_5", kind="external", note=SIZE_NOTE),
    _m("yamaha_hs7", "Yamaha HS7", "monitor", "monitor_6", kind="external", note=SIZE_NOTE),
    _m("yamaha_hs8", "Yamaha HS8", "monitor", "monitor_8", kind="external", note=SIZE_NOTE),
    _m("krk_rokit_5", "KRK Rokit 5", "monitor", "monitor_5", kind="external", note=SIZE_NOTE),
    _m("krk_rokit_7", "KRK Rokit 7", "monitor", "monitor_6", kind="external", note=SIZE_NOTE),
    _m("krk_rokit_8", "KRK Rokit 8", "monitor", "monitor_8", kind="external", note=SIZE_NOTE),
    _m("jbl_305p", "JBL 305P MkII", "monitor", "monitor_5", kind="external", note=SIZE_NOTE),
    _m("jbl_306p", "JBL 306P MkII", "monitor", "monitor_6", kind="external", note=SIZE_NOTE),
    _m("jbl_308p", "JBL 308P MkII", "monitor", "monitor_8", kind="external", note=SIZE_NOTE),
    _m("presonus_e35", "PreSonus Eris 3.5", "monitor", "small_3", kind="external", note=SIZE_NOTE),
    _m("presonus_e45", "PreSonus Eris 4.5", "monitor", "monitor_5", kind="external", note=SIZE_NOTE),
    _m("presonus_e5", "PreSonus Eris 5", "monitor", "monitor_5", kind="external", note=SIZE_NOTE),
    _m("mackie_cr3x", "Mackie CR3-X", "monitor", "small_3", kind="external",
       patterns=[r"CR3-?X"], note=SIZE_NOTE),
    _m("mackie_cr4x", "Mackie CR4-X", "monitor", "small_3", kind="external",
       patterns=[r"CR4-?X"], note=SIZE_NOTE),
    _m("mackie_cr5x", "Mackie CR5-X", "monitor", "monitor_5", kind="external",
       patterns=[r"CR5-?X"], note=SIZE_NOTE),
    _m("maudio_bx4", "M-Audio BX4", "monitor", "monitor_5", kind="external", note=SIZE_NOTE),
    _m("maudio_bx5", "M-Audio BX5", "monitor", "monitor_5", kind="external", note=SIZE_NOTE),
    _m("edifier_r2000db", "Edifier R2000DB", "monitor", "monitor_5", kind="external",
       patterns=[r"R2000"], note=SIZE_NOTE),
    _m("edifier_4in", "Edifier R1280T, R1280DB, R1700BT or MR4", "monitor", "small_3", kind="external",
       patterns=[r"Edifier", r"R1280", r"R1700", r"\bMR4\b"], note=SIZE_NOTE),
    _m("audioengine_a5", "Audioengine A5+", "monitor", "monitor_5", kind="external",
       patterns=[r"Audioengine (HD|A)?5"], note=SIZE_NOTE),
    _m("audioengine_a2", "Audioengine A2+", "desktop", "desktop", kind="external",
       patterns=[r"Audioengine (HD|A)?2"], note=SIZE_NOTE),
    _m("kanto_yu2", "Kanto YU2", "monitor", "small_3", kind="external", patterns=[r"YU2\b"], note=SIZE_NOTE),
    _m("kanto_yu4", "Kanto YU4", "monitor", "small_3", kind="external", patterns=[r"YU4\b"], note=SIZE_NOTE),

    # ---- desktop and portable speakers
    _m("creative_pebble", "Creative Pebble", "desktop", "desktop", kind="builtin",
       patterns=[r"Pebble"], note=SIZE_NOTE),
    _m("razer_nommo", "Razer Nommo", "desktop", "desktop", kind="builtin", patterns=[r"Nommo"], note=SIZE_NOTE),
    _m("steelseries_arena_3", "SteelSeries Arena 3", "desktop", "small_3", kind="builtin",
       patterns=[r"Arena 3\b"], note=SIZE_NOTE),
    _m("logitech_small", "Logitech Z120, Z150 or Z207", "desktop", "desktop", kind="builtin",
       patterns=[r"\bZ(120|150|207)\b"], note=SIZE_NOTE),
    _m("bose_companion_2", "Bose Companion 2", "desktop", "desktop", kind="external", note=SIZE_NOTE),
    _m("portable", "Portable Bluetooth speaker", "desktop", "portable", kind="builtin",
       patterns=[r"JBL (Flip|Charge|Go|Clip|Xtreme|Pulse)", r"SoundLink", r"(WONDER|MEGA|ULTIMATE ?EARS ?)BOOM",
                 r"\bUE BOOM\b"],
       note="Small portable speakers sound cleaner without deep bass."),

    # ---- subwoofers and shakers
    _m("subwoofer", "Powered subwoofer", "sub", "sub", "sub", kind="external",
       note="Plug the subwoofer into a channel that plays the Subwoofer role."),
    _m("buttkicker", "ButtKicker Gamer 2 or Gamer Plus", "sub", "shaker", "shaker", kind="external",
       note="Its speakers get the Bass shaker role: they feel the game's bass, and any SimHub "
            "effects you send them on the Effects tab."),
    _m("dayton_shaker", "Dayton Audio bass shaker or puck", "sub", "shaker", "shaker", kind="external",
       note="Its speakers get the Bass shaker role: they feel the game's bass, and any SimHub "
            "effects you send them on the Effects tab."),

    # ---- sound cards and interfaces: the speakers behind them are unknown
    _m("interface", "Audio interface or DAC", "interface", "", kind="external",
       patterns=[r"Focusrite", r"Scarlett", r"\bUMC\d", r"BEHRINGER", r"Audient", r"\bMOTU\b", r"\bSSL \d",
                 r"Universal Audio", r"\bVolt \d", r"Steinberg", r"\bUR\d\d", r"Arturia", r"MiniFuse",
                 r"Topping", r"FiiO", r"\bSMSL\b", r"Schiit", r"Sound ?Blaster", r"\bXonar\b", r"Essence",
                 r"AudioBox", r"\bRME\b", r"Babyface", r"Fireface", r"\bDAC\b"],
       note="Windows cannot see which speakers are plugged into it. Pick them from the list below."),

    # ---- screens: TVs before monitors, both after the more specific entries above
    _m("tv", "TV", "screen", "tv", kind="builtin",
       patterns=[r"\bTV\b", r"^\s*SAMSUNG\s*(\(|$)", r"^\s*SONY\b", r"BRAVIA", r"Hisense", r"\bTCL\b",
                 r"Panasonic", r"\bVIZIO\b", r"TOSHIBA", r"\bSHARP\b", r"\bFTV\b"],
       note="If sound comes out of separate speakers plugged into the TV, change 'Where the sound "
            "comes out' and pick those speakers instead."),
    _m("monitor_screen", "Computer monitor", "screen", "tiny", kind="builtin",
       patterns=[r"\((NVIDIA|AMD|ATI) High Definition Audio", r"Display Audio"],
       note="Monitor speakers are tiny. If this is a TV, choose TV instead. If speakers are plugged "
            "into its headphone jack, change 'Where the sound comes out'."),

    # ---- any other speaker, chosen by size
    _m("generic_floor", "Floor standing speakers", "generic", "floor", kind="external"),
    _m("generic_8", "Bookshelf or monitor, 8 inch woofer", "generic", "monitor_8", kind="external"),
    _m("generic_6", "Bookshelf or monitor, 6 to 6.5 inch woofer", "generic", "monitor_6", kind="external"),
    _m("generic_5", "Bookshelf or monitor, 4.5 to 5 inch woofer", "generic", "monitor_5", kind="external"),
    _m("generic_3", "Small speakers, 3 to 4 inch", "generic", "small_3", kind="external"),
    _m("generic_desktop", "Small desktop speakers, 2 to 3 inch", "generic", "desktop", kind="external"),
    _m("generic_sat", "Satellites with a separate subwoofer", "generic", "sat80", "sub", kind="external"),

    # ---- the computer's own outputs: last, because the names are so general
    _m("pc_output", "Computer sound output", "interface", "", kind="external",
       patterns=[r"Realtek", r"High Definition Audio Device", r"^\s*Speakers\b", r"\bLine\b", r"S/PDIF",
                 r"Digital Output", r"USB Audio", r"USB PnP Sound"],
       note="Windows cannot see which speakers are plugged into this output. Pick them from the "
            "list below for a matching preset."),
]

BY_KEY = {m.key: m for m in LIBRARY}
_COMPILED = [(m, [re.compile(p, re.IGNORECASE) for p in m.patterns]) for m in LIBRARY]


GENERIC_FRONT = {"speakers", "speaker", "headphones", "headset", "headset earphone", "line",
                 "line out", "digital audio", "digital audio (s/pdif)", "realtek digital output"}
DRIVER_WORDS = re.compile(r"High Definition Audio|Display Audio|Realtek|USB Audio Device|"
                          r"^USB Audio$|Audio Device$", re.IGNORECASE)


def friendly_name(device_name: str) -> str:
    """A shorter name for the map: "LG TV SSCR2 (NVIDIA High Definition Audio)" becomes
    "LG TV SSCR2", "Speakers (G560 Gaming Speaker)" becomes "G560 Gaming Speaker"."""
    match = re.match(r"^(.*?)\s*\((.*)\)\s*$", device_name or "")
    if not match:
        return device_name
    front, inner = match.group(1).strip(), match.group(2).strip()
    if front.lower() in GENERIC_FRONT:
        return device_name if DRIVER_WORDS.search(inner) else inner
    return front or device_name


def recognise(device_name: str):
    """The library entry whose name pattern matches this Windows device name, or None."""
    for entry, patterns in _COMPILED:
        if any(p.search(device_name or "") for p in patterns):
            return entry
    return None


def apply_model(dev: Device, entry: SpeakerModel) -> None:
    """Fills in where the sound comes out and the frequency range of every speaker."""
    if entry.kind and entry.kind != dev.kind and not (is_shape(dev) and entry.kind == "external"):
        set_attached(dev, entry.kind == "builtin")
    if entry.preset == "shaker":
        # a ButtKicker amplifier on its own output: every channel drives a shaker
        for spk in dev.speakers:
            spk.role = SHAKER
            spk.apply_shaker_preset()
        dev.model = entry.key
        return
    for spk in dev.speakers:
        if is_sub(spk.role):
            if entry.sub_preset:
                apply_range_preset(spk, entry.sub_preset)
        elif entry.preset:
            apply_range_preset(spk, entry.preset)
    dev.model = entry.key


def choices():
    """(category heading, [entries]) in display order, for the model picker."""
    order = ["generic", "monitor", "desktop", "system", "sub", "screen", "receiver", "headphones",
             "interface"]
    out = []
    for cat in order:
        items = [m for m in LIBRARY if m.category == cat]
        if items:
            out.append((CATEGORIES[cat], items))
    return out
