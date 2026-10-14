"""Attaching and detaching speakers, surround systems as a shape, outputs that
gain channels, and the level meters."""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

from speakerweave.model import (Project, SHAPE_RADIUS, can_move_alone, is_shape, set_attached,
                                speaker_angle, speaker_distance, speaker_position)


def near(a, b, tol=0.02):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def test_detached_speakers_come_back_to_their_own_spots():
    p = Project(mode="2.0")
    tv = p.add_device("TV", 2)
    left, right = tv.speakers
    on_unit = [speaker_position(tv, s) for s in tv.speakers]
    set_attached(tv, False)                     # first time: they start where they were drawn
    assert [speaker_position(tv, s) for s in tv.speakers] == on_unit
    left.x, left.y = -2.0, 0.5                  # the user drags them to their real spots
    right.x, right.y = 2.0, 0.5
    tv.x, tv.y = 0.3, -1.0                      # and moves the screen too
    set_attached(tv, True)                      # snap back onto the screen, the screen stays put
    assert (tv.x, tv.y) == (0.3, -1.0)
    assert near(speaker_position(tv, left), (0.3 - tv.width / 2, -1.0))
    set_attached(tv, False)                     # loose again: back where they were before
    assert speaker_position(tv, left) == (-2.0, 0.5) and speaker_position(tv, right) == (2.0, 0.5)
    again = Project.from_json(p.to_json())
    assert again.devices[0].free_placed
    old = p.to_json().replace('"free_placed": true', '"x_unused": 1')
    assert Project.from_json(old).devices[0].free_placed      # older loose setups keep their spots


def test_a_surround_system_is_a_shape_around_the_listener():
    p = Project(mode="5.1", surround_rear=True)
    z = p.add_device("Logitech Z906", 6)
    assert is_shape(z) and z.kind == "builtin" and (z.x, z.y) == (p.listener_x, p.listener_y)
    roles = [s.role for s in z.speakers]
    assert roles == ["FL", "FR", "FC", "LFE", "BL", "BR"]
    for spk in z.speakers:
        if spk.role in ("FL", "FR", "FC", "BL", "BR"):
            assert abs(speaker_distance(p, z, spk) - SHAPE_RADIUS) < 0.05
    fl, fr, c, sub, bl, br = z.speakers
    assert abs(speaker_angle(p, z, fl) + 30) < 1 and abs(speaker_angle(p, z, br) - 150) < 1
    sx, sy = speaker_position(z, sub)
    assert sx < speaker_position(z, fl)[0]       # the subwoofer sits off to the left
    assert not any(can_move_alone(z, s) for s in z.speakers)
    z.rotation = 90.0                           # turned, the shape turns as one
    assert abs(speaker_angle(p, z, c) - 90) < 1
    z.rotation = 0.0
    p.set_role(bl, "SL")                        # a new role moves the speaker to that spot
    assert abs(speaker_angle(p, z, bl) + 90) < 1
    set_attached(z, False)
    assert all(can_move_alone(z, s) for s in z.speakers)
    seven = p.add_device("Card 7.1", 8)
    assert is_shape(seven)


def test_an_output_that_gains_channels_gets_new_speakers_and_the_mode_follows():
    p = Project(mode="2.0")
    card = p.add_device("Speakers (Realtek(R) Audio)", 2)
    p.set_role(card.speakers[0], "FL")
    p.set_role(card.speakers[1], "FR")
    card.speakers[0].gain_db = -3.0             # settings of the old speakers are kept
    assert p.set_device_channels(card, 6)
    assert len(card.speakers) == 6 and card.channels == 6 and is_shape(card)
    assert card.speakers[0].gain_db == -3.0
    assert p.fit_mode_to(card)
    assert p.mode == "5.1" and p.surround_rear
    assert [s.role for s in card.speakers] == ["FL", "FR", "FC", "LFE", "BL", "BR"]
    assert not p.set_device_channels(card, 6)   # nothing new
    assert not p.fit_mode_to(card)


def test_level_meters_follow_the_engine():
    from speakerweave.ui import theme
    from speakerweave.ui.levels import DB_LOW, MeterBlock, to_db
    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    block = MeterBlock("Card", "6 channels")
    block.set_channels([("FL", "#4da3ff"), ("FR", "#ff6b6b")])
    block.resize(block.width(), 180)
    assert block.feed([0.5, 0.0], 0.03)
    assert abs(block.levels[0] - to_db(0.5)) < 0.01 and block.levels[1] == DB_LOW
    block.feed([0.0, 0.0], 0.1)                 # falls gently, the peak line holds
    assert to_db(0.5) - 3.5 < block.levels[0] < to_db(0.5) and abs(block.peaks[0] - to_db(0.5)) < 0.01
    block.grab()
    assert to_db(0.0) == DB_LOW and abs(to_db(1.0)) < 1e-9
