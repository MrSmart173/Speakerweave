"""Test sounds on one speaker only, solo on the map, colour themes, the user's
own test sounds and the Windows default output. Run with:  python -m pytest tests"""
import os
import struct
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from PySide6.QtWidgets import QApplication

from fake_audio import FakeSoundDevice
from speakerweave import backend, default_output, sounds, windefault
from speakerweave.dsp import PinkNoise
from speakerweave.engine import Engine
from speakerweave.ui import state as state_module
from speakerweave.ui import theme
from test_core import SR, three_tv_project


def pump(app, seconds=0.0):
    end = time.monotonic() + seconds
    app.processEvents()
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def loud_channels(outs, floor=1e-4):
    return {(d, c) for d, o in outs.items() for c in range(o.shape[1]) if np.abs(o[:, c]).max() > floor}


# ------------------------------------------------------------------ test sounds play on one speaker only

def test_a_test_only_run_plays_nothing_but_the_test_sound():
    proj, left, mid, right = three_tv_project()
    eng = Engine(proj)
    eng.configure(SR, 8)
    eng.test_only = True
    noise = (PinkNoise(1).block(4800)[:, None] * 0.1) * np.ones((1, 8))
    eng.process(noise)
    assert loud_channels(eng.process(noise)) == set()        # the input never reaches a speaker
    eng.identify(left.speakers[0].id, seconds=0.25)
    assert loud_channels(eng.process(noise)) == {(left.id, 0)}
    for _ in range(4):                                       # the test sound is over
        outs = eng.process(noise)
    assert loud_channels(outs) == set()
    # a sound of the user's own plays sample for sample, on that speaker alone
    clip = np.full(2400, 0.25)
    eng.identify(right.speakers[1].id, kind="custom", samples=clip)
    outs = eng.process(np.zeros((2400, 8)))
    assert loud_channels(outs) == {(right.id, 1)}
    assert np.allclose(outs[right.id][1200:, 1], 0.25, atol=1e-3)


def test_clicking_the_left_speaker_never_sounds_the_right_one():
    """The bug: with the test signal as source, the left speaker's test was
    followed by the test signal stepping on to the right speaker."""
    state_module.config_dir = lambda d=tempfile.mkdtemp(): d
    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    fake = FakeSoundDevice([{"name": "Speakers (Realtek(R) Audio)", "outputs": 2},
                            {"name": "Mixer", "inputs": 2, "silent": True}])
    backend._sd = lambda: fake
    from speakerweave.ui.state import AppState
    state = AppState("")
    state.settings.default_output = False
    state.scan_devices()
    proj = state.project
    proj.input_kind, proj.input_name = "test", ""
    dev = proj.add_device("Speakers (Realtek(R) Audio)", 2)
    proj.set_role(dev.speakers[0], "FL")
    proj.set_role(dev.speakers[1], "FR")
    state.touch_streams()
    state.identify(dev.speakers[0].id, "noise")
    assert state.runner.running and state.engine.test_only
    pump(app, 2.6)
    assert not state.runner.running and not state.engine.test_only
    played = np.concatenate(fake.streams["Speakers (Realtek(R) Audio)"].recorded)
    assert np.abs(played[:, 0]).max() > 0.01
    assert np.abs(played[:, 1]).max() == 0.0
    # pressing Start afterwards plays the source normally again
    state.start()
    assert not state.engine.test_only
    state.stop()


# ------------------------------------------------------------------ the user's own test sounds

def _write_wav(path, samples, rate, kind):
    """kind: u8, i16, i24, i32, f32 or ext16 (extensible header)."""
    ch = samples.shape[1]
    if kind == "u8":
        data, tag, bits = (np.round(samples * 127) + 128).astype(np.uint8).tobytes(), 1, 8
    elif kind in ("i16", "ext16"):
        data, tag, bits = np.round(samples * 32767).astype("<i2").tobytes(), 1, 16
    elif kind == "i24":
        whole = np.round(samples * (2 ** 23 - 1)).astype("<i4").reshape(-1)
        data = b"".join(int(v & 0xFFFFFF).to_bytes(3, "little") for v in whole)
        tag, bits = 1, 24
    elif kind == "i32":
        data, tag, bits = np.round(samples * (2 ** 31 - 1)).astype("<i4").tobytes(), 1, 32
    else:
        data, tag, bits = samples.astype("<f4").tobytes(), 3, 32
    align = ch * bits // 8
    if kind == "ext16":
        fmt = struct.pack("<HHIIHHHHI", 0xFFFE, ch, rate, rate * align, align, bits, 22, bits, 0)
        fmt += struct.pack("<H", 1) + b"\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"
    else:
        fmt = struct.pack("<HHIIHH", tag, ch, rate, rate * align, align, bits)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
    body += b"LIST" + struct.pack("<I", 4) + b"INFO"                  # a chunk to skip
    body += b"data" + struct.pack("<I", len(data)) + data
    with open(path, "wb") as fh:
        fh.write(b"RIFF" + struct.pack("<I", len(body)) + body)


def test_wav_files_of_every_common_kind_are_read():
    folder = tempfile.mkdtemp()
    t = np.arange(4410) / 44100.0
    wave2 = np.stack([0.5 * np.sin(2 * np.pi * 440 * t), -0.25 * np.ones_like(t)], axis=1)
    for kind in ("u8", "i16", "ext16", "i24", "i32", "f32"):
        path = os.path.join(folder, f"{kind}.wav")
        _write_wav(path, wave2, 44100, kind)
        got, rate = sounds.read_wav(path)
        assert rate == 44100 and got.shape == wave2.shape, kind
        assert np.abs(got - wave2).max() < (0.01 if kind == "u8" else 1e-3), kind
    bad = os.path.join(folder, "bad.wav")
    with open(bad, "wb") as fh:
        fh.write(b"not a sound")
    try:
        sounds.decode(bad)
        assert False, "a broken file must be refused"
    except ValueError:
        pass


def test_a_chosen_sound_is_trimmed_shaped_and_kept_as_a_copy():
    folder, config = tempfile.mkdtemp(), tempfile.mkdtemp()
    rate = 44100
    quiet = np.zeros((rate // 2, 1))
    tone = 0.9 * np.sin(2 * np.pi * 300 * np.arange(rate) / rate)[:, None]
    path = os.path.join(folder, "My voice saying left.wav")
    _write_wav(path, np.concatenate([quiet, tone, quiet]), rate, "i16")
    entry, cut = sounds.add(path, 2, config)
    assert not cut and entry["name"] == "My voice saying left"
    assert abs(entry["seconds"] - 1.0) < 0.02                  # the silence before and after is gone
    os.remove(path)                                            # the original may go away
    at48 = sounds.load(entry, config, 48000)
    assert abs(len(at48) - 48000) < 100 and 0.45 < np.abs(at48).max() <= 0.51
    at44 = sounds.load(entry, config, 44100)
    assert abs(len(at44) - 44100) < 100
    assert at48[0] == 0.0                                      # faded in, no click
    # longer than the limit: the start is kept
    long_path = os.path.join(folder, "long.wav")
    _write_wav(long_path, 0.3 * np.ones((int(rate * (sounds.MAX_SECONDS + 3)), 1)), rate, "i16")
    entry, cut = sounds.add(long_path, 4, config)
    assert cut and abs(entry["seconds"] - sounds.MAX_SECONDS) < 0.05
    sounds.remove(entry, config)
    assert sounds.load(entry, config) is None
    assert sounds.clean_slots([{"name": "a", "file": "b"}, "junk", None]) == [
        {"name": "a", "file": "b", "seconds": 0.0}, {}, {}, {}, {}]


def test_own_sounds_are_offered_and_played_on_one_speaker():
    state_module.config_dir = lambda d=tempfile.mkdtemp(): d
    config = state_module.config_dir()
    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    fake = FakeSoundDevice([{"name": "Speakers (Realtek(R) Audio)", "outputs": 2},
                            {"name": "Mixer", "inputs": 2, "silent": True}])
    backend._sd = lambda: fake
    from speakerweave.ui.state import AppState
    state = AppState("")
    state.settings.default_output = False
    state.scan_devices()
    proj = state.project
    dev = proj.add_device("Speakers (Realtek(R) Audio)", 2)
    proj.set_role(dev.speakers[0], "FL")
    proj.set_role(dev.speakers[1], "FR")
    state.touch_streams()
    source = os.path.join(tempfile.mkdtemp(), "Ding.wav")
    _write_wav(source, 0.4 * np.sin(2 * np.pi * 880 * np.arange(24000) / 48000)[:, None], 48000, "i16")
    entry, _ = sounds.add(source, 0, config)
    state.settings.test_sounds[0] = entry
    assert ("custom1", "Ding") in state.test_sound_choices()
    assert len(state.test_sound_choices()) == 3
    state.identify(dev.speakers[1].id, "custom1")
    assert state.runner.running
    pump(app, 1.3)
    assert not state.runner.running
    played = np.concatenate(fake.streams["Speakers (Realtek(R) Audio)"].recorded)
    assert np.abs(played[:, 1]).max() > 0.2 and np.abs(played[:, 0]).max() == 0.0
    # an empty place says so instead of playing
    notes = []
    state.notice.connect(notes.append)
    state.identify(dev.speakers[1].id, "custom3")
    assert notes and "empty" in notes[-1] and not state.runner.running


# ------------------------------------------------------------------ colour themes

def test_every_preset_is_readable():
    for key, (name, note, colors) in theme.PRESETS.items():
        pal = theme.palette(colors)
        assert theme.contrast(pal["TEXT"], pal["PANEL"]) >= 7.0, key
        assert theme.contrast(pal["TEXT"], pal["BG"]) >= 7.0, key
        assert theme.contrast(pal["DIM"], pal["PANEL"]) >= 4.0, key
        assert theme.contrast(pal["ON_ACCENT"], pal["ACCENT"]) >= 4.5, key
        assert theme.contrast(pal["ACCENT"], pal["PANEL"]) >= 3.0, key
    assert len(theme.PRESETS) == 6
    # the original look is kept exactly
    pal = theme.palette(theme.PRESETS["midnight"][2])
    assert pal["PANEL_2"] == "#232831" and pal["DIM"] == "#8d96a5" and pal["DEVICE"] == "#2a3040"


def test_colours_from_adobe_color():
    codes = theme.parse_hex_list("#264653, 2A9D8F; e9c46a #F4A261 E76F51 and #abc")
    assert codes == ["#264653", "#2a9d8f", "#e9c46a", "#f4a261", "#e76f51", "#aabbcc"]
    assert theme.parse_hex_list("nothing here 1234567") == []
    for light in (False, True):
        c = theme.colors_from_swatches(codes[:5], light)
        assert set(c) == set(theme.THEME_KEYS)
        assert theme.contrast(c["text"], c["bg"]) >= 7.0
        assert theme.contrast(c["accent"], c["panel"]) >= 3.0
        assert (theme.luminance(c["bg"]) > 0.5) == light
    # an .ase file, the way Adobe apps save a theme
    blocks = []
    for name, rgb in (("Deep", (0.15, 0.27, 0.33)), ("Sea", (0.16, 0.62, 0.56))):
        title = (name + "\0").encode("utf-16-be")
        body = struct.pack(">H", len(title) // 2) + title + b"RGB " + struct.pack(">3f", *rgb) + b"\0\2"
        blocks.append(struct.pack(">HI", 1, len(body)) + body)
    group = (("Theme\0").encode("utf-16-be"))
    start = struct.pack(">HI", 0xC001, 2 + len(group)) + struct.pack(">H", len(group) // 2) + group
    end = struct.pack(">HI", 0xC002, 0)
    data = b"ASEF" + struct.pack(">HHI", 1, 0, 4) + start + b"".join(blocks) + end
    path = os.path.join(tempfile.mkdtemp(), "theme.ase")
    with open(path, "wb") as fh:
        fh.write(data)
    assert theme.read_ase(path) == ["#264554", "#299e8f"]


def test_saved_theme_choice_is_used():
    from speakerweave.settings import AppSettings
    s = AppSettings()
    assert theme.colors_for(s) == theme.PRESETS["midnight"][2]
    s.theme = "daylight"
    assert theme.colors_for(s)["bg"] == "#eef1f5"
    s.theme, s.custom_colors = "custom", {"accent": "#ff0000", "text": "not a colour"}
    c = theme.colors_for(s)
    assert c["accent"] == "#ff0000" and c["text"] == theme.PRESETS["midnight"][2]["text"]


# ------------------------------------------------------------------ Windows default output

class FakeWindows:
    """Stands in for the parts of windefault that talk to Windows."""

    def __init__(self, outputs, default):
        self.outputs = outputs                      # [(id, name)]
        self.current = {"0": default, "1": default, "2": default}
        self.calls = []

    def install(self, monkeypatch):
        monkeypatch.setattr(windefault, "supported", lambda: True)
        monkeypatch.setattr(windefault, "list_outputs", lambda: list(self.outputs))
        monkeypatch.setattr(windefault, "defaults", lambda: dict(self.current))
        monkeypatch.setattr(windefault, "set_default", self.set_default)

    def set_default(self, dev_id, roles=windefault.ROLES):
        self.calls.append((dev_id, tuple(roles)))
        for role in roles:
            self.current[str(role)] = dev_id


def test_what_windows_should_play_into():
    from speakerweave.model import Project
    from types import SimpleNamespace as NS
    p = Project()
    loops = [NS(name="Speakers (Realtek(R) Audio) [Loopback]"),
             NS(name="CABLE Input (VB-Audio Virtual Cable) [Loopback]")]
    # on the test signal, the virtual device is picked
    assert default_output.plan(p, loops) == ("CABLE Input (VB-Audio Virtual Cable)",
                                             "CABLE Input (VB-Audio Virtual Cable) [Loopback]", "")
    # listening to a device that is also one of the speakers would echo
    dev = p.add_device("Speakers (Realtek(R) Audio)", 2)
    p.input_kind, p.input_name = "loopback", "Speakers (Realtek(R) Audio) [Loopback]"
    device, _, problem = default_output.plan(p, loops)
    assert device == "" and "one of your speakers" in problem
    dev.enabled = False
    assert default_output.plan(p, loops)[0] == "Speakers (Realtek(R) Audio)"
    # a microphone or line in: nothing to change
    p.input_kind, p.input_name = "device", "Line in"
    assert default_output.plan(p, loops) == ("", "", "")
    p.input_kind = "test"
    assert "VB-CABLE" in default_output.plan(p, loops[:1])[2]


def test_default_output_is_set_and_given_back(monkeypatch):
    from speakerweave.settings import AppSettings
    win = FakeWindows([("{spk}", "Speakers (Realtek(R) Audio)"),
                       ("{cable}", "CABLE Input (VB-Audio Virtual Cable)")], "{spk}")
    win.install(monkeypatch)
    s = AppSettings()
    changed, problem = default_output.apply(s, "CABLE Input (VB-Audio Virtual Cable)")
    assert changed and not problem and win.current == {"0": "{cable}", "1": "{cable}", "2": "{cable}"}
    assert s.managed_output == "{cable}" and s.previous_outputs == {"0": "{spk}", "1": "{spk}", "2": "{spk}"}
    # opening again (the next boot) changes nothing and keeps what to give back
    changed, _ = default_output.apply(s, "CABLE Input (VB-Audio Virtual Cable)")
    assert not changed and s.previous_outputs["0"] == "{spk}"
    # someone picked their headphones for calls in the meantime: that one is left alone
    win.current["2"] = "{spk}"
    assert default_output.restore(s)
    assert win.current == {"0": "{spk}", "1": "{spk}", "2": "{spk}"}
    assert win.calls[-1] == ("{spk}", (1,)) and s.managed_output == ""
    # a name Windows does not know
    assert default_output.apply(s, "Gone device") == (False, "Windows has no output called Gone "
                                                              "device right now.")
    assert windefault.find("CABLE Input (VB-Audio Virtual", win.outputs) == "{cable}"


def test_settings_page_look_sounds_and_output(monkeypatch):
    state_module.config_dir = lambda d=tempfile.mkdtemp(): d
    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    fake = FakeSoundDevice([{"name": "Speakers (Realtek(R) Audio)", "outputs": 2},
                            {"name": "Mixer", "inputs": 2, "silent": True}])
    backend._sd = lambda: fake
    from speakerweave.ui.state import AppState
    from speakerweave.ui.window import MainWindow
    state = AppState("")
    state.settings.remote_port = free_port()
    state.settings.default_output = False
    win = MainWindow(state)
    win.show()
    pump(app, 0.2)
    sp = win.settings_page
    assert "Eli Smart" in sp.findChildren(type(sp.version))[-1].text() or any(
        "Eli Smart" in w.text() for w in sp.findChildren(type(sp.version)))
    # a preset
    sp.theme_box.setCurrentIndex(sp.theme_box.findData("daylight"))
    sp._theme_chosen()
    assert state.settings.theme == "daylight" and theme.BG == "#eef1f5" and not theme.DARK
    assert sp.custom_box.isHidden()
    win.grab()
    # your own, from Adobe Color codes
    sp.theme_box.setCurrentIndex(sp.theme_box.findData("custom"))
    sp._theme_chosen()
    assert not sp.custom_box.isHidden() and state.settings.custom_colors["bg"] == "#eef1f5"
    sp.paste.setText("#264653 #2A9D8F #E9C46A #F4A261 #E76F51")
    sp._use_paste()
    assert state.settings.theme == "custom" and theme.ACCENT == state.settings.custom_colors["accent"]
    assert sp.color_btns["accent"].text() == theme.ACCENT.upper()
    win.grab()
    sp.theme_box.setCurrentIndex(0)
    sp._theme_chosen()
    assert theme.BG == "#14171c"
    # the sound rows
    assert [row[0].text() for row in sp.sound_rows] == ["Empty"] * 5
    assert not sp.sound_rows[0][2].isEnabled()
    # solo: every other speaker shows the mute look on the map
    dev = state.project.add_device("Speakers (Realtek(R) Audio)", 2)
    state.project.set_role(dev.speakers[0], "FL")
    state.project.set_role(dev.speakers[1], "FR")
    dev.kind = "external"
    dev.speakers[0].x, dev.speakers[0].y = -1.0, -1.0
    dev.speakers[1].x, dev.speakers[1].y = 1.0, -1.0
    dev.speakers[0].solo = True
    state.touch_routing()
    win.show_page(0)
    pump(app, 0.1)
    image = win.map.grab().toImage()
    from speakerweave.model import speaker_position
    from speakerweave.ui.roommap import R
    other = win.map.to_px(*speaker_position(dev, dev.speakers[1]))
    solo = win.map.to_px(*speaker_position(dev, dev.speakers[0]))
    pixel = image.pixelColor(int(other.x()), int(other.y() + R - 4)).name()
    assert pixel == theme.OFF_FILL
    assert image.pixelColor(int(solo.x()), int(solo.y() + R - 4)).name() != theme.OFF_FILL
    # the Windows output option, with a pretend Windows
    fake_win = FakeWindows([("{spk}", "Speakers (Realtek(R) Audio)"),
                            ("{cable}", "CABLE Input (VB-Audio Virtual Cable)")], "{spk}")
    fake_win.install(monkeypatch)
    monkeypatch.setattr(windefault, "default_output", lambda role=0: (
        fake_win.current["0"], dict(fake_win.outputs)[fake_win.current["0"]]))
    from types import SimpleNamespace as NS
    state.loopbacks = [NS(name="CABLE Input (VB-Audio Virtual Cable) [Loopback]")]
    monkeypatch.setattr(windefault, "channel_count", lambda dev_id: 8)
    runner = state.runner
    monkeypatch.setattr(runner, "start", lambda: (setattr(runner, "running", True), [])[1])
    monkeypatch.setattr(runner, "stop", lambda: setattr(runner, "running", False))
    state.project.input_kind = "test"
    sp.default_output.setChecked(False)
    sp.default_output.setChecked(True)
    # Windows is only pointed at SpeakerWeave while its sound runs
    assert state.settings.default_output and fake_win.current["0"] == "{spk}"
    sp._make_default(show=False)                    # Set it now: starts the sound
    assert runner.running and fake_win.current["0"] == "{cable}"
    assert state.project.input_kind == "loopback" and "CABLE" in state.project.input_name
    assert "CABLE Input" in sp.output_state.text()
    state.stop()                                    # stopping gives Windows its output back
    assert fake_win.current["0"] == "{spk}"
    state.start()
    assert fake_win.current["0"] == "{cable}"
    sp.default_output.setChecked(False)
    assert fake_win.current["0"] == "{spk}"
    state.stop()
    win.close()
