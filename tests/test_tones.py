"""The tone generator: any pitch from 1 Hz to 20,000 Hz, as a steady tone, beeps, a
pattern or a sweep, on the speakers you pick."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from speakerweave import tones
from speakerweave.engine import Engine
from speakerweave.model import Project

SR = 48000.0


def run(spec, seconds, n=480):
    gen = tones.ToneGenerator(spec, SR)
    blocks = int(seconds * SR / n)
    return gen, np.concatenate([gen.render(n) for _ in range(blocks)])


def pitch(x):
    x = x * np.hanning(len(x))
    spectrum = np.abs(np.fft.rfft(x, 8 * len(x)))
    return np.argmax(spectrum) * SR / (8 * len(x))


def test_any_pitch_from_1_hz_to_20_khz():
    for hz in (1.0, 20.0, 440.0, 1000.0, 12345.0, 20000.0):
        _gen, x = run({"hz": hz, "db": -6}, 2.0 if hz < 10 else 0.5)
        assert abs(pitch(x[2400:]) - hz) < max(0.3, hz * 0.002), hz
        assert np.abs(x).max() <= 10 ** (-6 / 20) + 1e-6
    s = tones.clean({"hz": 0.2, "db": 9, "wave": "noise", "kind": "?"})
    assert s["hz"] == 1.0 and s["db"] == 0.0 and s["wave"] == "sine" and s["kind"] == "steady"
    assert tones.clean({"hz": 99999})["hz"] == 20000.0 and tones.clean({"hz": "abc"})["hz"] == 440.0


def test_every_wave_starts_softly_and_high_ones_do_not_fold_back():
    for wave in tones.WAVES:
        _gen, x = run({"hz": 1000, "wave": wave, "db": 0}, 0.2)
        assert abs(x[0]) < 1e-3 and np.abs(x[:20]).max() < 0.12      # a fade in, no click
        assert np.abs(x).max() <= 1.0 + 1e-6
        rms = np.sqrt(np.mean(x[4800:] ** 2))
        assert 0.55 < rms < 0.75, wave                               # the same loudness each
    for wave in ("square", "saw", "triangle"):
        _gen, x = run({"hz": 15000, "wave": wave, "db": 0}, 0.5)
        x = x[2400:] * np.hanning(len(x) - 2400)
        f = np.abs(np.fft.rfft(x))
        freqs = np.fft.rfftfreq(len(x), 1 / SR)
        main = f[np.argmin(np.abs(freqs - 15000))]
        folded = f[(freqs > 200) & (freqs < 14000)].max()
        assert 20 * np.log10(folded / main) < -35, wave


def test_beeps_patterns_and_sweeps():
    gen, x = run({"kind": "beeps", "hz": 500, "beep_ms": 100, "gap_ms": 150, "repeat": 4}, 1.5)
    loud = np.abs(x) > 0.01
    starts = np.flatnonzero(loud[1:] & ~loud[:-1]) + 1
    beeps = [s for i, s in enumerate(starts) if i == 0 or s - starts[i - 1] > 2000]
    assert len(beeps) == 4 and gen.finished
    assert all(abs((b - a) - 0.25 * SR) < 60 for a, b in zip(beeps, beeps[1:]))
    gen, x = run({"kind": "pattern", "steps": [[440, 200], [0, 100], [880, 200]], "repeat": 2}, 1.2)
    assert gen.finished
    assert abs(pitch(x[1000:9000]) - 440) < 3 and abs(pitch(x[15400:23400]) - 880) < 4
    assert np.abs(x[10500:13900]).max() < 1e-6                       # the rest
    assert np.abs(x[int(1.0 * SR):]).max() < 1e-6                    # two rounds, then quiet
    gen, x = run({"kind": "sweep", "sweep_from": 100, "sweep_to": 10000, "sweep_s": 2,
                  "sweep_log": True, "repeat": 1}, 2.2)
    assert gen.finished
    assert abs(pitch(x[2000:6000]) - 110) < 15 and pitch(x[int(1.9 * SR):int(1.98 * SR)]) > 7000
    assert abs(pitch(x[int(0.98 * SR):int(1.02 * SR)]) - 1000) < 80   # halfway: 1 kHz, logarithmic
    gen, x = run({"kind": "sweep", "sweep_from": 100, "sweep_to": 1000, "sweep_s": 1,
                  "sweep_back": True, "repeat": 1}, 2.1)
    assert gen.finished and gen.pos >= 2 * SR
    assert pitch(x[int(1.9 * SR):int(1.98 * SR)]) < 250                # back down again
    gen, x = run({"kind": "steady", "hz": 300}, 0.5)
    assert not gen.finished and gen.total is None                     # until stopped


def test_typing_steps_presets_and_saved_patterns():
    assert tones.parse_steps("440 200, rest 100, 880hz 200ms; 0:50, nonsense") == \
        [[440.0, 200], [0.0, 100], [880.0, 200], [0.0, 50]]
    assert tones.steps_text([[440.0, 200], [0.0, 100]]) == "440 200, rest 100"
    for name, steps in tones.PATTERNS.items():
        assert tones.clean_steps(steps) == [[float(h), int(m)] for h, m in steps], name
    saved = tones.clean_patterns({"Mine": [[300, 100]], "Bad": "x", "SOS": [[1, 100]], "": [[1, 10]]})
    assert saved == {"Mine": [[300.0, 100]]}
    assert "20 Hz to 20 kHz" in tones.describe({"kind": "sweep"})
    assert tones.describe({"hz": 440}) == "a steady 440 Hz sine tone at -20 dB"


def test_retune_while_it_plays():
    gen = tones.ToneGenerator({"hz": 440, "db": -20}, SR)
    first = np.concatenate([gen.render(480) for _ in range(20)])
    gen.retune({"hz": 880, "db": -6})
    second = np.concatenate([gen.render(480) for _ in range(20)])
    assert abs(pitch(first[2000:]) - 440) < 3 and abs(pitch(second[960:]) - 880) < 4
    assert np.abs(np.diff(np.concatenate([first[-5:], second[:5]]))).max() < 0.05   # no jump
    gen.retune({"kind": "sweep", "hz": 100})                          # another kind: next Play
    assert gen.spec["hz"] == 880


def test_the_engine_plays_it_on_the_chosen_speakers_instead_of_the_pc_sound():
    p = Project(mode="2.1", input_kind="device", input_name="Line in", master_db=0.0)
    p.bass_redirect = False
    tv = p.add_device("TV", 2)
    sub = p.add_device("Sub amp", 1)
    p.set_role(sub.speakers[0], "LFE")
    for spk in tv.speakers:
        spk.hp_on = spk.lp_on = False
    eng = Engine(p)
    eng.configure(SR, 2)
    left, right = tv.speakers
    music = np.full((480, 2), 0.3, dtype=np.float32)
    eng.set_tone(tones.ToneGenerator({"kind": "beeps", "hz": 1000, "beep_ms": 100, "gap_ms": 100,
                                      "repeat": 2, "db": -6}, SR), [left.id])
    assert eng.tone_on
    outs = [eng.process(music) for _ in range(60)]
    tv_out = np.concatenate([o[tv.id] for o in outs])
    assert abs(pitch(tv_out[480:4800, 0]) - 1000) < 5
    assert np.abs(tv_out[:int(0.4 * SR), 1]).max() < 1e-6            # the other speaker waits
    assert not eng.tone_on and eng.tones_done == 1                    # two beeps, then done
    assert np.abs(tv_out[-480:, 1]).max() > 0.1                       # the PC sound is back
    eng.set_tone(tones.ToneGenerator({"hz": 200}, SR), [left.id, right.id])
    eng.process(music)
    eng.stop_tone()
    assert not eng.tone_on


def test_the_tone_generator_panel(monkeypatch):
    from test_hidden_outputs import pump, window
    from speakerweave.ui.tone_panel import hz_to_slider, slider_to_hz
    assert hz_to_slider(1.0) == 0 and hz_to_slider(20000.0) == 1000
    assert slider_to_hz(0) == 1.0 and slider_to_hz(1000) == 20000.0
    assert abs(slider_to_hz(hz_to_slider(440.0)) - 440.0) < 5
    app, state, win = window([{"name": "Speakers", "outputs": 2}, {"name": "Sub", "outputs": 1}])
    try:
        state.save_settings = lambda: None
        p = state.project
        p.set_mode("2.1")
        speakers, sub = p.add_device("Speakers", 2), p.add_device("Sub", 1)
        p.set_role(sub.speakers[0], "LFE")
        speakers.enabled = sub.enabled = True
        state.touch_routing()
        state.structureChanged.emit()
        pump(app, 0.2)
        panel = win.tone_panel
        win.workspaces.open("tones")
        pump(app, 0.1)
        assert win.workspaces.in_front("tones")
        assert panel.target.count() >= 4                         # every speaker, the selected one, each
        panel.hz.setValue(12.0)
        assert panel.hz_slider.value() == hz_to_slider(12.0)
        assert panel.warning.isVisibleTo(panel) and "20 Hz" in panel.warning.text()
        panel.hz.setValue(1000.0)
        assert not panel.warning.isVisibleTo(panel)
        panel.hz_slider.setValue(500)
        assert abs(panel.hz.value() - slider_to_hz(500)) < 0.01
        panel.level.setValue(-30)
        assert state.settings.tone["db"] == -30.0
        panel.play_btn.click()
        pump(app, 0.3)
        assert state.tone_playing and state.runner.running
        assert set(state.engine._tone[1]) == set(state.playing_speakers())
        assert panel.stop_btn.isEnabled() and "Playing" in panel.status.text()
        generator = state.engine._tone[0]
        panel.hz.setValue(2000.0)                                 # follows the knob while it plays
        assert generator.spec["hz"] == 2000.0 and state.engine._tone[0] is generator
        panel.stop_btn.click()
        pump(app, 0.5)
        assert not state.tone_playing and not state.runner.running   # the sound stops again
        # a pattern from the presets, saved under a name of its own
        panel.kind_tabs.setCurrentIndex(2)
        panel.preset.setCurrentIndex(panel.preset.findData("SOS"))
        panel._preset_chosen(0)
        assert panel.table_steps() == tones.PATTERNS["SOS"]
        assert panel.spec()["kind"] == "pattern"
        monkeypatch.setattr("speakerweave.ui.tone_panel.QInputDialog.getText",
                            lambda *a, **k: ("My SOS", True))
        panel._save_pattern()
        assert state.settings.tone_patterns["My SOS"] == tones.PATTERNS["SOS"]
        assert panel.preset.currentData() == "saved:My SOS" and panel.delete_pattern.isEnabled()
        panel._delete_pattern()
        assert "My SOS" not in state.settings.tone_patterns
        panel.kind_tabs.setCurrentIndex(3)
        panel.sweep_from.setValue(5.0)
        assert panel.warning.isVisibleTo(panel)                   # a sweep down to 5 Hz
        # one at a time: the metronome stops a tone
        panel.kind_tabs.setCurrentIndex(0)
        panel.play()
        pump(app, 0.2)
        assert state.tone_playing
        state.start_metronome("together")
        assert not state.tone_playing and state.engine.metronome_on
        state.stop_metronome()
        win.workspaces.close_panel("tones")
    finally:
        win.state.runner.stop()
        win.close()
