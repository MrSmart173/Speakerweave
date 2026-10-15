"""A 2.1 speaker system that Windows offers as 7.1 (a Logitech G560) is shown and played
as what it is: two loose speakers and a subwoofer, not a surround shape."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from speakerweave import speaker_library
from speakerweave.engine import Engine
from speakerweave.model import (OFF, Project, TWO_ONE, is_shape, is_sub, set_attached,
                                speaker_position)

G560 = "Speakers (G560 Gaming Speaker)"


def add_g560(project, channels=8):
    dev = project.add_device(G560, channels)
    entry = speaker_library.recognise(G560)
    speaker_library.apply_model(dev, entry, project)
    return dev


def test_a_g560_offered_as_7_1_is_two_speakers_and_a_subwoofer():
    p = Project()
    p.set_mode("5.1")
    dev = add_g560(p)
    assert dev.channels == 8                      # Windows still gets the 8 channels it wants
    assert [(s.channel, s.name, s.role) for s in dev.speakers] == [
        (0, "Left", "FL"), (1, "Right", "FR"), (3, "Sub", "LFE")]
    assert not is_shape(dev)
    assert dev.kind == "external" and dev.layout == TWO_ONE
    left, right, sub = (speaker_position(dev, s) for s in dev.speakers)
    assert left[0] < right[0] and left[1] == right[1] < p.listener_y    # a pair in front of you
    assert len({left, right, sub}) == 3


def test_the_mode_is_left_alone_and_the_subwoofer_waits_for_one():
    p = Project()
    p.set_mode("2.0")
    dev = add_g560(p)
    assert p.mode == "2.0"
    assert [s.role for s in dev.speakers] == ["FL", "FR", OFF]


def test_a_saved_g560_shape_becomes_its_real_speakers_and_keeps_their_settings():
    p = Project()
    p.set_mode("5.1")
    dev = p.add_device(G560, 8)                   # as it was added before this fix
    dev.model = "logitech_g560"
    assert is_shape(dev)
    left = dev.speakers[0]
    left.gain_db = -4.0
    assert [d.title for d in speaker_library.fix_layouts(p)] == [dev.title]
    assert dev.speakers[0] is left and left.gain_db == -4.0
    assert [s.channel for s in dev.speakers] == [0, 1, 3]
    assert speaker_library.fix_layouts(p) == []   # only once


def test_windows_channel_changes_keep_the_three_speakers():
    p = Project()
    p.set_mode("5.1")
    dev = add_g560(p)
    ids = [s.id for s in dev.speakers]
    assert not p.set_device_channels(dev, 8)      # a rescan adds nothing back
    assert p.set_device_channels(dev, 6)          # Windows set it to 5.1
    assert [s.channel for s in dev.speakers] == [0, 1, 3] and [s.id for s in dev.speakers] == ids
    assert p.set_device_channels(dev, 2)          # stereo: no subwoofer channel
    assert [s.channel for s in dev.speakers] == [0, 1]
    assert p.set_device_channels(dev, 8)          # 7.1 again: the subwoofer is back
    assert [(s.channel, s.role) for s in dev.speakers] == [(0, "FL"), (1, "FR"), (3, "LFE")]
    assert not is_shape(dev)


def test_it_plays_on_its_own_channels_only():
    p = Project(input_kind="loopback", master_db=0.0, bass_redirect=False)
    p.set_mode("5.1")
    dev = add_g560(p)
    for spk in dev.speakers:
        spk.hp_on = spk.lp_on = False
    eng = Engine(p)
    eng.configure(48000.0, 8)
    t = np.arange(480) / 48000.0
    out = None
    for b in range(100):
        block = np.zeros((480, 8), dtype=np.float32)
        block[:, 0] = 0.3 * np.sin(2 * np.pi * 440 * (t + b * 480 / 48000.0))     # front left
        block[:, 3] = 0.3 * np.sin(2 * np.pi * 50 * (t + b * 480 / 48000.0))      # subwoofer
        out = eng.process(block)
    played = np.abs(out[dev.id]).max(axis=0)
    assert out[dev.id].shape == (480, 8)
    assert played[0] > 0.01 and played[3] > 0.01
    assert played[1] < 0.01 and all(played[ch] < 1e-6 for ch in (2, 4, 5, 6, 7))


def test_attached_its_speakers_are_the_ends_and_the_subwoofer_the_middle():
    p = Project()
    p.set_mode("5.1")
    dev = add_g560(p)
    set_attached(dev, True)
    left, right, sub = (speaker_position(dev, s) for s in dev.speakers)
    assert abs((left[0] + right[0]) / 2 - sub[0]) < 1e-9
    assert abs(right[0] - left[0] - dev.width) < 1e-9


def test_real_surround_systems_are_still_shapes():
    p = Project()
    p.set_mode("5.1")
    z906 = p.add_device("Speakers (Z906)", 6)
    assert is_shape(z906)
    stereo = p.add_device("Speakers (DELL P2424HT)", 2)
    assert not is_shape(stereo)
    assert all(not is_sub(s.role) for s in stereo.speakers)


def test_ticking_a_g560_in_the_app_keeps_the_mode_and_draws_three_speakers():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from test_hidden_outputs import pump, window
    app, state, win = window([{"name": G560, "outputs": 8}, {"name": "Monitor", "outputs": 2}])
    try:
        state.project.set_mode("2.1")
        dev = win._add_output(G560, 8)
        pump(app, 0.2)
        assert state.project.mode == "2.1"
        assert [(s.name, s.role) for s in dev.speakers] == [("Left", "FL"), ("Right", "FR"), ("Sub", "LFE")]
        assert not is_shape(dev) and dev.kind == "external"
        shot = os.environ.get("SPEAKERWEAVE_SHOT")
        if shot:
            win.grab().save(shot)
    finally:
        win.close()
        state.stop()
        pump(app, 0.1)


def test_a_headset_offered_as_7_1_is_its_two_sides():
    """Logitech G HUB, Corsair iCUE and Razer Synapse can make Windows offer a headset as 7.1."""
    p = Project()
    p.set_mode("5.1")
    name = "Speakers (PRO X Wireless Gaming Headset)"
    dev = p.add_device(name, 8)
    speaker_library.apply_model(dev, speaker_library.recognise(name), p)
    assert [(s.channel, s.role) for s in dev.speakers] == [(0, "FL"), (1, "FR")]
    assert not is_shape(dev) and dev.kind == "builtin" and p.mode == "5.1"


def test_a_pc_soundbar_taking_5_1_is_a_bar_and_its_subwoofer():
    p = Project()
    p.set_mode("5.1")
    name = "Speakers (Sound Blaster Katana V2)"
    dev = p.add_device(name, 6)
    speaker_library.apply_model(dev, speaker_library.recognise(name), p)
    assert [(s.channel, s.role) for s in dev.speakers] == [(0, "FL"), (1, "FR"), (3, "LFE")]
    assert dev.kind == "builtin" and not is_shape(dev)
    left, right, sub = (speaker_position(dev, s) for s in dev.speakers)
    assert abs((left[0] + right[0]) / 2 - sub[0]) < 1e-9          # the subwoofer under the bar


def test_real_surround_and_sound_cards_keep_every_channel():
    p = Project()
    p.set_mode("5.1")
    arena = p.add_device("Speakers (SteelSeries Arena 9)", 6)      # a real 5.1 system
    speaker_library.apply_model(arena, speaker_library.recognise(arena.name), p)
    assert len(arena.speakers) == 6 and is_shape(arena)
    tv = p.add_device("LG TV SSCR2 (NVIDIA High Definition Audio)", 8)   # a sound system on eARC
    speaker_library.apply_model(tv, speaker_library.recognise(tv.name), p)
    assert len(tv.speakers) == 8
    card = p.add_device("Speakers (Realtek(R) Audio)", 8)
    # headphones picked by hand for the green jack of a 7.1 card: the card's other jacks stay
    speaker_library.apply_model(card, speaker_library.BY_KEY["headphones"], p)
    speaker_library.apply_model(card, speaker_library.BY_KEY["logitech_g560"], p)
    assert len(card.speakers) == 8


def test_not_chosen_brings_every_channel_back_for_good():
    p = Project()
    p.set_mode("5.1")
    dev = add_g560(p)
    assert p.use_all_channels(dev)
    assert [s.channel for s in dev.speakers] == list(range(8)) and is_shape(dev)
    assert speaker_library.fix_layouts(p) == []                    # your choice stays
    assert not p.set_device_channels(dev, 8)


def test_every_library_layout_is_one_the_app_knows():
    from speakerweave.model import REAL_SPEAKERS
    for entry in speaker_library.LIBRARY:
        assert entry.layout in ("",) + tuple(REAL_SPEAKERS), entry.key
        if entry.layout:
            assert entry.patterns, f"{entry.key}: only an output recognised by name is fitted"
