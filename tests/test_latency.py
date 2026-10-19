"""Keeping the delay as low as it goes: outputs used on their own past Windows' mixer (with
the buffer converting their sample rate), the room for a hiccup given back over time, delay
that every speaker shares taken off, and where the delay comes from shown."""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from speakerweave import backend
from speakerweave.engine import AdaptiveFifo, Engine
from speakerweave.model import Project, auto_align_delays, common_delay, remove_common_delay
from fake_audio import FakeSoundDevice, _Stream


def test_an_output_at_another_rate_plays_the_same_notes():
    sr, out_rate, block = 48000.0, 44100.0, 480
    fifo = AdaptiveFifo(2, sr, 0.0, block=block, out_rate=out_rate)
    t = np.arange(int(sr * 2)) / sr
    wave = np.repeat((0.5 * np.sin(2 * np.pi * 1000.0 * t))[:, None], 2, axis=1).astype(np.float32)
    played, written, read_frames = [], 0, 0
    while written + block <= len(wave):
        fifo.write(wave[written:written + block])
        written += block
        while (read_frames + 441) / out_rate <= written / sr - 0.005:   # the device keeps pace
            played.append(fifo.read(441))
            read_frames += 441
    y = np.vstack(played)[int(out_rate * 0.5):, 0]
    spec = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    freq = np.fft.rfftfreq(len(y), 1 / out_rate)[np.argmax(spec)]
    assert abs(freq - 1000.0) < 3.0                     # the same note, at the device's own rate
    assert fifo.underruns <= 1                         # (the very first read finds it empty)


def test_room_asked_for_by_a_hiccup_is_given_back_when_all_is_calm():
    sr, block = 48000.0, 480
    fifo = AdaptiveFifo(2, sr, 0.0, block=block)
    base = fifo.need
    fifo._margin += int(0.012 * sr)                     # three hiccups' worth
    assert fifo.need > base
    quiet = np.zeros((block, 2), dtype=np.float32)
    for _ in range(int(fifo.CALM_S * 3 * sr / block) + 10):   # a minute of calm playing
        fifo.write(quiet)
        fifo.read(block)
    assert fifo.need < base + int(0.012 * sr)           # some of it given back
    assert fifo.need >= base                            # never below what it started with


def setup_with_delays():
    p = Project()
    p.set_mode("2.0")
    a = p.add_device("TV", 2)
    b = p.add_device("Monitor", 2)
    a.trim_ms, b.trim_ms = 12.0, 5.0
    a.speakers[0].delay_ms, a.speakers[1].delay_ms = 3.0, 4.0
    b.speakers[0].delay_ms, b.speakers[1].delay_ms = 9.0, 10.0
    return p, a, b


def test_delay_every_speaker_shares_is_taken_off_and_they_stay_in_line():
    p, a, b = setup_with_delays()
    before = [d.trim_ms + s.delay_ms for d in (a, b) for s in d.speakers]
    assert common_delay(p) == 14.0
    assert remove_common_delay(p) == 14.0
    after = [d.trim_ms + s.delay_ms for d in (a, b) for s in d.speakers]
    assert min(after) == 0.0
    assert np.allclose(np.subtract(before, after), 14.0)   # every one moved by the same amount
    assert all(d.trim_ms >= 0 and all(s.delay_ms >= 0 for s in d.speakers) for d in (a, b))
    assert remove_common_delay(p) == 0.0


def test_line_up_delays_leaves_the_latest_speaker_without_delay():
    p, a, b = setup_with_delays()
    a.y, b.y = -2.0, -1.0
    auto_align_delays(p)
    assert common_delay(p) < 0.05


class WasapiFake(FakeSoundDevice):
    """Pretend Windows sound: WASAPI, where one output refuses to be used on its own."""

    class WasapiSettings:
        def __init__(self, exclusive=False, auto_convert=False):
            self.exclusive, self.auto_convert = exclusive, auto_convert

    def __init__(self, devices):
        super().__init__(devices)
        self.opened = {}

    def query_hostapis(self):
        return [{"name": "Windows WASAPI"}]

    def query_devices(self):
        out = super().query_devices()
        for entry, d in zip(out, self.devices):
            entry["default_samplerate"] = d.get("rate", 48000.0)
        return out

    def OutputStream(self, device, channels, samplerate, callback, extra_settings=None, latency=None, **kw):
        d = self.devices[device]
        exclusive = bool(getattr(extra_settings, "exclusive", False))
        if exclusive and d.get("no_exclusive"):
            raise RuntimeError("Device unavailable [PaErrorCode -9985]")
        s = _Stream(samplerate, 441, channels, callback)
        s.latency = 0.004 if exclusive else 0.02
        self.opened[d["name"]] = (exclusive, samplerate)
        self.streams[d["name"]] = s
        return s

    def InputStream(self, device, channels, samplerate, callback, blocksize=480, **kw):
        s = super().InputStream(device, channels, samplerate, callback, blocksize)
        s.latency = 0.01
        return s


def test_lowest_delay_uses_outputs_on_their_own_and_falls_back_quietly():
    fake = WasapiFake([{"name": "Speakers (USB DAC)", "outputs": 2, "rate": 44100.0},
                       {"name": "VG258 (NVIDIA High Definition Audio)", "outputs": 2, "no_exclusive": True},
                       {"name": "Line in", "inputs": 2, "tones": {0: 440.0}}])
    old = backend._sd
    backend._sd = lambda: fake
    try:
        p = Project(input_kind="device", input_name="Line in", exclusive_outputs=True)
        p.set_mode("2.0")
        dac = p.add_device("Speakers (USB DAC)", 2)
        vg = p.add_device("VG258 (NVIDIA High Definition Audio)", 2)
        dac.enabled = vg.enabled = True
        eng = Engine(p)
        runner = backend.AudioRunner(p, eng)
        errors = runner.start()
        try:
            assert errors == []
            assert fake.opened["Speakers (USB DAC)"] == (True, 44100.0)       # on its own, own rate
            assert fake.opened["VG258 (NVIDIA High Definition Audio)"][0] is False   # through Windows
            assert runner.exclusive == {dac.id}
            assert any("VG258" in note for note in runner.notes)
            assert runner.fifos[dac.id].base == 48000.0 / 44100.0
            time.sleep(0.5)
            parts = runner.delay_parts()
            assert set(parts) == {"listening", "buffer", "output", "speakers"}
            assert parts["listening"] == 10.0 and parts["output"] == 20.0
            assert abs(sum(parts.values()) - runner.delay_ms()) < 1e-9
            played = np.vstack(fake.streams["Speakers (USB DAC)"].recorded[-40:])
            assert np.max(np.abs(played)) > 0.05                              # it really plays
        finally:
            runner.stop()
        # switched off: every output plays through Windows again
        p.exclusive_outputs = False
        runner.start()
        runner.stop()
        assert fake.opened["Speakers (USB DAC)"] == (False, 48000.0) and not runner.exclusive
    finally:
        backend._sd = old


def test_the_errors_page_points_at_a_high_rate_and_shared_delay(monkeypatch):
    from test_hidden_outputs import pump, window
    app, state, win = window([{"name": "Speakers", "outputs": 2}])
    try:
        p = state.project
        p.input_kind, p.input_name = "loopback", "SpeakerWeave Virtual Speaker output (VB-Audio Virtual Cable) [Loopback]"
        dev = p.add_device("Speakers", 2)
        dev.enabled = True
        dev.trim_ms = 6.0
        state.runner.running = True                    # as if the sound were playing
        state.engine.sr = 192000.0
        found = {f.title: f for f in win.errors_page.findings()}
        rate = found["SpeakerWeave Virtual Speaker output (VB-Audio Virtual Cable) runs at 192 kHz"]
        assert rate.action == "rate48" and rate.level == "warning"
        shared = found["Every speaker waits at least 6.0 ms"]
        assert shared.action == "trim_delay"
        state.runner.running = False
        win.errors_page.do_action("trim_delay")
        assert dev.trim_ms == 0.0
        # the 48 kHz button sets the rate and keeps the channels
        from speakerweave import windefault
        calls = []
        monkeypatch.setattr(windefault, "supported", lambda: True)
        monkeypatch.setattr(windefault, "find", lambda name, outputs=None: "{cab}")
        monkeypatch.setattr(windefault, "channel_count", lambda dev_id: 8)
        monkeypatch.setattr(windefault, "set_channels",
                            lambda dev_id, channels=8, rate=0: calls.append((dev_id, channels, rate)))
        monkeypatch.setattr(state, "scan_devices", lambda: None)
        assert state.set_listen_rate(48000) == "" and calls == [("{cab}", 8, 48000)]
    finally:
        monkeypatch.undo()
        win.close()
        state.stop()
        pump(app, 0.1)
