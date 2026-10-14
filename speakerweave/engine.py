"""The mixing engine (no sound card code in here, so it can be tested offline).

Engine.process() takes one block of incoming audio and returns one block per
output device. AdaptiveFifo sits between the engine and each sound card and
keeps devices with slightly different clocks in step with each other.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import numpy as np

from .dsp import SpeakerChain, PinkNoise, db_to_lin
from .mixer import build_matrix
from .model import Project, OFF, source_layout_for


@dataclass
class _SpeakerPlan:
    spk_id: str
    channel: int
    role_index: int         # row of the mixing matrix, -1 = no signal
    audible: bool
    chain: SpeakerChain
    slot: int = -1          # column in the extra sound mix, -1 = no extra sound
    plays: bool = True      # not muted, and not silenced by another speaker's solo


@dataclass
class _DevicePlan:
    dev_id: str
    channels: int
    speakers: list


@dataclass
class _Plan:
    matrix: np.ndarray
    devices: list
    master: float
    # for a surround source that is only carrying stereo right now (music, video):
    # the same routing with the stereo pair spread over every speaker
    stereo_matrix: np.ndarray = None
    extra_channels: tuple = ()          # source channels other than front left and right
    front_pair: tuple = ()              # the source channels of front left and right
    # extra sources: {source id: matrix (speaker slots, its channels)}
    extras: dict = None
    slots: int = 0


SURROUND_HOLD_S = 3.0      # surround channels silent this long: treat the sound as stereo
PAIR_HOLD_S = 1.0          # stereo means both fronts playing: within this long of each other
METRONOME_LEAD_S = 0.08    # the first click comes this long after the metronome is switched on
QUIET = 1e-4

class Engine:
    def __init__(self, project: Project):
        self.project = project
        self.sr = 48000.0
        self.src_channels = 2
        self.source_roles: list[str] = ["FL", "FR"]
        self.chains: dict[str, SpeakerChain] = {}
        self._plan: _Plan | None = None
        self._master_now = 0.0
        self._noise = PinkNoise(7)
        self._identify_id = ""
        self._identify_left = 0
        self._identify_total = 0
        self._identify_kind = "noise"
        self._sweep_phase = 0.0
        self._custom = None                # samples of a sound the user added, while it plays
        self.test_only = False             # True: nothing but test sounds reach the speakers
        self.input_peaks = np.zeros(2)
        self.output_peaks: dict = {}      # {device id: peak of each channel}, for the meters
        # extra sources (SimHub effects, a spotter app ...): filled by their own capture
        # streams, read here block by block
        self.extra_fifos: dict = {}       # {source id: AdaptiveFifo}
        self.extra_peaks: dict = {}       # {source id: peak of each channel}, for the meters
        self.surround_now = False         # the source is carrying more than stereo right now
        self._surround_until = 0
        self._left_until = self._right_until = 0
        self._samples = 0
        self._last_matrix = None
        self.layout_override = ""      # set by the built in test signal
        self.windows_gain = 1.0        # the Windows volume of the device listened to (winvolume.py)
        # the metronome: (beats per minute, ((speaker id, low), ...), one after another).
        # Replaced as a whole by set_metronome, read once per block by the audio thread.
        self._metro = (0.0, (), False)
        self._metro_seen = self._metro
        self._metro_clock = 0
        self._metro_next = 0
        self._metro_beat = 0
        self._metro_active: list = []      # clicks still sounding: (speaker id, start, samples)
        self._click_cache: dict = {}
        self.block_count = 0           # goes up with every processed block
        self._guard = threading.Lock()

    # ---------------------------------------------------------- setup (UI thread)
    def configure(self, sr: float, src_channels: int) -> None:
        with self._guard:
            self.sr = float(sr)
            self.src_channels = int(src_channels)
            self.chains = {}
            self.input_peaks = np.zeros(self.src_channels)
            self._master_now = 0.0
        self.rebuild()

    def rebuild(self) -> None:
        """Recompute routing from the project. Safe to call while running."""
        p = self.project
        with self._guard:
            self.source_roles = source_layout_for(
                self.src_channels, self.layout_override or p.source_layout)
            # Only roles that really have a speaker count as "the room". The sound
            # of any other channel is shared between the speakers that do exist,
            # so nothing goes missing while a role is still unassigned.
            room = p.roles_in_use()
            options = dict(upmix=p.upmix, bass_redirect=p.bass_redirect,
                           bass_redirect_db=p.bass_redirect_db, lfe_to_mains=p.lfe_to_mains)
            stereo_matrix, extra, stereo_roles, front_pair = None, (), None, ()
            roles = self.source_roles
            real_source = p.input_kind != "test" and not self.layout_override
            if real_source and p.upmix and len(roles) > 2 and "FL" in roles and "FR" in roles:
                # Windows plays stereo into a 7.1 device with the other channels silent.
                # Then the stereo pair is spread like a stereo source would be.
                stereo_roles = [r if r in ("FL", "FR") else OFF for r in roles]
                stereo_matrix = True
                extra = tuple(i for i, r in enumerate(roles) if r not in ("FL", "FR", OFF))
                front_pair = (roles.index("FL"), roles.index("FR"))
            any_solo = any(s.solo for d, s in p.all_speakers() if d.enabled)
            shaker = db_to_lin(p.shaker_game_db) if p.shaker_game_on else 0.0
            matrix = build_matrix(self.source_roles, room, shaker_gain=shaker, **options)
            if stereo_matrix is not None:
                stereo_matrix = build_matrix(stereo_roles, room, shaker_gain=shaker, **options)
            # which speakers get extra sound, and from which channels
            targets = {}
            for src in p.extra_sources:
                if not src.enabled:
                    continue
                for route in src.routes:
                    for spk_id in route.targets:
                        targets.setdefault(spk_id, len(targets))
            devices = []
            alive = set()
            for dev in p.devices:
                if not dev.enabled:
                    continue
                plans = []
                for spk in dev.speakers:
                    if spk.channel >= dev.channels:
                        continue
                    chain = self.chains.get(spk.id)
                    if chain is None:
                        chain = self.chains[spk.id] = SpeakerChain(self.sr)
                    chain.configure(spk, dev.trim_ms, dev.gain_db)
                    alive.add(spk.id)
                    ridx = room.index(spk.role) if spk.role in room else -1
                    plays = not spk.mute and (spk.solo or not any_solo)
                    audible = ridx >= 0 and plays
                    plans.append(_SpeakerPlan(spk.id, spk.channel, ridx, audible, chain,
                                              targets.get(spk.id, -1), plays))
                devices.append(_DevicePlan(dev.id, dev.channels, plans))
            for gone in set(self.chains) - alive:
                del self.chains[gone]
            extras = {}
            for src in p.extra_sources:
                if not src.enabled or not src.routes:
                    continue
                width = max(r.channel for r in src.routes) + 1
                mix = np.zeros((len(targets), width))
                for route in src.routes:
                    for spk_id in route.targets:
                        mix[targets[spk_id], route.channel] += db_to_lin(route.gain_db)
                if np.any(mix):
                    extras[src.id] = mix
            self._plan = _Plan(matrix, devices, 0.0 if p.muted else db_to_lin(p.master_db),
                               stereo_matrix=stereo_matrix, extra_channels=extra,
                               front_pair=front_pair, extras=extras, slots=len(targets))
            self._last_matrix = None
            self.output_peaks = {d.dev_id: np.zeros(d.channels) for d in devices}

    def update_speaker(self, spk_id: str) -> None:
        """Push new EQ / gain / delay settings of one speaker to the audio thread."""
        dev, spk = self.project.find_speaker(spk_id)
        chain = self.chains.get(spk_id)
        if spk is not None and chain is not None:
            chain.configure(spk, dev.trim_ms, dev.gain_db)

    SWEEP_FROM, SWEEP_TO = 20.0, 16000.0

    def identify(self, spk_id: str, seconds: float = 1.5, kind: str = "noise", samples=None) -> None:
        """Play a test sound on one speaker only. kind "noise" is a short burst
        of pink noise, "sweep" a tone gliding from deep bass to high treble,
        which makes the speaker's frequency limits easy to hear. kind "custom"
        plays samples (mono, at the engine's sample rate), a sound the user added."""
        if kind == "custom":
            samples = np.asarray(samples if samples is not None else [], dtype=np.float64)
            self._custom = samples
            seconds = len(samples) / self.sr
        else:
            self._custom = None
        self._identify_kind = kind
        self._identify_total = int(seconds * self.sr)
        self._sweep_phase = 0.0
        self._identify_id = spk_id
        self._identify_left = self._identify_total

    @property
    def identifying(self) -> bool:
        return self._identify_left > 0

    def _test_sound(self, n: int) -> np.ndarray:
        done = self._identify_total - self._identify_left
        if self._identify_kind == "custom" and self._custom is not None:
            chunk = self._custom[done:done + n]
            if len(chunk) < n:
                chunk = np.concatenate([chunk, np.zeros(n - len(chunk))])
            return chunk            # already faded in and out when it was added
        if self._identify_kind == "sweep":
            t = (done + np.arange(n)) / self.sr
            length = max(self._identify_total / self.sr, 0.1)
            freq = self.SWEEP_FROM * (self.SWEEP_TO / self.SWEEP_FROM) ** np.clip(t / length, 0.0, 1.0)
            phase = self._sweep_phase + np.cumsum(2.0 * np.pi * freq / self.sr)
            self._sweep_phase = float(phase[-1] % (2.0 * np.pi))
            sound = np.sin(phase) * 0.25
        else:
            sound = self._noise.block(n) * 0.2
        # soft start and end, so there is no click
        fade = max(1, int(0.02 * self.sr))
        pos = done + np.arange(n)
        envelope = np.clip(np.minimum(pos, self._identify_total - pos) / fade, 0.0, 1.0)
        return sound * envelope

    # ---------------------------------------------------------- metronome
    def set_metronome(self, bpm: float, targets, turns: bool = False) -> None:
        """Steady clicks instead of the PC sound. targets: [(speaker id, low)] in the
        order they take turns. low: a thump for subwoofers and shakers, which cannot
        play a click. Every click leaves the engine at exactly the same moment, so what
        is heard out of step comes from the speakers' delays and distances."""
        self._metro = (float(bpm), tuple((str(i), bool(low)) for i, low in targets), bool(turns))

    def stop_metronome(self) -> None:
        self._metro = (0.0, (), False)

    @property
    def metronome_on(self) -> bool:
        return self._metro[0] > 0 and bool(self._metro[1])

    def _click(self, low: bool, accent: bool) -> np.ndarray:
        key = (low, accent, self.sr)
        wave = self._click_cache.get(key)
        if wave is None:
            if low:     # a short thump a subwoofer or shaker can play
                t = np.arange(int(0.07 * self.sr)) / self.sr
                env = (1.0 - np.exp(-t / 0.002)) * np.exp(-t / 0.018)
                wave = np.sin(2 * np.pi * (70.0 if accent else 55.0) * t) * env * (0.9 if accent else 0.7)
            else:       # a sharp tick: easy to hear when two arrive a few ms apart
                t = np.arange(int(0.012 * self.sr)) / self.sr
                env = np.exp(-t / 0.0018)
                wave = np.sin(2 * np.pi * (3200.0 if accent else 2200.0) * t) * env * (0.7 if accent else 0.5)
            self._click_cache[key] = wave
        return wave

    def _metronome(self, n: int, metro) -> dict:
        """{speaker id: (n,) samples} for this block."""
        bpm, targets, turns = metro
        start = self._metro_clock
        end = start + n
        if self._metro_seen[0] <= 0 or not self._metro_seen[1]:
            # just switched on: begin a moment from now, on the first beat
            self._metro_next = start + int(METRONOME_LEAD_S * self.sr)
            self._metro_beat = 0
            self._metro_active = []
        self._metro_seen = metro
        period = max(1, int(round(self.sr * 60.0 / bpm)))
        while self._metro_next < end:
            beat = self._metro_beat
            if turns:
                chosen = [targets[beat % len(targets)]]
                accent = beat % len(targets) == 0
            else:
                chosen = targets
                accent = beat % 4 == 0
            for spk_id, low in chosen:
                self._metro_active.append((spk_id, self._metro_next, self._click(low, accent)))
            self._metro_beat += 1
            self._metro_next += period
        out = {}
        still = []
        for spk_id, at, wave in self._metro_active:
            a, b = max(at, start), min(at + len(wave), end)
            if a < b:
                buf = out.get(spk_id)
                if buf is None:
                    buf = out[spk_id] = np.zeros(n)
                buf[a - start:b - start] += wave[a - at:b - at]
            if at + len(wave) > end:
                still.append((spk_id, at, wave))
        self._metro_active = still
        self._metro_clock = end
        return out

    def level(self, spk_id: str) -> float:
        chain = self.chains.get(spk_id)
        return chain.peak if chain else 0.0

    # ---------------------------------------------------------- audio thread
    def process(self, block: np.ndarray) -> dict:
        """block: (frames, source channels). Returns {device id: (frames, channels) float32}."""
        plan = self._plan
        if plan is None:
            return {}
        n = block.shape[0]
        self.block_count += 1
        x = np.asarray(block, dtype=np.float64)
        want = plan.matrix.shape[1]
        if x.shape[1] > want:
            x = x[:, :want]
        elif x.shape[1] < want:
            x = np.hstack([x, np.zeros((n, want - x.shape[1]))])
        peaks = np.max(np.abs(x), axis=0) if n else np.zeros(x.shape[1])
        if len(peaks) == len(self.input_peaks):
            self.input_peaks = np.maximum(peaks, self.input_peaks * 0.9)
        else:
            self.input_peaks = peaks
        matrix = plan.matrix
        self._samples += n
        if plan.stereo_matrix is not None:
            if plan.extra_channels and float(np.max(peaks[list(plan.extra_channels)])) > QUIET:
                self._surround_until = self._samples + int(SURROUND_HOLD_S * self.sr)
            self.surround_now = self._samples < self._surround_until
            # Stereo music has both fronts playing. One front alone (a channel test, a
            # game's sound coming from the left) stays on its own speakers.
            left, right = plan.front_pair
            hold = int(PAIR_HOLD_S * self.sr)
            if float(peaks[left]) > QUIET:
                self._left_until = self._samples + hold
            if float(peaks[right]) > QUIET:
                self._right_until = self._samples + hold
            pair = self._samples < self._left_until and self._samples < self._right_until
            if not self.surround_now and pair:
                matrix = plan.stereo_matrix
        else:
            self.surround_now = len(self.source_roles) > 2
        last = self._last_matrix
        if last is not None and last is not matrix and last.shape == matrix.shape and n:
            # switching between stereo and surround: blend over one block, no click
            ramp = np.linspace(0.0, 1.0, n)[:, None]
            bus = (x @ last.T) * (1.0 - ramp) + (x @ matrix.T) * ramp
        else:
            bus = x @ matrix.T
        self._last_matrix = matrix

        ident_id = self._identify_id if self._identify_left > 0 else ""
        noise = None
        if ident_id:
            noise = self._test_sound(n)
            self._identify_left -= n
        metro = self._metro
        clicks = None
        if metro[0] > 0 and metro[1]:
            clicks = self._metronome(n, metro)
        else:
            self._metro_seen = metro

        want = plan.master * self.windows_gain
        if self._master_now != want:
            master = np.linspace(self._master_now, want, n, endpoint=True)
            self._master_now = want
        else:
            master = want

        extra = self._extra_mix(plan, n)
        silence = np.zeros(n)
        outs = {}
        for dev in plan.devices:
            out = np.zeros((n, dev.channels), dtype=np.float32)
            for sp in dev.speakers:
                if ident_id:
                    sig = noise if sp.spk_id == ident_id else silence
                elif clicks is not None:
                    sig = clicks.get(sp.spk_id, silence)      # the PC sound waits meanwhile
                elif self.test_only or not sp.plays:
                    sig = silence
                else:
                    sig = bus[:, sp.role_index] if sp.audible else silence
                    if extra is not None and sp.slot >= 0:
                        sig = sig + extra[:, sp.slot]
                out[:, sp.channel] = sp.chain.process(sig) * master
            np.clip(out, -1.0, 1.0, out=out)
            outs[dev.dev_id] = out
            if n:
                level = np.max(np.abs(out), axis=0)
                old = self.output_peaks.get(dev.dev_id)
                self.output_peaks[dev.dev_id] = level if old is None or len(old) != len(level) \
                    else np.maximum(level, old * 0.9)
        return outs

    def _extra_mix(self, plan: _Plan, n: int):
        """The extra sources' sound for every speaker that gets some: (n, slots)."""
        if not self.extra_fifos:
            return None
        total = None
        for src_id, fifo in list(self.extra_fifos.items()):
            block = fifo.read(n)
            if n:
                level = np.max(np.abs(block), axis=0)
                old = self.extra_peaks.get(src_id)
                self.extra_peaks[src_id] = level if old is None or len(old) != len(level) \
                    else np.maximum(level, old * 0.9)
            mix = (plan.extras or {}).get(src_id)
            if mix is None or not plan.slots:
                continue
            width = min(mix.shape[1], block.shape[1])
            part = block[:, :width].astype(np.float64) @ mix[:, :width].T
            total = part if total is None else total + part
        return total


class AdaptiveFifo:
    """Buffer between the engine and one sound card.

    Every sound card runs on its own clock, so over minutes they drift apart.
    This buffer watches how full it is and plays back a tiny bit faster or
    slower (a few hundredths of a percent, far too small to hear) so every
    device stays the same distance behind the input. It also slowly learns
    the steady speed difference of its device, so in the long run every
    buffer sits exactly on the target and the devices line up with each other.
    """

    KP = 1.0e-6          # speed correction per frame of fill error
    KI = 1.0e-8          # learning rate of the steady difference (per frame, per second)
    MAX_CORR = 0.003     # never correct by more than 0.3 %
    TAU = 1.0            # seconds of smoothing on the fill measurement

    MARGIN_S = 0.003     # room for the uneven timing of Windows, to start with
    MARGIN_STEP_S = 0.003    # more room after each time the device ran dry while sound flowed
    MARGIN_MAX_S = 0.04

    def __init__(self, channels: int, sr: float, target_ms: float, capacity_s: float = 1.5,
                 block: int = 0):
        """target_ms is the safety buffer chosen by the person. With block (the
        frames the engine writes at a time) the buffer never goes below what this
        device needs to play cleanly (see need), so 0 ms means "as small as works"."""
        self.channels = channels
        self.sr = float(sr)
        self.block = int(block)
        self._max_read = self.block          # until the device asks, guess its blocks match ours
        self._margin = int(self.MARGIN_S * sr) if self.block else 0
        self._last_write = 0.0
        self.target = max(64, int(target_ms * sr / 1000.0), self.need)
        self._cap = max(int(capacity_s * sr), self.target * 4)
        self._buf = np.zeros((self._cap, channels), dtype=np.float32)
        self._n = 0
        self._pos = 0.0
        self._primed = False
        self._err = 0.0
        self._learned = 0.0
        self.ratio = 1.0
        # if a device falls this far out of line (after a stall), jump back at once
        self._resync = max(int(0.015 * sr), self.target // 3)
        self.resyncs = 0
        self.underruns = 0
        self.overruns = 0
        self._lock = threading.Lock()

    @property
    def need(self) -> int:
        """The smallest target (frames left just after the device took a block) that
        never runs dry: our blocks arrive whole, so up to one and a half of them can be
        missing when the device asks, plus the room it has needed so far for uneven
        timing. 0 without a block size."""
        if not self.block:
            return 0
        return self.block + self.block // 2 + self._margin

    def set_target(self, frames: int) -> None:
        """Every output gets the same target, so they all stay the same distance
        behind the PC and in line with each other."""
        with self._lock:
            frames = max(64, int(frames))
            if frames != self.target:
                self.target = frames
                self._resync = max(int(0.015 * self.sr), self.target // 3)
                if self.target * 4 > self._cap:
                    grown = np.zeros((self.target * 4, self.channels), dtype=np.float32)
                    grown[: self._n] = self._buf[: self._n]
                    self._buf, self._cap = grown, self.target * 4

    @property
    def glitches(self) -> int:
        """How often the sound of this device was interrupted or had to jump."""
        return self.underruns + self.overruns + self.resyncs

    @property
    def fill_ms(self) -> float:
        return self._n * 1000.0 / self.sr

    def _drop(self, frames: int) -> None:
        frames = min(frames, self._n)
        if frames > 0:
            self._buf[: self._n - frames] = self._buf[frames: self._n]
            self._n -= frames

    def write(self, block: np.ndarray) -> None:
        with self._lock:
            self._last_write = time.perf_counter()
            n = len(block)
            if n > self._cap:
                block, n = block[-self._cap:], self._cap
            if self._n + n > self._cap or self._n > self.target * 4:
                # the sound card stopped taking audio: jump back to the target
                self._drop(self._n + n - self.target)
                self.overruns += 1
                self._err = 0.0
            n = min(n, self._cap - self._n)
            self._buf[self._n: self._n + n] = block[-n:] if n else block[:0]
            self._n += n

    def read(self, frames: int) -> np.ndarray:
        with self._lock:
            if frames > self._max_read and self.block:
                self._max_read = frames              # the device takes bigger blocks than guessed
            if not self._primed:
                # with a block size the target is what is left after this read, so the
                # fill is measured the same way from the very first block
                keep = self.target + (frames if self.block else 0)
                if self._n < keep:
                    return np.zeros((frames, self.channels), dtype=np.float32)
                self._drop(self._n - keep)          # same starting latency on every device
                self._primed = True
                self._pos = 0.0
                self._err = 0.0
                self.ratio = 1.0 + self._learned
            r = self.ratio
            last = self._pos + (frames - 1) * r
            if int(last) + 1 >= self._n:
                self._primed = False
                self.underruns += 1
                # ran dry while sound was still arriving: this device needs more room.
                # (When the PC simply stops sending, nothing is learned from it.)
                if self.block and time.perf_counter() - self._last_write < 2.5 * self.block / self.sr:
                    self._margin = min(self._margin + int(self.MARGIN_STEP_S * self.sr),
                                       int(self.MARGIN_MAX_S * self.sr))
                return np.zeros((frames, self.channels), dtype=np.float32)
            idx = self._pos + np.arange(frames) * r
            i0 = idx.astype(np.int64)
            frac = (idx - i0).astype(np.float32)[:, None]
            out = self._buf[i0] * (1.0 - frac) + self._buf[i0 + 1] * frac
            end = self._pos + frames * r
            used = int(end)
            self._pos = end - used
            self._drop(used)
            # slow control loop on the fill level
            alpha = min(1.0, frames / (self.sr * self.TAU))
            self._err += alpha * ((self._n - self.target) - self._err)
            learned = self._learned + self.KI * self._err * frames / self.sr
            self._learned = min(max(learned, -self.MAX_CORR), self.MAX_CORR)
            corr = self.KP * self._err + self._learned
            self.ratio = 1.0 + min(max(corr, -self.MAX_CORR), self.MAX_CORR)
            if abs(self._err) > self._resync:
                # Too far off to creep back unnoticed: one small jump now is better
                # than this device playing out of line with the others for a minute.
                if self._err > 0:
                    self._drop(self._n - self.target)
                else:
                    self._primed = False
                self._err = 0.0
                self.ratio = 1.0 + self._learned
                self.resyncs += 1
            return out
