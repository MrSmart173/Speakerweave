"""Speaker types, the speaker library, settings, controls, controllers, Stream Deck
links, Bluetooth and test sounds."""
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from speakerweave import bluetooth, controls, speaker_library
from speakerweave.gamepads import GamepadWatcher
from speakerweave.model import Project, Speaker
from speakerweave.presets import RANGE_PRESETS, apply_range_preset, matching_preset
from speakerweave.remote import RemoteServer
from speakerweave.settings import AppSettings


# ------------------------------------------------------------------ speaker types

def test_every_speaker_type_applies_and_is_recognised_again():
    for preset in RANGE_PRESETS:
        spk = Speaker()
        apply_range_preset(spk, preset.key)
        assert spk.hp_on == (preset.low_cut is not None) and spk.lp_on == (preset.high_cut is not None)
        assert matching_preset(spk) == preset.key, preset.key
    spk = Speaker()
    apply_range_preset(spk, "tv")
    spk.hp_freq = 93.0
    assert matching_preset(spk) == ""
    apply_range_preset(spk, "soundbar")        # same numbers as "sat80": keeps its own name
    assert matching_preset(spk) == "soundbar"


# ------------------------------------------------------------------ speaker library

NAMES = {
    "LG TV SSCR2 (NVIDIA High Definition Audio)": "tv",
    "SAMSUNG (NVIDIA High Definition Audio)": "tv",
    "PHL 271V8 (NVIDIA High Definition Audio)": "monitor_screen",
    "DELL U2720Q (Intel(R) Display Audio)": "monitor_screen",
    "DENON-AVR (NVIDIA High Definition Audio)": "receiver",
    "Speakers (G560 Gaming Speaker)": "logitech_g560",
    "Speakers (Creative Pebble V3)": "creative_pebble",
    "Speakers (Creative Pebble Plus)": "creative_pebble_plus",
    "Speakers (Razer Nommo V2)": "razer_nommo_v2",
    "Speakers (Razer Nommo Chroma)": "razer_nommo",
    "Headphones (Realtek(R) Audio)": "headphones",
    "Headset Earphone (HyperX Cloud II Wireless)": "headphones",
    "Headphones (WH-1000XM4 Stereo)": "headphones",
    "Speakers (JBL Flip 5 Stereo)": "portable",
    "CABLE Input (VB-Audio Virtual Cable)": "virtual",
    "Speakers (Focusrite USB Audio)": "interface",
    "Speakers (UMC204HD 192k)": "interface",
    "Speakers (Realtek(R) Audio)": "pc_output",
    "Realtek Digital Output (Realtek(R) Audio)": "pc_output",
}


def test_outputs_are_recognised_by_their_windows_name():
    for name, key in NAMES.items():
        found = speaker_library.recognise(name)
        assert found is not None and found.key == key, (name, found and found.key)
    assert speaker_library.recognise("Something nobody makes") is None


def test_library_entries_are_complete():
    from speakerweave.presets import BY_KEY
    keys = set()
    for entry in speaker_library.LIBRARY:
        assert entry.key not in keys
        keys.add(entry.key)
        assert entry.category in speaker_library.CATEGORIES
        assert entry.preset == "" or entry.preset in BY_KEY
        assert entry.sub_preset == "" or entry.sub_preset in BY_KEY
    listed = [m for _h, items in speaker_library.choices() for m in items]
    assert len(listed) > 40 and all(m.category != "virtual" for m in listed)


def test_applying_a_model_sets_where_the_sound_comes_out_and_the_ranges():
    proj = Project(mode="5.1")
    tv = proj.add_device("LG TV SSCR2 (NVIDIA High Definition Audio)", 2)
    speaker_library.apply_model(tv, speaker_library.recognise(tv.name))
    assert tv.kind == "builtin" and tv.model == "tv"
    assert all(s.hp_on and s.hp_freq == 100 for s in tv.speakers)
    card = proj.add_device("Speakers (Realtek(R) Audio)", 6)
    speaker_library.apply_model(card, speaker_library.BY_KEY["generic_sat"])
    assert card.kind == "builtin"                  # a surround system stays in its shape
    stereo = proj.add_device("Speakers (Realtek(R) Audio)", 2)
    speaker_library.apply_model(stereo, speaker_library.BY_KEY["generic_sat"])
    assert stereo.kind == "external"
    sub = next(s for s in card.speakers if s.role == "LFE")
    assert (sub.hp_freq, sub.lp_freq) == (10, 75)
    assert all(s.hp_freq == 80 and not s.lp_on for s in card.speakers if s is not sub)
    before = [(s.hp_on, s.hp_freq) for s in card.speakers]
    speaker_library.apply_model(card, speaker_library.BY_KEY["interface"])   # unknown speakers
    assert [(s.hp_on, s.hp_freq) for s in card.speakers] == before


# ------------------------------------------------------------------ settings

def test_settings_are_saved_and_survive_damage():
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "settings.json")
    s = AppSettings(start_in_tray=True, remote_port=50000)
    s.bindings.append({"action": "mute", "kind": "key", "vk": 120, "mods": 2, "text": "Ctrl+F9"})
    s.setup_slots[2] = "C:/setups/racing.json"
    s.save(path)
    back = AppSettings.load(path)
    assert back == s and len(back.remote_token) == 8
    with open(path, "w") as fh:
        fh.write("{not json")
    damaged = AppSettings.load(path)
    assert damaged == AppSettings(remote_token=damaged.remote_token)
    with open(path, "w") as fh:
        fh.write('{"setup_slots": ["a"], "bindings": 5, "future": 1}')
    odd = AppSettings.load(path)
    assert odd.setup_slots == ["a", "", "", ""] and odd.bindings == []


# ------------------------------------------------------------------ bindings

def test_one_input_does_one_thing():
    bindings = []
    f9 = {"kind": "key", "vk": 120, "mods": 0, "qt": "F9", "text": "F9"}
    pad = {"kind": "pad", "guid": "abc", "device": "Wheel", "input": "b3", "text": "Button 4 on Wheel"}
    assert controls.set_binding(bindings, "mute", f9) == []
    assert controls.set_binding(bindings, "mute", pad) == []
    assert controls.binding_for(bindings, "mute", "key")["text"] == "F9"
    assert controls.set_binding(bindings, "volume_up", dict(f9)) == ["mute"]     # F9 moves
    assert controls.binding_for(bindings, "mute", "key") is None
    assert controls.actions_for_pad(bindings, "abc", "b3") == ["mute"]
    controls.set_binding(bindings, "mute", dict(pad, input="b4", text="Button 5 on Wheel"))
    assert controls.actions_for_pad(bindings, "abc", "b3") == []                 # replaced
    controls.clear_binding(bindings, "mute", "pad")
    assert [b["action"] for b in bindings] == ["volume_up"]
    assert controls.next_mode("7.1", 1) == ("2.0", False) and controls.next_mode("2.0", -1) == ("7.1", False)
    assert controls.next_mode(("5.1", False), 1) == ("5.1", True)
    assert controls.next_mode("custom", 1) == ("2.0", False)
    proj = Project()
    dev = proj.add_device("TV", 2)
    keys = [a.key for a in controls.all_actions(proj)]
    assert f"mute_output:{dev.id}" in keys and "slot_4" in keys
    assert controls.describe_mods(controls.MOD_CONTROL | controls.MOD_SHIFT) == "Ctrl+Shift"


# ------------------------------------------------------------------ controllers

def test_controller_buttons_and_hats_are_reported_once_per_press():
    import sdl2
    pads = GamepadWatcher()
    assert pads.start(), pads.error
    index = sdl2.SDL_JoystickAttachVirtual(sdl2.SDL_JOYSTICK_TYPE_WHEEL, 3, 40, 1)
    try:
        assert any(d.buttons == 40 for d in pads.devices())
        joy = next(j for j, *_r in pads._open.values() if sdl2.SDL_JoystickNumButtons(j) == 40)
        assert pads.poll() == []
        sdl2.SDL_JoystickSetVirtualButton(joy, 33, 1)
        events = pads.poll()
        assert [e.input for e in events] == ["b33"] and "Button 34" in events[0].text
        assert pads.poll() == []                         # held, not pressed again
        sdl2.SDL_JoystickSetVirtualButton(joy, 33, 0)
        sdl2.SDL_JoystickSetVirtualHat(joy, 0, sdl2.SDL_HAT_UP)
        assert [e.input for e in pads.poll()] == ["h0up"]
        sdl2.SDL_JoystickSetVirtualHat(joy, 0, sdl2.SDL_HAT_RIGHTUP)
        assert [e.input for e in pads.poll()] == ["h0right"]
    finally:
        sdl2.SDL_JoystickDetachVirtual(index)
    pads.poll()
    assert all(d.buttons != 40 for d in pads.devices())
    pads.stop()


# ------------------------------------------------------------------ Stream Deck links

def free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_links_trigger_actions_only_with_the_right_code():
    seen = []
    remote = RemoteServer(free_port(), "c0de", seen.append)
    assert remote.start(), remote.error
    try:
        assert get(remote.url("volume_up")) == 200
        assert get(remote.url("mute_output:ab12")) == 200
        assert get(f"http://127.0.0.1:{remote.port}/wrong/volume_up") == 403
        assert get(f"http://127.0.0.1:{remote.port}/c0de/rm%20-rf") == 404
        assert seen == ["volume_up", "mute_output:ab12"]
        clash = RemoteServer(remote.port, "x", seen.append)
        assert not clash.start() and "in use" in clash.error
    finally:
        remote.stop()
    assert not remote.running


# ------------------------------------------------------------------ Bluetooth

def test_bluetooth_list_is_read_from_windows_answer():
    one = '{"FriendlyName":"WH-1000XM4","Status":"OK","InstanceId":"BTHENUM\\\\DEV_38184C1F0A8B\\\\7&1"}'
    assert [d.name for d in bluetooth.parse(one)] == ["WH-1000XM4"]
    many = ('[{"FriendlyName":"Xbox Controller","Status":"Unknown","InstanceId":"BTHLE\\\\DEV_AA"},'
            '{"FriendlyName":"JBL Flip 5","Status":"OK","InstanceId":"BTHENUM\\\\DEV_BB"},'
            '{"FriendlyName":"","Status":"OK","InstanceId":"BTHENUM\\\\DEV_CC"}]')
    devices = bluetooth.parse(many)
    assert [(d.name, d.available, d.low_energy) for d in devices] == [
        ("JBL Flip 5", True, False), ("Xbox Controller", False, True)]
    assert bluetooth.parse("") == []


# ------------------------------------------------------------------ test sounds

def test_sweep_and_noise_play_on_one_speaker_only():
    from speakerweave.engine import Engine
    proj = Project(mode="2.0", master_db=0.0)
    dev = proj.add_device("Amp", 2)
    left, right = dev.speakers
    eng = Engine(proj)
    eng.configure(48000.0, 2)
    eng.process(np.zeros((4800, 2)))
    eng.identify(left.id, 1.0, "sweep")
    out = np.concatenate([eng.process(np.zeros((480, 2)))[dev.id] for _ in range(100)])
    assert np.abs(out[:, 1]).max() == 0 and np.abs(out[:, 0]).max() > 0.2
    start = np.abs(np.fft.rfft(out[2400:7200, 0])).argmax() * 48000 / 4800
    end = np.abs(np.fft.rfft(out[40000:44800, 0])).argmax() * 48000 / 4800
    assert start < 100 and end > 3000, (start, end)          # it glides from low to high
    assert not eng.identifying


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok   ", name)


# ------------------------------------------------------------ custom modes and side or rear pairs

def test_side_or_rear_surround_pair():
    from speakerweave.model import Project, mode_choices, mode_label
    p = Project(mode="5.1")
    assert p.mode_roles() == ["FL", "FR", "FC", "LFE", "SL", "SR"]
    p.surround_rear = True
    assert p.mode_roles() == ["FL", "FR", "FC", "LFE", "BL", "BR"]
    assert "RL RR" in mode_label("5.1", True) and "SL SR" in mode_label("5.1", False)
    assert ("5.0", True) in mode_choices() and ("7.1", True) not in mode_choices()
    # 7.1 has both pairs, so the rear switch does nothing there
    assert Project(mode="7.1", surround_rear=True).mode_roles().count("SL") == 1


def test_switching_side_to_rear_moves_the_speakers():
    from speakerweave.model import Project
    p = Project(mode="5.1")
    dev = p.add_device("Amp", 6)
    roles = ["FL", "FR", "FC", "LFE", "SL", "SR"]
    for spk, role in zip(dev.speakers, roles):
        p.set_role(spk, role)
    p.set_mode("5.1", rear=True)
    assert [s.role for s in dev.speakers] == ["FL", "FR", "FC", "LFE", "BL", "BR"]
    p.set_mode("5.1", rear=False)
    assert [s.role for s in dev.speakers] == roles
    # going up to 7.1 keeps a side pair as side, and a rear pair as rear
    p.set_mode("7.1")
    assert [s.role for s in dev.speakers] == roles


def test_custom_positions_and_extra_subwoofers():
    from speakerweave.model import CUSTOM, Project, standard_mode_for
    p = Project(mode="5.1")
    dev = p.add_device("Amp", 6)
    for spk, role in zip(dev.speakers, ["FL", "FR", "FC", "LFE", "SL", "SR"]):
        p.set_role(spk, role)
    p.set_mode(CUSTOM, custom=["BR", "FL", "FR", "BL", "LFE", "LFE2"])
    assert p.mode_roles() == ["FL", "FR", "LFE", "LFE2", "BL", "BR"]
    # the centre has no place left, the side pair becomes the rear pair
    assert [s.role for s in dev.speakers] == ["FL", "FR", "OFF", "LFE", "BL", "BR"]
    assert p.mode_text() == "Custom 4.2   FL FR RL RR"
    p.set_role(dev.speakers[2], "LFE2")
    assert dev.speakers[2].lp_on and dev.speakers[2].lp_freq == 75     # a second sub gets the sub preset
    again = Project.from_json(p.to_json())
    assert again.mode == CUSTOM and again.mode_roles() == p.mode_roles()
    assert standard_mode_for(["FL", "FR", "FC", "LFE", "BL", "BR"]) == ("5.1", True)
    assert standard_mode_for(["FL", "FR", "SL", "SR"]) == ("4.0", False)
    assert standard_mode_for(["FL", "FR", "FC", "LFE", "LFE2"]) is None
    assert standard_mode_for(["FC"]) is None


def test_every_subwoofer_gets_the_bass():
    import numpy as np
    from speakerweave.mixer import build_matrix
    source = ["FL", "FR", "FC", "LFE", "SL", "SR"]
    room = ["FL", "FR", "LFE", "LFE2", "BL", "BR"]
    m = build_matrix(source, room)
    assert m.shape == (6, 6)
    assert np.allclose(m[2], m[3]) and m[2, 3] > 0
    # the side channels of a 5.1 source end up on the rear pair
    assert m[4, 4] > 0 and m[5, 5] > 0
    # with bass sent to the subs, both subs carry it
    m = build_matrix(["FL", "FR"], room, bass_redirect=True)
    assert np.allclose(m[2], m[3]) and m[2, 0] > 0


def test_no_channel_is_lost_in_any_custom_layout():
    import itertools
    import numpy as np
    from speakerweave.mixer import build_matrix
    from speakerweave.model import MAIN_POSITIONS
    source = ["FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"]
    for n in range(1, len(MAIN_POSITIONS) + 1):
        for mains in itertools.combinations(MAIN_POSITIONS, n):
            for subs in ([], ["LFE"], ["LFE", "LFE2"]):
                room = list(mains) + subs
                m = build_matrix(source, room, bass_redirect=False)
                silent = [s for i, s in enumerate(source) if not np.any(m[:, i])]
                assert not silent, (room, silent)
    # the centre of a source played on a side pair only is shared by both
    m = build_matrix(["FL", "FR", "FC"], ["SL", "SR"])
    assert m[0, 2] == m[1, 2] > 0 and m[0, 0] == 1.0
