"""Sound check: follows the sound from the PC to every speaker and reports
where it stops.

Used by the Errors page ("Run a sound check") and from the command line:

    python -m speakerweave.soundcheck "sound check report.txt"

It never plays anything you can hear: the test tone goes into the virtual
device SpeakerWeave listens to, and while the whole chain is checked the
speakers are muted at the very end of the chain.
"""
from __future__ import annotations

import os
import platform
import sys
import time
from dataclasses import dataclass, field

import numpy as np

from . import __version__, backend
from .release import version_name
from .model import OFF, ROLE_NAMES, Project, is_sub

TONE_HZ = 997.0
TONE_LEVEL = 0.05                      # about -26 dB, into the virtual device only
LISTEN_SECONDS = 1.6


@dataclass
class Finding:
    level: str                 # "ok", "warning" or "error"
    title: str
    detail: str = ""
    fix: str = ""
    action: str = ""           # a fix the Errors page can do with one button
    area: str = "sound"        # "sound" or "surround"


@dataclass
class Report:
    findings: list = field(default_factory=list)
    lines: list = field(default_factory=list)       # the raw facts, for the text report

    def add(self, level, title, detail="", fix="", action="", area="sound"):
        self.findings.append(Finding(level, title, detail, fix, action, area))

    def note(self, text: str) -> None:
        self.lines.append(text)

    @property
    def errors(self):
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self):
        return [f for f in self.findings if f.level == "warning"]

    def text(self) -> str:
        out = [f"SpeakerWeave {version_name()} ({__version__}) sound check, {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
        for f in self.findings:
            out.append(f"[{f.level.upper()}] {f.title}")
            if f.detail:
                out.append(f"    {f.detail}")
            if f.fix:
                out.append(f"    What to do: {f.fix}")
        out += ["", "Details", "-------"] + self.lines
        return "\n".join(out) + "\n"


# ------------------------------------------------------------------ setup checks (no sound needed)

def check_setup(project: Project, outputs: list, loopbacks: list, report: Report,
                windows_default: str = "", running=None) -> None:
    """Problems that can be seen from the setup and the device lists alone.
    running: whether SpeakerWeave's sound is on (None when not known)."""
    p = project
    by_name = {d.name: d for d in outputs}
    enabled = [d for d in p.devices if d.enabled]
    report.note(f"Mode {p.mode_text()}, listening to {p.input_kind}: {p.input_name or '(test signal)'}")

    if not enabled:
        report.add("error", "No sound output is ticked",
                   "SpeakerWeave has nothing to play the sound on.",
                   "Tick your speakers, TVs or sound card in the list on the left of the Room page.",
                   action="room")

    # the source
    listened = ""
    if p.input_kind == "test":
        report.add("warning", "Listening to the test signal",
                   "The test signal only steps a noise through the speakers. The sound of the PC "
                   "is not being picked up.",
                   "Under Listen to, choose \"Everything this PC plays on: SpeakerWeave Virtual "
                   "Speaker output\" (VB-CABLE's CABLE Input).",
                   action="listen_virtual")
    elif p.input_kind == "loopback":
        listened = p.input_name.replace(" [Loopback]", "")
        if not any(lb.name == p.input_name for lb in loopbacks):
            report.add("error", f"{listened} is not available to listen to",
                       "The device chosen under Listen to was not found.",
                       "Press Rescan, then choose it again under Listen to.", action="rescan")
        if listened in {d.name for d in enabled}:
            report.add("error", f"{listened} is both the source and a speaker",
                       "Playing into the device you listen to makes an echo loop, so it is skipped.",
                       "Listen to the virtual device (SpeakerWeave Virtual Speaker output) instead.")
        if running is not False and windows_default and listened and windows_default != listened:
            report.add("error", "Windows is not playing into the device SpeakerWeave listens to",
                       f"Windows plays into {windows_default}, SpeakerWeave listens to {listened}. "
                       f"So SpeakerWeave hears nothing (or the speakers also play the sound directly).",
                       "Press the button: SpeakerWeave starts its sound and Windows plays into "
                       f"{listened}.", action="claim")
    if running is False and enabled:
        report.add("warning", "The sound is stopped",
                   "SpeakerWeave is not passing the PC's sound on to your speakers right now.",
                   "Press Start (top left).", action="start")

    # each output
    for dev in enabled:
        info = by_name.get(dev.name)
        if info is None:
            report.add("warning", f"{dev.title} is not connected",
                       "Windows does not list this output right now, so it is left out.",
                       "Switch it on or plug it in, then press Rescan. Or untick it if you no "
                       "longer use it.", action=f"untick:{dev.id}")
            continue
        report.note(f"Output {dev.title}: {info.outputs} channels on Windows, {dev.channels} in the "
                    f"setup, {info.samplerate:.0f} Hz")
        if info.outputs < dev.channels:
            lost = [s.name for s in dev.speakers if s.channel >= info.outputs and s.role != OFF]
            if lost:
                report.add("warning", f"{dev.title} only has {info.outputs} channels open",
                           f"Windows offers {info.outputs} channels, so these speakers stay silent: "
                           f"{', '.join(lost)}.",
                           "In the Sound control panel, select the output, press Configure and "
                           "choose 5.1 or 7.1.", action="sound_panel", area="surround")
        if all(s.role == OFF or s.mute for s in dev.speakers):
            report.add("warning", f"{dev.title} has no speaker playing",
                       "Every speaker of this output is off or muted.",
                       "Click a speaker and give it a role.")

    # surround: which positions have a speaker
    roles = p.mode_roles()
    have = {s.role for d in enabled for s in d.speakers if s.role != OFF}
    missing = [ROLE_NAMES[r] for r in roles if r not in have and not is_sub(r)]
    if missing and enabled:
        report.add("warning", f"No speaker for: {', '.join(missing)}",
                   "That part of the surround sound is shared between the nearest speakers, so it "
                   "is not lost, but it does not come from its own direction.",
                   "Give a speaker each of these roles, or pick a mode with fewer positions.",
                   action="positions", area="surround")
    extra = sorted({ROLE_NAMES.get(s.role, s.role) for d in enabled for s in d.speakers
                    if s.role != OFF and s.role not in roles})
    if extra:
        report.add("warning", f"Speakers with a role this mode does not have: {', '.join(extra)}",
                   "They play nothing in this mode.", "Change their role, or change the mode.",
                   area="surround")

    # the source's channel count against the mode
    if p.input_kind == "loopback":
        lb = next((d for d in loopbacks if d.name == p.input_name), None)
        if lb is not None:
            report.note(f"Source {lb.name}: {lb.inputs} channels, {lb.samplerate:.0f} Hz")
            wanted = len([r for r in roles if not is_sub(r)])
            if lb.inputs <= 2 < wanted:
                report.add("warning", f"Windows sends only stereo into {listened}",
                           f"Your mode has {wanted} positions, but the PC's sound arrives as "
                           f"{lb.inputs} channels. SpeakerWeave spreads stereo over every speaker, "
                           f"but games cannot place sounds behind you.",
                           f"Press the button to set {listened} to 7.1, then restart the game.",
                           action="surround", area="surround")


# ------------------------------------------------------------------ live checks

def _tone(n: int, start: int, sr: float) -> np.ndarray:
    t = (start + np.arange(n)) / sr
    return (TONE_LEVEL * np.sin(2 * np.pi * TONE_HZ * t)).astype(np.float32)


class _ToneInto:
    """Plays a quiet tone into one output (meant for a virtual device)."""

    def __init__(self, info):
        self.info = info
        self.stream = None
        self.pos = 0

    def __enter__(self):
        sd = backend._sd()
        channels = max(1, min(self.info.outputs, 8))
        sr = self.info.samplerate

        def callback(outdata, frames, _t, _s):
            tone = _tone(frames, self.pos, sr)
            self.pos += frames
            outdata[:] = np.repeat(tone[:, None], channels, axis=1)
        self.stream = sd.OutputStream(device=self.info.index, channels=channels, samplerate=sr,
                                      dtype="float32", extra_settings=backend._extra(self.info),
                                      callback=callback)
        self.stream.start()
        return self

    def __exit__(self, *exc):
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass
        return False


def _is_virtual(name: str) -> bool:
    from .speaker_library import recognise
    entry = recognise(name)
    return entry is not None and entry.category == "virtual"


def check_listening(project: Project, outputs: list, report: Report) -> None:
    """Plays a quiet tone into the virtual device and checks it arrives."""
    p = project
    if p.input_kind != "loopback" or not backend.loopback_available():
        return
    listened = p.input_name.replace(" [Loopback]", "")
    target = next((d for d in outputs if d.name == listened), None)
    if target is None:
        return
    if not _is_virtual(listened):
        report.note(f"Listening test skipped: {listened} is a real output, a tone would be heard.")
        return
    import pyaudiowpatch as pa
    audio = pa.PyAudio()
    got = []
    try:
        info = next((d for d in audio.get_loopback_device_info_generator()
                     if d["name"] == p.input_name), None)
        if info is None:
            return
        total = int(info["maxInputChannels"])

        def on_audio(in_data, frames, _ti, _st):
            got.append(np.frombuffer(in_data, dtype=np.float32).reshape(-1, total).copy())
            return (None, pa.paContinue)
        stream = audio.open(format=pa.paFloat32, channels=total, rate=int(info["defaultSampleRate"]),
                            input=True, input_device_index=int(info["index"]),
                            frames_per_buffer=480, stream_callback=on_audio)
        try:
            with _ToneInto(target):
                time.sleep(LISTEN_SECONDS)
        finally:
            stream.stop_stream()
            stream.close()
    except Exception as exc:
        report.add("error", f"Could not listen to {listened}", repr(exc),
                   "Restart the PC once after installing VB CABLE. If it stays, reinstall VB CABLE.")
        return
    finally:
        audio.terminate()
    if not got:
        report.add("error", f"Nothing arrives from {listened}",
                   "A test tone was played into it, but listening in on it delivered no sound at all.",
                   "Restart the PC once after installing VB CABLE. Check that it is enabled in the "
                   "Sound control panel (Win + R, mmsys.cpl).")
        return
    data = np.concatenate(got)
    peak = float(np.max(np.abs(data)))
    report.note(f"Listening test: {len(data)} frames, {data.shape[1]} channels, peak {peak:.4f}")
    if peak < TONE_LEVEL * 0.2:
        report.add("error", f"The sound played into {listened} does not come back out",
                   f"Peak {peak:.4f} instead of about {TONE_LEVEL}.",
                   f"In the Sound control panel, open {listened}, Levels tab: set it to 100 and "
                   f"unmuted.")
    else:
        report.add("ok", f"Listening to {listened} works",
                   "A test tone played into it arrived in SpeakerWeave.")


def check_chain(project: Project, outputs: list, report: Report, seconds: float = 2.0) -> None:
    """Runs the real engine with every speaker muted at the very end, feeds it a
    tone through the virtual device and checks that each speaker receives it and
    each output keeps asking for sound."""
    from .engine import Engine
    p = Project.from_json(project.to_json())        # a copy, the real setup is never touched
    p.muted = True                                  # silent: the tone stops right before the speakers
    if not any(d.enabled for d in p.devices):
        return
    engine = Engine(p)
    engine.rebuild()
    runner = backend.AudioRunner(p, engine)
    tone_target = None
    if p.input_kind == "loopback":
        listened = p.input_name.replace(" [Loopback]", "")
        target = next((d for d in outputs if d.name == listened), None)
        if target is not None and _is_virtual(listened):
            tone_target = target
    problems = runner.start()
    for text in problems:
        report.add("error", "Starting the sound: " + text.split(":")[0], text,
                   "Close other apps that use this output in exclusive mode, then try again.")
    if not runner.running:
        report.add("error", "The sound could not be started", "; ".join(problems) or "")
        return
    peaks: dict[str, float] = {}
    try:
        ctx = _ToneInto(tone_target) if tone_target else None
        if ctx:
            ctx.__enter__()
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            for _, spk in p.all_speakers():
                peaks[spk.id] = max(peaks.get(spk.id, 0.0), engine.level(spk.id))
            time.sleep(0.02)
        if ctx:
            ctx.__exit__(None, None, None)
        stats = runner.status()
        input_peak = float(np.max(engine.input_peaks)) if len(engine.input_peaks) else 0.0
    finally:
        runner.stop()
    report.note(f"Chain test: input peak {input_peak:.4f}, callback errors {runner.callback_errors}")
    if tone_target and input_peak < TONE_LEVEL * 0.2:
        report.add("error", "SpeakerWeave receives no sound while running",
                   "The test tone did not reach the mixing engine.",
                   "Check the Listen to choice, then run the check again.")
    signal_in = bool(tone_target) or input_peak > TONE_LEVEL * 0.2
    for dev in p.devices:
        if not dev.enabled or dev.id not in stats:
            continue
        fill_ms, ppm, glitches = stats[dev.id]
        # subwoofers and speakers limited to low notes cannot play the test tone
        heard = [s for s in dev.speakers if s.role != OFF and not s.mute and not is_sub(s.role)
                 and not (s.lp_on and s.lp_freq < TONE_HZ * 1.5)]
        quiet = [s.name for s in heard if peaks.get(s.id, 0.0) < 1e-4]
        report.note(f"{dev.title}: buffer {fill_ms:.0f} ms, {ppm:+.0f} ppm, {glitches} interruptions, "
                    f"speaker peaks " + ", ".join(f"{s.name} {peaks.get(s.id, 0.0):.4f}"
                                                  for s in dev.speakers))
        if fill_ms <= 1.0:
            report.add("error", f"{dev.title} is not taking any sound",
                       "Its sound stream opened but never asked for audio.",
                       "Set this output's format to 48000 Hz in the Sound control panel "
                       "(Advanced tab), and close apps that use it in exclusive mode.")
        elif signal_in and quiet:
            report.add("warning", f"{dev.title}: no sound reaches {', '.join(quiet)}",
                       "These speakers have a role, but the test tone did not reach them.",
                       "Check their roles and the mode, or turn off Solo on other speakers.")
        elif signal_in:
            report.add("ok", f"{dev.title} receives the sound",
                       f"The test tone reached all {len(heard)} playing speakers.")
        if glitches > 2:
            report.add("warning", f"{dev.title} had {glitches} interruptions in {seconds:.0f} s",
                       "Its sound card did not keep up.", "Raise the Safety buffer on the Sound tab.")
    if runner.callback_errors:
        report.add("error", "The mixing engine reported errors",
                   f"{runner.callback_errors} blocks could not be processed.",
                   "Send the error log (Settings page, Open that folder) to the developer.")


def windows_default_name() -> str:
    try:
        from . import windefault
        return windefault.default_output()[1] if windefault.supported() else ""
    except Exception:
        return ""


def run(project: Project, live: bool = True) -> Report:
    report = Report()
    report.note(f"Windows {platform.version()}, Python {sys.version.split()[0]}")
    try:
        sd = backend._sd()
        report.note(f"PortAudio: {sd.get_portaudio_version()[1]}")
    except Exception as exc:
        report.add("error", "The sound library could not start", repr(exc))
        return report
    if sys.platform.startswith("win") and not backend.loopback_available():
        report.add("error", "Listening to the PC's sound is not possible",
                   "The PyAudioWPatch part is missing from this copy of SpeakerWeave.",
                   "Reinstall SpeakerWeave.")
    try:
        outputs = backend.list_outputs()
        loopbacks = backend.list_loopbacks()
    except Exception as exc:
        report.add("error", "Could not read the list of sound devices", repr(exc))
        return report
    for d in outputs:
        report.note(f"  output: {d.name}  [{d.outputs} ch, {d.samplerate:.0f} Hz]")
    for d in loopbacks:
        report.note(f"  can listen to: {d.name}  [{d.inputs} ch, {d.samplerate:.0f} Hz]")
    default = windows_default_name()
    report.note(f"Windows default output: {default or 'unknown'}")
    check_setup(project, outputs, loopbacks, report, default)
    if live:
        try:
            check_listening(project, outputs, report)
        except Exception as exc:
            report.add("error", "The listening test failed", repr(exc))
        try:
            check_chain(project, outputs, report)
        except Exception as exc:
            report.add("error", "The sound chain test failed", repr(exc))
    if not report.errors and not report.warnings:
        report.add("ok", "No problems found", "The sound goes from the PC to every speaker.")
    return report


def _config_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "SpeakerWeave")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    out = argv[0] if argv else "sound check report.txt"
    path = os.path.join(_config_dir(), "last setup.json")
    try:
        project = Project.load(path)
    except Exception:
        project = Project()
    report = run(project)
    report.lines.insert(0, f"Setup read from: {path}")
    text = report.text()
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
