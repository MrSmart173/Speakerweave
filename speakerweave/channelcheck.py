"""Which channels does Windows pass through the virtual device?

Plays a different quiet tone on every channel of the device at once, listens in on it,
and reports which tone arrived on which channel. Then the same with plain stereo, the
way music and most videos play. Run it with SpeakerWeave closed, so nothing else plays
into the device:

    python -m speakerweave.channelcheck "channel test.txt"
"""
from __future__ import annotations

import sys
import time

import numpy as np

from . import backend, windefault

NAMES_8 = ["FL", "FR", "C", "SUB", "RL", "RR", "SL", "SR"]
TONE_LEVEL = 0.05            # quiet: about -26 dB
SECONDS = 1.5


SPEAKER_BITS = ["FL", "FR", "C", "SUB", "RL", "RR", "FLC", "FRC", "RC", "SL", "SR"]
KNOWN = {0x3: "stereo", 0x33: "quad", 0x3F: "5.1 (rear)", 0x60F: "5.1 (side)", 0x63F: "7.1",
         0xFF: "7.1 (wide)"}


def _mask_text(mask: int) -> str:
    if not mask:
        return "none stored"
    names = [name for bit, name in enumerate(SPEAKER_BITS) if mask & (1 << bit)]
    return f"0x{mask:X} = {KNOWN.get(mask, 'unusual')} ({' '.join(names)})"


def _freqs(n: int) -> list:
    return [300.0 + 150.0 * i for i in range(n)]       # 300, 450, 600 ... Hz, one per channel


def _play_and_listen(sd, pa, pa_audio, out_info, loop_info, channels: int, freqs: list) -> np.ndarray:
    """Plays freqs[i] on channel i of out_info (channels wide), returns what arrived."""
    sr = int(out_info.samplerate)
    total = int(loop_info["maxInputChannels"])
    got = []
    pos = [0]

    def on_audio(in_data, frames, _ti, _st):
        got.append(np.frombuffer(in_data, dtype=np.float32).reshape(-1, total).copy())
        return (None, pa.paContinue)

    def on_play(outdata, frames, _t, _s):
        t = (pos[0] + np.arange(frames)) / sr
        pos[0] += frames
        outdata[:] = 0.0
        for ch, f in enumerate(freqs):
            outdata[:, ch] = TONE_LEVEL * np.sin(2 * np.pi * f * t)

    listen = pa_audio.open(format=pa.paFloat32, channels=total, rate=int(loop_info["defaultSampleRate"]),
                           input=True, input_device_index=int(loop_info["index"]),
                           frames_per_buffer=480, stream_callback=on_audio)
    play = sd.OutputStream(device=out_info.index, channels=channels, samplerate=sr, dtype="float32",
                           extra_settings=backend._extra(out_info), callback=on_play)
    try:
        play.start()
        time.sleep(SECONDS)
    finally:
        play.stop()
        play.close()
        listen.stop_stream()
        listen.close()
    if not got:
        return np.zeros((0, total), dtype=np.float32)
    data = np.concatenate(got)
    return data[int(0.3 * sr):]                          # skip the start, while streams settle


def _which(data: np.ndarray, sr: float, freqs: list) -> list:
    """For every captured channel: the tones found in it, loudest first, with their level."""
    out = []
    for ch in range(data.shape[1]):
        x = data[:, ch].astype(np.float64)
        if len(x) < 4800:
            out.append([])
            continue
        x = x[: len(x) // 4800 * 4800]
        spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) / (len(x) / 4)
        found = []
        for i, f in enumerate(freqs):
            k = int(round(f * len(x) / sr))
            level = float(spec[max(0, k - 2):k + 3].max())
            if level > TONE_LEVEL * 0.1:                 # within 20 dB of what was sent
                found.append((level, i))
        found.sort(reverse=True)
        out.append(found)
    return out


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    report_path = argv[0] if argv else "channel test.txt"
    lines = []

    def say(text=""):
        lines.append(text)
        print(text, flush=True)

    sd = backend._sd()
    outputs = backend.list_outputs()
    target = next((o for o in outputs if o.name.lower().startswith("cable input")), None)
    if target is None:
        say("No CABLE Input device was found.")
        open(report_path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
        return 1
    say(f"Device: {target.name}, {target.outputs} channels in Windows, {target.samplerate:.0f} Hz")
    try:
        dev_id = windefault.find(target.name)
        info = windefault.layout(dev_id)
        say(f"Windows mixes {info['channels']} channels, layout {_mask_text(info['mix_mask'])}")
        say(f"Speaker setup in the Sound control panel: {_mask_text(info['speakers'])}")
    except Exception as exc:
        say(f"Layout: could not read ({exc!r})")
    try:
        _id, default_name = windefault.default_output()
        say(f"Windows default output: {default_name}")
    except Exception as exc:
        say(f"Windows default output: unknown ({exc!r})")
    try:
        from .wincom import Apartment
        from .winvolume import _EndpointVolume
        from ctypes import POINTER, byref, c_float, c_uint32
        from .wincom import HRESULT, method
        with Apartment() as com:
            vol = _EndpointVolume(com, target.name)
            try:
                gain, muted, percent = vol.read()
                count = c_uint32()
                method(vol.vol, 5, HRESULT, POINTER(c_uint32))(byref(count))
                levels = []
                for ch in range(count.value):
                    v = c_float()
                    method(vol.vol, 13, HRESULT, c_uint32, POINTER(c_float))(ch, byref(v))
                    name = NAMES_8[ch] if ch < 8 else str(ch + 1)
                    levels.append(f"{name} {v.value * 100:.0f}%")
            finally:
                vol.close()
        say(f"Windows volume: {percent:.0f}%{' MUTED' if muted else ''}. Balance per channel: "
            + ", ".join(levels))
    except Exception as exc:
        say(f"Windows volume: could not read ({exc!r})")
    say()

    import pyaudiowpatch as pa
    audio = pa.PyAudio()
    try:
        loop = next((d for d in audio.get_loopback_device_info_generator()
                     if d["name"].startswith(target.name)), None)
        if loop is None:
            say("Cannot listen in on the device (no loopback found).")
            return 1
        total = int(loop["maxInputChannels"])
        say(f"Listening in: {total} channels")
        names = NAMES_8 if total == 8 else [str(i + 1) for i in range(total)]
        sr = float(loop["defaultSampleRate"])

        for title, channels in (("All channels at once, a different tone on each", min(target.outputs, 8)),
                                ("Plain stereo, like music and most videos", 2)):
            freqs = _freqs(channels)
            data = _play_and_listen(sd, pa, audio, target, loop, channels, freqs)
            say()
            say(f"{title}:")
            sent = [names[i] if channels == total else ("L" if i == 0 else "R") for i in range(channels)]
            for ch, found in enumerate(_which(data, sr, freqs)):
                if not found:
                    say(f"  {names[ch]:>3} receives nothing")
                else:
                    parts = [f"{sent[i]} ({20 * np.log10(level / TONE_LEVEL):+.0f} dB)" for level, i in found]
                    say(f"  {names[ch]:>3} receives " + ", ".join(parts))
    finally:
        audio.terminate()
        open(report_path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
