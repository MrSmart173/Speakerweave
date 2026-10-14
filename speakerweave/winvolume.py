"""Following the Windows volume of the device SpeakerWeave listens to.

The volume keys of a keyboard, the volume wheel of a mouse or headset, and the
Windows volume slider all change the volume of the Windows sound output. When that
output is the virtual device SpeakerWeave listens to, Windows records the sound for
SpeakerWeave before that volume is applied, so on its own the speakers would ignore
it. This reads the device's volume and mute a few times a second, and SpeakerWeave
applies them to every speaker.
"""
from __future__ import annotations

import sys
import threading
import time
from ctypes import POINTER, byref, c_float, c_int, c_uint32, c_void_p, c_wchar_p

from . import windefault
from .wincom import CLSCTX_ALL, GUID, HRESULT, Apartment, guid, method, release

IID_ENDPOINT_VOLUME = "5CDF2C82-841E-4546-9722-0CF74078229A"
INTERVAL_S = 0.05            # 20 looks a second: a volume wheel feels instant
RETRY_S = 2.0                # a device that could not be opened is tried again this often


class _EndpointVolume:
    """IAudioEndpointVolume of one output device."""

    def __init__(self, com, name: str):
        dev_id = windefault.find(name)
        if not dev_id:
            raise LookupError(name)
        enum = com.create(windefault.CLSID_ENUMERATOR, windefault.IID_ENUMERATOR)
        device = c_void_p()
        try:
            method(enum, 5, HRESULT, c_wchar_p, POINTER(c_void_p))(dev_id, byref(device))
        finally:
            release(enum)
        self.vol = c_void_p()
        try:
            method(device, 3, HRESULT, POINTER(GUID), c_uint32, c_void_p, POINTER(c_void_p))(
                byref(guid(IID_ENDPOINT_VOLUME)), CLSCTX_ALL, None, byref(self.vol))
        finally:
            release(device)
        self._level = method(self.vol, 8, HRESULT, POINTER(c_float))      # GetMasterVolumeLevel (dB)
        self._scalar = method(self.vol, 9, HRESULT, POINTER(c_float))     # ... LevelScalar (slider)
        self._mute = method(self.vol, 15, HRESULT, POINTER(c_int))        # GetMute

    def read(self) -> tuple:
        """(gain, muted, slider percent). The gain is the level Windows itself would
        use for this slider position."""
        db, scalar, muted = c_float(), c_float(), c_int()
        self._level(byref(db))
        self._scalar(byref(scalar))
        self._mute(byref(muted))
        return 10.0 ** (db.value / 20.0), bool(muted.value), scalar.value * 100.0

    def close(self) -> None:
        release(self.vol)


def _open_windows(com, name: str):
    return _EndpointVolume(com, name)


class VolumeFollower:
    """Watches one device's Windows volume in a thread of its own and reports changes
    with on_change(gain, muted, percent), called from that thread."""

    def __init__(self, on_change, open_device=None):
        self.on_change = on_change
        self._open = open_device or _open_windows
        self._name = ""
        self._thread = None
        self._stop = threading.Event()
        self.gain, self.muted, self.percent = 1.0, False, 100.0
        self.following = ""          # the device whose volume is in use right now

    @property
    def available(self) -> bool:
        """Windows itself (not merely something that says it is), or a test's own opener."""
        return self._open is not _open_windows or sys.platform == "win32"

    def follow(self, name: str) -> None:
        """name: the Windows name of the output device to follow, "" for none."""
        self._name = name or ""
        if not self.available:
            return
        if self._name and (self._thread is None or not self._thread.is_alive()):
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="Windows volume", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _report(self, gain: float, muted: bool, percent: float) -> None:
        if (abs(gain - self.gain) > 1e-4 or muted != self.muted
                or abs(percent - self.percent) > 0.05):
            self.gain, self.muted, self.percent = gain, muted, percent
            try:
                self.on_change(gain, muted, percent)
            except Exception:
                pass

    def _run(self) -> None:
        with _apartment(self._open):
            current, current_name, retry_at = None, None, 0.0
            while not self._stop.is_set():
                name = self._name
                if name != current_name:
                    if current is not None:
                        current.close()
                    current, current_name, retry_at = None, name, 0.0
                    self.following = ""
                if name and current is None and time.monotonic() >= retry_at:
                    try:
                        current = self._open(_COM.get(), name)
                        self.following = name
                    except Exception:
                        retry_at = time.monotonic() + RETRY_S
                if current is not None:
                    try:
                        self._report(*current.read())
                    except Exception:            # the device went away
                        current.close()
                        current, self.following = None, ""
                        retry_at = time.monotonic() + RETRY_S
                if current is None:
                    self._report(1.0, False, 100.0)  # nothing to follow: full volume
                self._stop.wait(INTERVAL_S)
            if current is not None:
                current.close()
            self.following = ""


class _COM:
    """The COM apartment of the follower thread (None when a test supplies its own opener)."""
    _local = threading.local()

    @classmethod
    def get(cls):
        return getattr(cls._local, "com", None)


class _apartment:
    def __init__(self, opener):
        self.real = opener is _open_windows

    def __enter__(self):
        if self.real:
            self.com = Apartment().__enter__()
            _COM._local.com = self.com
        return self

    def __exit__(self, *exc):
        if self.real:
            _COM._local.com = None
            self.com.__exit__(*exc)
        return False

