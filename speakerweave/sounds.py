"""Test sounds the user adds: up to five sound files that can be played on a
single speaker, next to the built in noise and sweep.

A chosen file is read once, turned into a short mono sound at 48 kHz and kept
as a copy in SpeakerWeave's own folder, so it keeps working when the original
file is moved or deleted. WAV files are read directly. Everything else (MP3,
M4A, AAC, WMA, FLAC and whatever else Windows can play) is read through
Windows itself (Media Foundation), so nothing extra has to be installed.
"""
from __future__ import annotations

import ctypes
import os
import struct
import sys
import wave
from math import gcd

import numpy as np

MAX_SOUNDS = 5
MAX_SECONDS = 30.0
RATE = 48000
FILE_FILTER = ("Sound files (*.wav *.mp3 *.m4a *.aac *.wma *.flac *.ogg *.opus *.aiff *.aif *.mp4);;"
               "All files (*)")


def folder(config_dir: str) -> str:
    return os.path.join(config_dir, "Test sounds")


def empty_slots() -> list:
    return [{} for _ in range(MAX_SOUNDS)]


def clean_slots(slots) -> list:
    """Exactly MAX_SOUNDS entries, each {} or {"name", "file", "seconds"}."""
    out = []
    for item in list(slots or [])[:MAX_SOUNDS]:
        ok = isinstance(item, dict) and item.get("file") and item.get("name")
        out.append({"name": str(item["name"]), "file": str(item["file"]),
                    "seconds": float(item.get("seconds", 0.0))} if ok else {})
    return out + [{} for _ in range(MAX_SOUNDS - len(out))]


# ------------------------------------------------------------------ reading files

def read_wav(path: str) -> tuple[np.ndarray, int]:
    """(frames, channels) float64 and the sample rate of a WAV file. Handles
    8, 16, 24 and 32 bit whole numbers and 32 or 64 bit floating point."""
    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) < 12 or data[:4] not in (b"RIFF", b"RF64") or data[8:12] != b"WAVE":
        raise ValueError("This is not a WAV file.")
    pos, fmt, raw = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt = body
        elif cid == b"data":
            raw = data[pos + 8:] if size in (0, 0xFFFFFFFF) else body
            if fmt is not None:
                break
        pos += 8 + size + (size & 1)
    if fmt is None or raw is None or len(fmt) < 16:
        raise ValueError("This WAV file has no sound in it.")
    tag, channels, rate, _, align, bits = struct.unpack("<HHIIHH", fmt[:16])
    if tag == 0xFFFE and len(fmt) >= 26:                 # extensible: the real format follows
        tag = struct.unpack("<H", fmt[24:26])[0]
    if channels < 1 or rate < 1000:
        raise ValueError("This WAV file has an unusual layout.")
    width = bits // 8
    frames = len(raw) // (width * channels)
    raw = raw[:frames * width * channels]
    if tag == 3 and bits in (32, 64):
        samples = np.frombuffer(raw, dtype="<f4" if bits == 32 else "<f8").astype(np.float64)
    elif tag == 1 and bits == 8:
        samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0
    elif tag == 1 and bits == 16:
        samples = np.frombuffer(raw, dtype="<i2") / 32768.0
    elif tag == 1 and bits == 24:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        whole = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        whole = np.where(whole >= 1 << 23, whole - (1 << 24), whole)
        samples = whole / float(1 << 23)
    elif tag == 1 and bits == 32:
        samples = np.frombuffer(raw, dtype="<i4") / 2147483648.0
    else:
        raise ValueError(f"WAV files of this kind ({bits} bit, format {tag}) cannot be read.")
    return samples.reshape(-1, channels), int(rate)


def _read_with_windows(path: str, max_seconds: float) -> tuple[np.ndarray, int]:
    """Any file Windows can play, read through Media Foundation."""
    from ctypes import POINTER, byref, c_int64, c_uint32, c_void_p
    from .wincom import GUID, HRESULT, Apartment, guid, method, release

    major = guid("48EBA18E-F8C9-4687-BF11-0A74C9F96A8F")          # MF_MT_MAJOR_TYPE
    audio = guid("73647561-0000-0010-8000-00AA00389B71")          # MFMediaType_Audio
    subtype = guid("F7E34C9A-42E8-4714-B74B-CB29D72C35E5")        # MF_MT_SUBTYPE
    float_pcm = guid("00000003-0000-0010-8000-00AA00389B71")      # MFAudioFormat_Float
    n_channels = guid("37E48BF5-645E-4C5B-89DE-ADA9E29B696A")     # MF_MT_AUDIO_NUM_CHANNELS
    n_rate = guid("5FAEEAE7-0290-4C31-9E8A-C534F68D9DBA")         # MF_MT_AUDIO_SAMPLES_PER_SECOND
    first_audio, all_streams = 0xFFFFFFFD, 0xFFFFFFFE
    end_of_stream = 0x2

    mfplat = ctypes.WinDLL("mfplat")
    reader_dll = ctypes.WinDLL("mfreadwrite")
    mfplat.MFStartup.restype = HRESULT
    mfplat.MFStartup.argtypes = [ctypes.c_ulong, ctypes.c_uint32]
    mfplat.MFShutdown.restype = HRESULT
    mfplat.MFCreateMediaType.restype = HRESULT
    mfplat.MFCreateMediaType.argtypes = [POINTER(c_void_p)]
    create_reader = reader_dll.MFCreateSourceReaderFromURL
    create_reader.restype = HRESULT
    create_reader.argtypes = [ctypes.c_wchar_p, c_void_p, POINTER(c_void_p)]

    with Apartment():
        mfplat.MFStartup(0x00020070, 1)
        reader = c_void_p()
        try:
            create_reader(os.path.abspath(path), None, byref(reader))
            select = method(reader, 4, HRESULT, c_uint32, ctypes.c_int)
            select(all_streams, 0)
            select(first_audio, 1)

            wanted = c_void_p()
            mfplat.MFCreateMediaType(byref(wanted))
            try:
                set_guid = method(wanted, 24, HRESULT, POINTER(GUID), POINTER(GUID))
                set_guid(byref(major), byref(audio))
                set_guid(byref(subtype), byref(float_pcm))
                method(reader, 7, HRESULT, c_uint32, c_void_p, c_void_p)(first_audio, None, wanted)
            finally:
                release(wanted)

            got = c_void_p()
            method(reader, 6, HRESULT, c_uint32, POINTER(c_void_p))(first_audio, byref(got))
            try:
                get_u32 = method(got, 7, HRESULT, POINTER(GUID), POINTER(c_uint32))
                channels, rate = c_uint32(), c_uint32()
                get_u32(byref(n_channels), byref(channels))
                get_u32(byref(n_rate), byref(rate))
            finally:
                release(got)
            channels, rate = max(1, channels.value), max(1, rate.value)

            read = method(reader, 9, HRESULT, c_uint32, c_uint32, POINTER(c_uint32),
                          POINTER(c_uint32), POINTER(c_int64), POINTER(c_void_p))
            limit = int((max_seconds + 1.0) * rate) * channels * 4
            chunks, total = [], 0
            while total < limit:
                stream, flags, stamp, sample = c_uint32(), c_uint32(), c_int64(), c_void_p()
                read(first_audio, 0, byref(stream), byref(flags), byref(stamp), byref(sample))
                if sample.value:
                    buffer = c_void_p()
                    try:
                        method(sample, 41, HRESULT, POINTER(c_void_p))(byref(buffer))
                        where, cap, length = c_void_p(), c_uint32(), c_uint32()
                        method(buffer, 3, HRESULT, POINTER(c_void_p), POINTER(c_uint32),
                               POINTER(c_uint32))(byref(where), byref(cap), byref(length))
                        try:
                            chunks.append(ctypes.string_at(where.value, length.value))
                            total += length.value
                        finally:
                            method(buffer, 4, HRESULT)()
                    finally:
                        release(buffer)
                        release(sample)
                if flags.value & end_of_stream:
                    break
        finally:
            release(reader)
            mfplat.MFShutdown()
    raw = b"".join(chunks)
    raw = raw[:len(raw) // (4 * channels) * 4 * channels]
    samples = np.frombuffer(raw, dtype="<f4").astype(np.float64).reshape(-1, channels)
    return samples, int(rate)


def decode(path: str, max_seconds: float = MAX_SECONDS) -> tuple[np.ndarray, int]:
    """(frames, channels) and the sample rate of a sound file."""
    if not os.path.isfile(path):
        raise ValueError("That file could not be found.")
    if path.lower().endswith((".wav", ".wave")):
        try:
            return read_wav(path)
        except ValueError:
            if not sys.platform.startswith("win"):
                raise
    if not sys.platform.startswith("win"):
        raise ValueError("Only WAV files can be read on this system.")
    try:
        return _read_with_windows(path, max_seconds)
    except OSError as exc:
        raise ValueError("Windows could not read this file. Try a WAV or MP3 file.") from exc


# ------------------------------------------------------------------ shaping

def prepare(samples: np.ndarray, rate: int) -> tuple[np.ndarray, bool]:
    """A mono test sound at RATE: quiet start and end trimmed, at most
    MAX_SECONDS long, a short fade in and out, and a sensible level.
    Returns (sound, was_cut_short)."""
    x = np.asarray(samples, dtype=np.float64)
    mono = x.mean(axis=1) if x.ndim == 2 else x
    loud = np.flatnonzero(np.abs(mono) > 10 ** (-50 / 20))
    if len(loud) == 0:
        raise ValueError("This file is silent.")
    mono = mono[loud[0]:loud[-1] + 1]
    limit = int(MAX_SECONDS * rate)
    cut = len(mono) > limit
    mono = mono[:limit]
    if rate != RATE:
        from scipy.signal import resample_poly
        g = gcd(int(rate), RATE)
        mono = resample_poly(mono, RATE // g, int(rate) // g)
    fade_in, fade_out = int(0.01 * RATE), int(0.05 * RATE)
    if len(mono) > fade_in + fade_out:
        mono[:fade_in] *= np.linspace(0.0, 1.0, fade_in)
        mono[-fade_out:] *= np.linspace(1.0, 0.0, fade_out)
    peak = float(np.max(np.abs(mono))) or 1.0
    return (mono * (0.5 / peak)).astype(np.float32), cut


def write_wav(path: str, mono: np.ndarray, rate: int = RATE) -> None:
    whole = np.clip(np.round(np.asarray(mono) * 32767.0), -32768, 32767).astype("<i2")
    tmp = path + ".tmp"
    with wave.open(tmp, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(whole.tobytes())
    os.replace(tmp, path)


def add(source: str, slot: int, config_dir: str) -> tuple[dict, bool]:
    """Reads source and keeps a ready copy for slot (0 to 4).
    Returns (entry for the settings, was_cut_short)."""
    if not 0 <= slot < MAX_SOUNDS:
        raise ValueError("There are five places for test sounds.")
    samples, rate = decode(source)
    sound, cut = prepare(samples, rate)
    where = folder(config_dir)
    os.makedirs(where, exist_ok=True)
    name = f"sound {slot + 1}.wav"
    write_wav(os.path.join(where, name), sound)
    title = os.path.splitext(os.path.basename(source))[0].strip() or f"Sound {slot + 1}"
    if len(title) > 40:
        title = title[:39] + "…"
    return {"name": title, "file": name, "seconds": round(len(sound) / RATE, 2)}, cut


def remove(entry: dict, config_dir: str) -> None:
    if entry and entry.get("file"):
        try:
            os.remove(os.path.join(folder(config_dir), entry["file"]))
        except OSError:
            pass


def load(entry: dict, config_dir: str, rate: float = RATE):
    """The samples of a stored test sound at the given rate, or None if the
    copy is gone."""
    if not entry or not entry.get("file"):
        return None
    try:
        samples, file_rate = read_wav(os.path.join(folder(config_dir), entry["file"]))
    except (OSError, ValueError):
        return None
    mono = samples.mean(axis=1)
    rate = int(round(rate))
    if rate != file_rate and rate > 0:
        from scipy.signal import resample_poly
        g = gcd(file_rate, rate)
        mono = resample_poly(mono, rate // g, file_rate // g)
    return mono
