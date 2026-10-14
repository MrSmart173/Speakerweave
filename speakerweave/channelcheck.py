"""Where do the channels of the virtual device get mixed up?

Plays quiet tones into CABLE Input and listens in on it, in ways that each leave out
one suspect:

1. straight in Windows' own format, so no converter is involved at all
2. through the sound library most apps use, which lets Windows convert
3. with the cable set to stereo, and to 5.1, for a moment (it is set back afterwards)

It also writes down every setting Windows keeps for the cable, including any sound
effects (APOs) attached to it. Run it with Spotify and the like paused:

    python -m speakerweave.channelcheck "channel test.txt"
"""
from __future__ import annotations

import os
import re
import sys
import time

import numpy as np

from . import backend, windefault

NAMES = {8: ["FL", "FR", "C", "SUB", "RL", "RR", "SL", "SR"], 6: ["FL", "FR", "C", "SUB", "SL", "SR"],
         2: ["FL", "FR"]}
SPEAKER_BITS = ["FL", "FR", "C", "SUB", "RL", "RR", "FLC", "FRC", "RC", "SL", "SR"]
KNOWN = {0x3: "stereo", 0x33: "quad", 0x3F: "5.1 (rear)", 0x60F: "5.1 (side)", 0x63F: "7.1",
         0xFF: "7.1 (wide)"}
TONE_LEVEL = 0.05            # quiet: about -26 dB
SECONDS = 1.5

RENDER_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
APO_KEY = r"SOFTWARE\Classes\AudioEngine\AudioProcessingObjects"
FX = "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d}"
SPK = "{1da5d803-d492-4edd-8c23-e0c0ffee7f0e}"
PROPERTY_NAMES = {
    "{a45c254e-df1c-4efd-8020-67d146a850e0},2": "name",
    f"{SPK},0": "form factor",
    f"{SPK},3": "physical speakers",
    f"{SPK},5": "enhancements switched off",
    f"{SPK},6": "full range speakers",
    "{f19f064d-082c-4e27-bc73-6882a1bb8e4c},0": "device format",
    "{e4870e26-3cc5-4cd2-ba46-ca0a9a70ed04},0": "default format",
    f"{FX},1": "effect before mixing (SFX)",
    f"{FX},2": "effect after mixing (MFX)",
    f"{FX},3": "effect settings window",
    f"{FX},4": "effect name",
    f"{FX},5": "stream effect",
    f"{FX},6": "mode effect",
    f"{FX},7": "endpoint effect",
    f"{FX},13": "stream effects",
    f"{FX},14": "mode effects",
    f"{FX},15": "endpoint effects",
}
CLSID = re.compile(r"\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}")


def _mask_text(mask: int) -> str:
    if not mask:
        return "none stored"
    names = [name for bit, name in enumerate(SPEAKER_BITS) if mask & (1 << bit)]
    return f"0x{mask:X} = {KNOWN.get(mask, 'unusual')} ({' '.join(names)})"


def _format_text(fmt: dict) -> str:
    kind = "float" if fmt.get("float") else f"{fmt.get('valid', fmt.get('bits'))} bit"
    return (f"{fmt.get('channels')} channels of {fmt.get('bits')} bit ({kind}) at {fmt.get('rate')} Hz, "
            f"format tag {fmt.get('tag')}, layout {_mask_text(fmt.get('mask', 0))}")


def _freqs(n: int) -> list:
    return [300.0 + 150.0 * i for i in range(n)]       # 300, 450, 600 ... Hz, one per channel


def _names(channels: int) -> list:
    return NAMES.get(channels, [str(i + 1) for i in range(channels)])


# ---------------------------------------------------------------- what Windows keeps for the cable
def _value_text(value) -> str:
    if isinstance(value, bytes):
        text = value[:80].hex(" ")
        return text + (" ..." if len(value) > 80 else "")
    if isinstance(value, list):
        return " | ".join(str(v) for v in value)
    if isinstance(value, int):
        return f"{value} (0x{value:X})"
    return str(value)


def _apo_name(winreg, clsid: str) -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{APO_KEY}\\{clsid}") as key:
            return str(winreg.QueryValueEx(key, "FriendlyName")[0])
    except OSError:
        return ""


def _settings(say, device_id: str) -> None:
    try:
        import winreg
    except ImportError:
        say("Settings: only readable on Windows")
        return
    endpoint = device_id[device_id.rfind("{"):] if "{" in device_id else device_id
    say(f"Windows' own settings for the cable ({endpoint}):")
    found_effects = set()
    for part in ("Properties", "FxProperties"):
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{RENDER_KEY}\\{endpoint}\\{part}")
        except OSError:
            say(f"  {part}: none")
            continue
        with key:
            say(f"  {part}:")
            i = 0
            while True:
                try:
                    name, value, _kind = winreg.EnumValue(key, i)
                except OSError:
                    break
                i += 1
                label = PROPERTY_NAMES.get(name.lower(), "")
                say(f"    {name}{'  [' + label + ']' if label else ''} = {_value_text(value)}")
                if part == "FxProperties" and isinstance(value, (str, list)):
                    for clsid in CLSID.findall(" ".join(value) if isinstance(value, list) else value):
                        found_effects.add(clsid.upper())
    if found_effects:
        say("  Sound effects (APOs) named for the cable:")
        for clsid in sorted(found_effects):
            say(f"    {clsid} = {_apo_name(winreg, clsid) or 'no name registered'}")
    else:
        say("  Sound effects (APOs) named for the cable: none")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Multimedia\Audio") as key:
            mono = winreg.QueryValueEx(key, "AccessibilityMonoMixState")[0]
    except OSError:
        mono = "not set"
    say(f"Mono audio (Accessibility): {mono}")
    for folder in (r"C:\Program Files\EqualizerAPO", r"C:\Program Files (x86)\EqualizerAPO"):
        if os.path.isdir(folder):
            say(f"Equalizer APO is installed in {folder}")
            try:
                with open(os.path.join(folder, "config", "config.txt"), encoding="utf-8",
                          errors="replace") as fh:
                    lines = fh.read().splitlines()[:30]
                say("  Its config.txt starts with:")
                for line in lines:
                    say("    " + line)
            except OSError:
                pass


# ---------------------------------------------------------------- playing and listening
def _tones(active: dict):
    """active: {channel: frequency}. A block maker for rawwasapi.play_and_listen."""
    def make(start, frames, channels, rate):
        t = (start + np.arange(frames)) / rate
        block = np.zeros((frames, channels), np.float32)
        for ch, f in active.items():
            if ch < channels:
                block[:, ch] = TONE_LEVEL * np.sin(2 * np.pi * f * t)
        return block
    return make


def _library_player(sd, out_info, channels: int, freqs: list):
    """Plays through PortAudio (sounddevice) and lets Windows convert, as most apps do."""
    def start():
        sr = int(out_info.samplerate)
        pos = [0]

        def on_play(outdata, frames, _t, _s):
            t = (pos[0] + np.arange(frames)) / sr
            pos[0] += frames
            outdata[:] = 0.0
            for ch, f in enumerate(freqs):
                outdata[:, ch] = TONE_LEVEL * np.sin(2 * np.pi * f * t)
        stream = sd.OutputStream(device=out_info.index, channels=channels, samplerate=sr, dtype="float32",
                                 extra_settings=backend._extra(out_info), callback=on_play)
        stream.start()

        def stop():
            stream.stop()
            stream.close()
        return stop
    return start


def _which(data: np.ndarray, sr: float, freqs: list) -> list:
    """For every captured channel: the tones found in it, loudest first, as (level, index)."""
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


def _clean(found: list, expected: dict) -> bool:
    """expected: {captured channel: tone index}. Clean: exactly those, nothing else."""
    for ch, tones in enumerate(found):
        want = expected.get(ch)
        got = [i for _level, i in tones]
        if want is None and got:
            return False
        if want is not None and got != [want]:
            return False
    return True


def _check(say, title: str, run, sent: list) -> bool:
    """run(freqs) -> (heard, rate, channels). sent: names of the tones on channels 0, 1 ..."""
    freqs = _freqs(len(sent))
    try:
        data, rate, channels = run(freqs)
    except Exception as exc:
        say(f"  {title}: could not run ({exc!r})")
        return False
    data = data[int(0.3 * rate):]                       # skip the start, while streams settle
    if len(data) < 4800:
        say(f"  {title}: heard nothing at all ({len(data)} frames)")
        return False
    found = _which(data, rate, freqs)
    ok = _clean(found, {i: i for i in range(min(len(sent), channels))})
    silent = not any(found)
    verdict = "CLEAN, every channel where it belongs" if ok else ("SILENT, nothing arrived" if silent else "MIXED UP")
    say(f"  {title}: {verdict}")
    names = _names(channels)
    for ch, tones in enumerate(found):
        parts = [f"{sent[i]} ({20 * np.log10(level / TONE_LEVEL):+.0f} dB)" for level, i in tones]
        say(f"    {names[ch]:>3} receives " + (", ".join(parts) if parts else "nothing"))
    return ok


# ---------------------------------------------------------------- the test
def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    report_path = argv[0] if argv else "channel test.txt"
    lines = []

    def say(text=""):
        lines.append(text)
        print(text, flush=True)

    try:
        return _run(say)
    except Exception as exc:
        say(f"The test stopped: {exc!r}")
        return 1
    finally:
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")


def _run(say) -> int:
    from . import rawwasapi
    sd = backend._sd()
    target = next((o for o in backend.list_outputs() if o.name.lower().startswith("cable input")), None)
    if target is None:
        say("No CABLE Input device was found.")
        return 1
    dev_id = windefault.find(target.name)
    say(f"Device: {target.name}, {target.outputs} channels, {target.samplerate:.0f} Hz")
    info = windefault.layout(dev_id)
    start_channels = int(info["channels"]) or 8
    say(f"Speaker setup in the Sound control panel: {_mask_text(info['speakers'])}")
    for label, key in (("Windows mixes in", "mix_format"), ("The device itself runs", "device_format")):
        if key in info:
            say(f"{label}: {_format_text(info[key])}")
    say(f"Windows default output: {windefault.default_output()[1]}")
    say()
    _settings(say, dev_id)

    def straight(freqs):
        return rawwasapi.play_and_listen(dev_id, _tones(dict(enumerate(freqs))), SECONDS)

    def library(freqs):
        return rawwasapi.play_and_listen(dev_id, None, SECONDS,
                                         other_player=_library_player(sd, target, len(freqs), freqs))

    verdicts = []
    sent = _names(start_channels)
    say()
    say(f"== 1. Played straight in Windows' own format, nothing converted ({start_channels} channels)")
    verdicts.append(("Straight, plain stereo", _check(say, "plain stereo", straight, ["L", "R"])))
    verdicts.append(("Straight, a tone on each channel",
                     _check(say, "a tone on each channel", straight, sent)))

    say()
    say("== 2. Played through the sound library, Windows converting (as many apps do)")
    verdicts.append(("Library, plain stereo", _check(say, "plain stereo", library, ["L", "R"])))
    verdicts.append(("Library, a tone on each channel",
                     _check(say, "a tone on each channel", library, sent)))

    try:
        for channels, label in ((2, "stereo"), (6, "5.1")):
            say()
            say(f"== 3. The cable set to {label} for a moment, played straight")
            try:
                windefault.set_channels(dev_id, channels)
                time.sleep(1.0)
                now = windefault.layout(dev_id)
                say(f"  Windows now mixes {now['channels']} channels, layout {_mask_text(now['mix_mask'])}")
            except Exception as exc:
                say(f"  could not switch the cable to {label} ({exc!r})")
                continue
            verdicts.append((f"Cable as {label}, plain stereo",
                             _check(say, "plain stereo", straight, ["L", "R"])))
            if channels > 2:
                verdicts.append((f"Cable as {label}, a tone on each channel",
                                 _check(say, "a tone on each channel", straight, _names(channels))))
    finally:
        try:
            windefault.set_channels(dev_id, start_channels)
            time.sleep(1.0)
            back = windefault.layout(dev_id)
            say()
            say(f"The cable is set back to {back['channels']} channels, layout {_mask_text(back['mix_mask'])}")
        except Exception as exc:
            say(f"Could not set the cable back to {start_channels} channels ({exc!r})")

    say()
    say("Summary:")
    for title, ok in verdicts:
        say(f"  {'CLEAN    ' if ok else 'MIXED UP '} {title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
