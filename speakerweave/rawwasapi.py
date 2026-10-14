"""Playing to and listening in on a Windows sound output with nothing in between.

Sound libraries such as PortAudio open a stream in a format of their own choosing and
let Windows convert it. This talks to Windows' own audio interface (WASAPI) directly,
always in the exact format Windows mixes the output in, so Windows converts nothing:
what is written is what reaches the output, and what is heard is what the output got.
Used by the channel test to tell apart a fault in a converter from one in the output.
"""
from __future__ import annotations

import ctypes
import time
from ctypes import POINTER, byref, c_int, c_longlong, c_uint32, c_uint64, c_void_p, c_wchar_p

import numpy as np

from . import windefault
from .wincom import CLSCTX_ALL, GUID, HRESULT, Apartment, guid, method, release

IID_AUDIO_CLIENT = "1CB9AD4C-DBFA-4C32-B178-C2F568A703B2"
IID_RENDER_CLIENT = "F294ACFC-3146-4483-A7BF-ADDCA7C260E2"
IID_CAPTURE_CLIENT = "C8ADBD64-E71E-48A0-A4DE-185C395CD317"
SHARED = 0
LOOPBACK = 0x00020000
SILENT = 0x2
BUFFER_S = 0.2


class Client:
    """One shared mode stream on an output: playing to it, or (loopback) listening in."""

    def __init__(self, com, device_id: str, loopback: bool = False):
        self.com, self.loopback = com, loopback
        enum = com.create(windefault.CLSID_ENUMERATOR, windefault.IID_ENUMERATOR)
        device = c_void_p()
        try:
            method(enum, 5, HRESULT, c_wchar_p, POINTER(c_void_p))(device_id, byref(device))
        finally:
            release(enum)
        self.client, self.service = c_void_p(), c_void_p()
        try:
            method(device, 3, HRESULT, POINTER(GUID), c_uint32, c_void_p, POINTER(c_void_p))(
                byref(guid(IID_AUDIO_CLIENT)), CLSCTX_ALL, None, byref(self.client))
        finally:
            release(device)
        mix = c_void_p()
        method(self.client, 8, HRESULT, POINTER(c_void_p))(byref(mix))          # GetMixFormat
        try:
            self.format = windefault._read_format(mix.value)
            if not (self.format["float"] and self.format["bits"] == 32):
                raise RuntimeError(f"Windows mixes this output in an unusual format: {self.format}")
            method(self.client, 3, HRESULT, c_int, c_uint32, c_longlong, c_longlong, c_void_p, c_void_p)(
                SHARED, LOOPBACK if loopback else 0, int(BUFFER_S * 1e7), 0, mix.value, None)
        finally:
            com.free(mix)
        self.channels = int(self.format["channels"])
        self.rate = float(self.format["rate"])
        size = c_uint32()
        method(self.client, 4, HRESULT, POINTER(c_uint32))(byref(size))           # GetBufferSize
        self.frames = size.value
        method(self.client, 14, HRESULT, POINTER(GUID), POINTER(c_void_p))(        # GetService
            byref(guid(IID_CAPTURE_CLIENT if loopback else IID_RENDER_CLIENT)), byref(self.service))
        self._padding = method(self.client, 6, HRESULT, POINTER(c_uint32))
        if loopback:
            self._get = method(self.service, 3, HRESULT, POINTER(c_void_p), POINTER(c_uint32),
                               POINTER(c_uint32), POINTER(c_uint64), POINTER(c_uint64))
            self._release = method(self.service, 4, HRESULT, c_uint32)
            self._next = method(self.service, 5, HRESULT, POINTER(c_uint32))
        else:
            self._get = method(self.service, 3, HRESULT, c_uint32, POINTER(c_void_p))
            self._release = method(self.service, 4, HRESULT, c_uint32, c_uint32)

    def start(self) -> None:
        method(self.client, 10, HRESULT)()

    def stop(self) -> None:
        method(self.client, 11, HRESULT)()

    def close(self) -> None:
        release(self.service)
        release(self.client)

    # playing
    def room(self) -> int:
        padding = c_uint32()
        self._padding(byref(padding))
        return self.frames - padding.value

    def write(self, block: np.ndarray) -> None:
        """block: float32 frames of exactly self.channels channels, at most room() of them."""
        n = len(block)
        if n <= 0:
            return
        data = c_void_p()
        self._get(n, byref(data))
        ctypes.memmove(data.value, np.ascontiguousarray(block, dtype=np.float32).tobytes(),
                       n * self.channels * 4)
        self._release(n, 0)

    # listening in
    def read(self) -> np.ndarray:
        chunks = []
        packet = c_uint32()
        while True:
            self._next(byref(packet))
            if not packet.value:
                break
            data, n, flags, pos, qpc = c_void_p(), c_uint32(), c_uint32(), c_uint64(), c_uint64()
            self._get(byref(data), byref(n), byref(flags), byref(pos), byref(qpc))
            count = n.value * self.channels
            if flags.value & SILENT or not data.value:
                chunk = np.zeros(count, np.float32)
            else:
                chunk = np.frombuffer((ctypes.c_float * count).from_address(data.value), np.float32).copy()
            self._release(n.value)
            chunks.append(chunk.reshape(-1, self.channels))
        return np.concatenate(chunks) if chunks else np.zeros((0, self.channels), np.float32)


def play_and_listen(device_id: str, make_block, seconds: float, other_player=None) -> tuple:
    """Plays make_block(start_frame, frames, channels, rate) straight to the output while
    listening in on it. With other_player, that plays instead: other_player() starts
    playing by itself and returns a function that stops it.
    Returns (what was heard, rate, channels)."""
    with Apartment() as com:
        ear = Client(com, device_id, loopback=True)
        mouth = None if other_player is not None else Client(com, device_id)
        heard, stop_other = [], None
        try:
            ear.start()
            pos = 0
            if mouth is not None:
                first = mouth.room()
                mouth.write(make_block(pos, first, mouth.channels, mouth.rate))
                pos += first
                mouth.start()
            else:
                stop_other = other_player()
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                if mouth is not None:
                    room = mouth.room()
                    if room:
                        mouth.write(make_block(pos, room, mouth.channels, mouth.rate))
                        pos += room
                heard.append(ear.read())
                time.sleep(0.005)
            heard.append(ear.read())
        finally:
            if stop_other is not None:
                stop_other()
            for stream in (mouth, ear):
                if stream is not None:
                    try:
                        stream.stop()
                    except OSError:
                        pass
                    stream.close()
    data = np.concatenate(heard) if heard else np.zeros((0, ear.channels), np.float32)
    return data, ear.rate, ear.channels
