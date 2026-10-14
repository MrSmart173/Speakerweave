"""Offline tests of the mixing engine. Run with:  python -m pytest tests"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from speakerweave.dsp import PinkNoise, SpeakerChain, response_db
from speakerweave.engine import AdaptiveFifo, Engine
from speakerweave.mixer import build_matrix
from speakerweave.model import (MODES, SOURCE_LAYOUTS, Project, Speaker, auto_align_delays,
                                auto_assign_roles, can_move_alone, move_speaker,
                                partner_speaker, speaker_position)
from speakerweave.rgb import led_colors, level_to_unit

SR = 48000.0
S71 = SOURCE_LAYOUTS["7.1"]
S51 = SOURCE_LAYOUTS["5.1"]
ST = SOURCE_LAYOUTS["stereo"]


def row(m, roles, role):
    return m[roles.index(role)]


def rms_db(x):
    return 20 * math.log10(max(float(np.sqrt(np.mean(np.square(x)))), 1e-12))


def sine(freq, seconds=1.0, amp=0.5):
    t = np.arange(int(seconds * SR)) / SR
    return amp * np.sin(2 * np.pi * freq * t)


def run_chain(spk, x, block=480):
    chain = SpeakerChain(SR)
    chain.configure(spk)
    return np.concatenate([chain.process(x[i:i + block]) for i in range(0, len(x), block)])


# ------------------------------------------------------------------ mixing matrix

def test_same_layout_is_passed_straight_through():
    for name, src in SOURCE_LAYOUTS.items():
        room = [r for r in src]
        m = build_matrix(src, room, bass_redirect=False)
        assert np.allclose(m, np.eye(len(src))), name


def test_surround_folds_down_to_stereo_without_losing_anything():
    room = MODES["2.0"][1]
    m = build_matrix(S71, room)
    fl, fr = row(m, room, "FL"), row(m, room, "FR")
    assert fl[S71.index("FL")] == 1 and fr[S71.index("FR")] == 1
    assert abs(fl[S71.index("FC")] - 0.7071) < 1e-3 and abs(fr[S71.index("FC")] - 0.7071) < 1e-3
    for left in ("SL", "BL"):
        assert fl[S71.index(left)] > 0 and fr[S71.index(left)] == 0
    assert np.all(m.sum(axis=0) > 0), "every incoming channel must be heard somewhere"


def test_stereo_is_spread_to_every_speaker_when_upmix_is_on():
    room = MODES["7.1"][1]
    m = build_matrix(ST, room)
    assert np.all(np.abs(m).sum(axis=1) > 0)
    assert row(m, room, "SL")[1] == 0 and row(m, room, "SR")[0] == 0   # left stays left
    off = build_matrix(ST, room, upmix=False, bass_redirect=False)
    assert np.abs(off).sum() == 2.0                                    # only the fronts


def test_no_role_is_fed_twice_by_fold_down_plus_upmix():
    room = MODES["6.1"][1]
    m = build_matrix(S71, room, bass_redirect=False)
    bc = row(m, room, "BC")
    assert abs(bc[S71.index("BL")] - 0.7071) < 1e-3 and abs(bc[S71.index("BR")] - 0.7071) < 1e-3
    room = MODES["5.1"][1]
    m = build_matrix(SOURCE_LAYOUTS["quad"], room, bass_redirect=False)
    assert row(m, room, "SL")[2] == 1.0


def test_subwoofer_gets_lfe_plus_redirected_bass():
    room = MODES["2.1"][1]
    m = build_matrix(ST, room, bass_redirect=True, bass_redirect_db=-6)
    assert np.allclose(row(m, room, "LFE"), [0.501, 0.501], atol=1e-3)
    m = build_matrix(S51, MODES["5.1"][1], bass_redirect=False)
    assert row(m, MODES["5.1"][1], "LFE")[S51.index("LFE")] == 1
    assert np.abs(row(m, MODES["5.1"][1], "LFE")).sum() == 1


def test_every_mode_and_source_combination_is_sane():
    for mode, (_, room) in MODES.items():
        for name, src in SOURCE_LAYOUTS.items():
            m = build_matrix(src, room)
            assert np.all(np.isfinite(m)) and np.all(m >= 0)
            assert np.all(m.sum(axis=0) > 0), (mode, name)
            assert m.max() <= 1.0 + 1e-9, (mode, name)


# ------------------------------------------------------------------ filters

def test_subwoofer_label_limits_the_speaker_to_low_notes():
    proj = Project(mode="2.1")
    spk = Speaker()
    proj.set_role(spk, "LFE")
    assert spk.hp_on and spk.lp_on and spk.hp_freq == 10 and spk.lp_freq == 75
    passed = rms_db(run_chain(spk, sine(40, 2.0))[48000:]) - rms_db(sine(40))
    blocked_high = rms_db(run_chain(spk, sine(600, 2.0))[48000:]) - rms_db(sine(600))
    blocked_low = rms_db(run_chain(spk, sine(2.5, 6.0))[4 * 48000:]) - rms_db(sine(2.5, 2.0))
    assert abs(passed) < 0.5, passed
    assert blocked_high < -60, blocked_high
    assert blocked_low < -40, blocked_low
    proj.set_role(spk, "FL")
    assert not spk.hp_on and not spk.lp_on


def test_custom_frequency_window():
    spk = Speaker(hp_on=True, hp_freq=200, hp_slope=48, lp_on=True, lp_freq=2000, lp_slope=48)
    f = np.array([50.0, 630.0, 8000.0])
    r = response_db(spk, SR, f)
    assert r[0] < -80 and abs(r[1]) < 0.1 and r[2] < -80


def test_eq_band_boosts_only_its_own_frequency():
    spk = Speaker()
    band = spk.eq[5]
    assert band.freq == 1000
    band.gain_db = 6.0
    boosted = rms_db(run_chain(spk, sine(1000))[24000:]) - rms_db(sine(1000))
    untouched = rms_db(run_chain(spk, sine(60))[24000:]) - rms_db(sine(60))
    assert abs(boosted - 6.0) < 0.1 and abs(untouched) < 0.1
    spk.eq_on = False
    assert abs(rms_db(run_chain(spk, sine(1000))[24000:]) - rms_db(sine(1000))) < 0.01


def test_shelves_and_graph_agree_with_the_audio():
    spk = Speaker()
    spk.eq[0].gain_db = -9.0        # low shelf at 31.5 Hz
    spk.eq[-1].gain_db = 4.0        # high shelf at 16 kHz
    r = response_db(spk, SR, np.array([10.0, 1000.0, 21000.0]))
    assert abs(r[0] + 9) < 0.6 and abs(r[1]) < 0.2 and abs(r[2] - 4) < 0.6
    measured = rms_db(run_chain(spk, sine(10, 4.0))[2 * 48000:]) - rms_db(sine(10, 2.0))
    assert abs(measured - r[0]) < 0.2


def test_delay_gain_and_polarity():
    spk = Speaker(delay_ms=10.0, gain_db=-6.0, invert=True)
    x = np.zeros(4800)
    x[4000] = 1.0                                   # after the fade in
    y = run_chain(spk, x)
    assert int(np.argmax(np.abs(y))) == 4000 + 480
    assert abs(y[4480] + 0.501) < 1e-3


def test_settings_can_change_while_audio_is_running():
    spk = Speaker()
    chain = SpeakerChain(SR)
    chain.configure(spk)
    x = sine(1000, 0.5)
    a = np.concatenate([chain.process(x[i:i + 480]) for i in range(0, 12000, 480)])
    spk.gain_db = -12
    spk.eq[5].gain_db = 3
    spk.delay_ms = 5
    chain.configure(spk)
    b = np.concatenate([chain.process(x[i:i + 480]) for i in range(12000, 24000, 480)])
    assert np.all(np.isfinite(b))
    assert abs((rms_db(b[6000:]) - rms_db(a[6000:])) + 9.0) < 0.2


# ------------------------------------------------------------------ whole engine

def three_tv_project():
    """The example from the brief: three TVs, six speakers, no centre, no sub."""
    proj = Project(mode="6.0", input_kind="test", master_db=0.0)
    left = proj.add_device("TV left", 2)
    mid = proj.add_device("TV middle", 2)
    right = proj.add_device("TV right", 2)
    wanted = {left.id: ("BL", "SL"), mid.id: ("FL", "FR"), right.id: ("SR", "BR")}
    for dev in proj.devices:
        for spk, role in zip(dev.speakers, wanted[dev.id]):
            proj.set_role(spk, role)
    return proj, left, mid, right


def test_three_tvs_each_channel_reaches_the_right_speaker():
    proj, left, mid, right = three_tv_project()
    eng = Engine(proj)
    eng.configure(SR, 8)
    expect = {"BL": (left.id, 0), "SL": (left.id, 1), "FL": (mid.id, 0),
              "FR": (mid.id, 1), "SR": (right.id, 0), "BR": (right.id, 1)}
    eng.process(np.zeros((4800, 8)))                # let the fade in finish
    for ch, role in enumerate(S71):
        block = np.zeros((480, 8), dtype=np.float32)
        block[:, ch] = 0.5
        outs = eng.process(block)
        loud = {(d, c) for d, o in outs.items() for c in range(o.shape[1]) if np.abs(o[:, c]).max() > 0.01}
        if role in expect:
            assert loud == {expect[role]}, (role, loud)
        elif role == "FC":
            assert loud == {(mid.id, 0), (mid.id, 1)}      # phantom centre
        elif role == "LFE":
            assert loud == {(mid.id, 0), (mid.id, 1)}      # no sub, so the fronts take it


def test_mute_solo_identify_and_disabled_devices():
    proj, left, mid, right = three_tv_project()
    eng = Engine(proj)
    eng.configure(SR, 8)
    noise = (PinkNoise(1).block(4800)[:, None] * 0.1) * np.ones((1, 8))

    def loud():
        eng.process(noise)
        outs = eng.process(noise)
        return {(d, c) for d, o in outs.items() for c in range(o.shape[1]) if np.abs(o[:, c]).max() > 1e-4}

    assert len(loud()) == 6
    mid.speakers[0].mute = True
    eng.rebuild()
    assert (mid.id, 0) not in loud() and len(loud()) == 5
    mid.speakers[0].mute = False
    left.speakers[1].solo = True
    eng.rebuild()
    assert loud() == {(left.id, 1)}
    left.speakers[1].solo = False
    right.enabled = False
    eng.rebuild()
    assert {d for d, _ in loud()} == {left.id, mid.id}
    right.enabled = True
    eng.rebuild()
    eng.identify(right.speakers[1].id, seconds=5)
    assert loud() == {(right.id, 1)}


def test_output_never_exceeds_full_scale():
    proj, *_ = three_tv_project()
    proj.master_db = 12
    eng = Engine(proj)
    eng.configure(SR, 8)
    for _ in range(20):
        outs = eng.process(np.ones((480, 8), dtype=np.float32))
    assert all(np.abs(o).max() <= 1.0 for o in outs.values())


# ------------------------------------------------------------------ device sync

def simulate(ppm, seconds=180, write_block=480, read_block=512, target_ms=60):
    """Engine clock at 48000, sound card clock off by ppm parts per million."""
    fifo = AdaptiveFifo(1, SR, target_ms)
    card_rate = SR * (1 + ppm * 1e-6)
    t_write = t_read = 0.0
    phase = 0
    fills, out = [], []
    while t_write < seconds:
        if t_write <= t_read:
            n = np.arange(phase, phase + write_block)
            fifo.write(np.sin(2 * np.pi * 1000 * n / SR).astype(np.float32)[:, None])
            phase += write_block
            t_write += write_block / SR
        else:
            out.append(fifo.read(read_block)[:, 0])
            fills.append(fifo.fill_ms)
            t_read += read_block / card_rate
    return fifo, np.array(fills), np.concatenate(out)


def test_devices_with_different_clocks_stay_in_step():
    for ppm in (-400, -50, 0, 50, 400):
        fifo, fills, out = simulate(ppm)
        assert fifo.underruns == 0 and fifo.overruns == 0, (ppm, fifo.underruns, fifo.overruns)
        late = fills[len(fills) // 2:]
        assert late.min() > 25 and late.max() < 95, (ppm, late.min(), late.max())
        # a slow card (negative ppm) leaves audio piling up, so playback speeds up
        assert abs((fifo.ratio - 1) * 1e6 + ppm) < 40, (ppm, (fifo.ratio - 1) * 1e6)
        tail = out[-48000:]
        spectrum = np.abs(np.fft.rfft(tail * np.hanning(len(tail))))
        peak = int(np.argmax(spectrum))
        tone = np.sum(spectrum[peak - 4:peak + 5] ** 2)
        rest = np.sum(spectrum ** 2) - tone
        assert 10 * math.log10(tone / rest) > 40, ppm      # clean tone, no glitches


def test_drifting_devices_end_up_lined_up_with_each_other():
    """After a while a slow card and a fast card sit at the same delay."""
    means = []
    for ppm in (-300, 300):
        fifo, fills, _ = simulate(ppm, seconds=600)
        assert fifo.underruns == 0 and fifo.overruns == 0
        means.append(float(np.mean(fills[-len(fills) // 10:])))
    assert abs(means[0] - means[1]) < 1.0, means
    assert abs(means[0] - 60.0) < 2.0, means


def test_a_device_that_stalls_jumps_back_into_line():
    """One sound card freezes for 40 ms. It must not stay 40 ms late."""
    fifo = AdaptiveFifo(1, SR, 60)
    one = np.ones((480, 1), dtype=np.float32)

    def run(blocks):
        fills = []
        for _ in range(blocks):
            fifo.write(one)
            fifo.read(480)
            fills.append(fifo.fill_ms)
        return fills

    run(300)
    assert abs(fifo.fill_ms - 60) < 12
    for _ in range(4):                      # the card takes nothing for 40 ms
        fifo.write(one)
    assert fifo.fill_ms > 90
    fills = run(300)                        # three seconds later
    assert abs(np.mean(fills[-50:]) - 60) < 8, np.mean(fills[-50:])
    assert fifo.resyncs == 1


def test_buffer_recovers_after_the_input_stops_and_restarts():
    fifo = AdaptiveFifo(2, SR, 40)
    one = np.ones((480, 2), dtype=np.float32)
    for _ in range(10):
        fifo.write(one)
    assert fifo.read(480).max() == 1.0
    for _ in range(10):
        got = fifo.read(480)
    assert got.max() == 0.0 and fifo.underruns >= 1
    for _ in range(10):
        fifo.write(one)
    assert fifo.read(480).max() == 1.0
    for _ in range(1000):                         # sound card stalls: no reads
        fifo.write(one)
    assert fifo.fill_ms < 200 and fifo.overruns > 0


# ------------------------------------------------------------------ room layout

def test_auto_assign_matches_the_three_tv_example():
    proj, left, mid, right = three_tv_project()
    for _, spk in proj.all_speakers():
        spk.role = "FL"                             # scramble
    proj.listener_x, proj.listener_y = 0.0, 0.0
    mid.x, mid.y, mid.rotation, mid.width = 0.0, -1.2, 0.0, 1.0
    left.x, left.y, left.rotation, left.width = -1.15, -0.45, -60.0, 1.0
    right.x, right.y, right.rotation, right.width = 1.15, -0.45, 60.0, 1.0
    auto_assign_roles(proj)
    assert [s.role for s in left.speakers] == ["BL", "SL"]
    assert [s.role for s in mid.speakers] == ["FL", "FR"]
    assert [s.role for s in right.speakers] == ["SR", "BR"]


def test_auto_assign_keeps_the_subwoofer_and_fills_every_role():
    proj = Project(mode="5.1")
    amp = proj.add_device("Sound card", 6)
    amp.kind = "external"
    spots = [(-1, -2), (1, -2), (0, -2.2), (2, 2), (-2, 0.6), (2, 0.6)]
    for spk, (x, y) in zip(amp.speakers, spots):
        spk.x, spk.y = x, y
    assert amp.speakers[3].role == "LFE"
    auto_assign_roles(proj)
    assert [s.role for s in amp.speakers] == ["FL", "FR", "FC", "LFE", "SL", "SR"]


def test_auto_align_delays_nearer_speakers():
    proj = Project(mode="2.0", listener_x=0, listener_y=0)
    dev = proj.add_device("Amp", 2)
    dev.kind = "external"
    dev.speakers[0].x, dev.speakers[0].y = 0.0, -3.43
    dev.speakers[1].x, dev.speakers[1].y = 1.715, 0.0
    auto_align_delays(proj)
    assert dev.speakers[0].delay_ms == 0.0 and abs(dev.speakers[1].delay_ms - 5.0) < 0.01


def test_built_in_speakers_follow_the_unit_when_it_moves_and_turns():
    proj = Project()
    tv = proj.add_device("TV", 2)
    tv.x, tv.y, tv.width, tv.rotation = 1.0, 2.0, 2.0, 90.0
    (x0, y0), (x1, y1) = (speaker_position(tv, s) for s in tv.speakers)
    assert abs(x0 - 1) < 1e-9 and abs(y0 - 1) < 1e-9 and abs(x1 - 1) < 1e-9 and abs(y1 - 3) < 1e-9


def test_unassigned_roles_are_not_lost():
    """7.1 mode but only a stereo pair is set up: every channel must still be heard."""
    proj = Project(mode="7.1", master_db=0.0)
    tv = proj.add_device("TV", 2)
    assert [s.role for s in tv.speakers] == ["FL", "FR"]
    assert proj.roles_missing() == ["FC", "LFE", "SL", "SR", "BL", "BR"]
    eng = Engine(proj)
    eng.configure(SR, 8)
    eng.process(np.zeros((4800, 8)))
    for ch, role in enumerate(S71):
        block = np.zeros((480, 8), dtype=np.float32)
        block[:, ch] = 0.5
        out = eng.process(block)[tv.id]
        left, right = np.abs(out[:, 0]).max() > 0.01, np.abs(out[:, 1]).max() > 0.01
        assert left or right, role
        if role in ("SL", "BL"):
            assert left and not right
        if role in ("SR", "BR"):
            assert right and not left


def test_auto_assign_never_swaps_sides_when_it_can_avoid_it():
    proj = Project(mode="7.1", listener_x=0.0, listener_y=0.0)
    amp = proj.add_device("Amp", 8)
    amp.kind = "external"
    # six speakers bunched on the left, two on the right
    spots = [(-1, -2), (-1.2, -1.8), (-2, -0.2), (-2, 0.4), (-1.5, 1.6), (-1, 2), (1, -2), (2, 1.5)]
    for spk, (x, y) in zip(amp.speakers, spots):
        spk.role = "FL"
        spk.x, spk.y = x, y
    auto_assign_roles(proj)
    for spk in amp.speakers[:6]:
        assert spk.role in ("FL", "SL", "BL", "FC"), spk.role
    assert amp.speakers[4].role == "BL" or amp.speakers[5].role == "BL"


def near(a, b, tol=0.01):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def test_moving_one_end_of_a_unit_stretches_and_turns_it():
    proj = Project()
    tv = proj.add_device("TV", 2)
    tv.x, tv.y, tv.width, tv.rotation = 0.0, -1.0, 1.0, 0.0
    left, right = tv.speakers
    move_speaker(tv, left, -0.8, -1.0)                      # sideways, mirror off
    assert near(speaker_position(tv, left), (-0.8, -1.0))
    assert near(speaker_position(tv, right), (0.5, -1.0))   # the other end stayed
    assert near((tv.x, tv.width, tv.rotation), (-0.15, 1.3, 0.0))
    move_speaker(tv, right, 0.5, -0.5)                      # front to back, mirror off
    assert near(speaker_position(tv, left), (-0.8, -1.0))
    assert near(speaker_position(tv, right), (0.5, -0.5))
    assert tv.rotation > 15


def test_mirror_moves_the_other_end_the_mirrored_way():
    proj = Project()
    tv = proj.add_device("TV", 2)
    tv.x, tv.y, tv.width, tv.rotation = 0.0, -1.0, 1.0, 0.0
    left, right = tv.speakers
    move_speaker(tv, left, -0.9, -1.0, mirror=True)         # wider on both sides
    assert near(speaker_position(tv, right), (0.9, -1.0))
    assert near((tv.x, tv.y, tv.width, tv.rotation), (0.0, -1.0, 1.8, 0.0))
    move_speaker(tv, right, 0.9, -0.4, mirror=True)         # both ends back together
    assert near(speaker_position(tv, left), (-0.9, -0.4))
    assert near((tv.x, tv.y, tv.width, tv.rotation), (0.0, -0.4, 1.8, 0.0))
    move_speaker(tv, left, 0.9, -0.4, mirror=True)          # ends pushed through each other
    assert tv.width >= 0.1


def test_mirror_for_loose_speakers_and_who_partners_with_whom():
    proj = Project(mode="5.1")
    amp = proj.add_device("Amp", 6)
    amp.kind = "external"
    fl, fr, centre, sub, rl, rr = amp.speakers
    assert partner_speaker(amp, fl) is fr and partner_speaker(amp, rr) is rl
    assert partner_speaker(amp, centre) is None and partner_speaker(amp, sub) is None
    fl.x, fl.y, fr.x, fr.y = -1.0, -2.0, 1.0, -2.0
    move_speaker(amp, fl, -1.5, -1.8, mirror=True)
    assert near((fr.x, fr.y), (1.5, -1.8))
    move_speaker(amp, fl, -1.0, -2.0)
    assert near((fr.x, fr.y), (1.5, -1.8))                  # mirror off: partner untouched
    amp.kind = "builtin"                                    # attached: one surround shape
    assert not any(can_move_alone(amp, s) for s in amp.speakers)
    assert partner_speaker(amp, fl) is None
    move_speaker(amp, centre, amp.x + 0.5, amp.y - 0.2 - amp.width / 2)   # moves the whole shape
    assert near((amp.x, amp.y), (0.5, 0.3))


def test_changing_mode_switches_off_roles_that_no_longer_exist():
    proj, left, mid, right = three_tv_project()
    proj.set_mode("2.0")
    assert [s.role for _, s in proj.all_speakers()] == ["OFF", "OFF", "FL", "FR", "OFF", "OFF"]


def test_profile_round_trip(tmp_path=None):
    import tempfile
    proj, left, mid, right = three_tv_project()
    mid.kind, mid.trim_ms, mid.label = "external", 35.0, "Middle TV"
    mid.speakers[0].eq[3].gain_db = -4.5
    mid.speakers[0].rgb_device = "Strip"
    path = os.path.join(tempfile.mkdtemp(), "p.json")
    proj.save(path)
    back = Project.load(path)
    assert back.to_json() == proj.to_json()
    assert Project.from_json('{"mode": "9.9", "future_setting": 1}').mode == "2.0"


# ------------------------------------------------------------------ lighting

def test_led_patterns():
    red = (255, 0, 0)
    assert led_colors("static", red, 0.0, 4, 0) == [red] * 4
    assert led_colors("pulse", red, 1.0, 2, 0) == [red] * 2
    assert led_colors("pulse", red, 0.0, 1, 0)[0][0] < 30
    vu = led_colors("vu", red, 0.5, 10, 0)
    assert [c[0] > 200 for c in vu] == [True] * 5 + [False] * 5
    assert len(set(led_colors("rainbow", red, 1.0, 12, 0))) > 6
    assert level_to_unit(1.0) == 1.0 and level_to_unit(0.0) == 0.0 and 0.4 < level_to_unit(0.06) < 0.6


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok   ", name)
            except Exception as exc:        # noqa: BLE001
                failed += 1
                print("FAIL ", name, repr(exc))
    sys.exit(1 if failed else 0)
