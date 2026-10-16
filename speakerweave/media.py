"""What is playing on this PC, and play, pause and skip for it.

Windows keeps track of every app that plays media (Spotify, Apple Music, YouTube in a
browser, the Media Player app ...) for the media keys and the volume flyout: the
"System Media Transport Controls". This reads them through Windows' own interfaces
(WinRT), called with ctypes, so nothing extra has to be installed.

A thread of its own looks once a second, and reports changes with on_change(NowPlaying
or None). Commands (play, pause, next, previous) run on that same thread.
"""
from __future__ import annotations

import ctypes
import queue
import sys
import threading
import time
from ctypes import POINTER, byref, c_bool, c_int32, c_int64, c_uint32, c_void_p, c_wchar_p
from dataclasses import dataclass, field

from .wincom import GUID, guid, method

MANAGER_CLASS = "Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager"
IID_MANAGER_STATICS = "2050C4EE-11A0-57DE-AED7-C97C70338245"
IID_ASYNC_INFO = "00000036-0000-0000-C000-000000000046"
IID_RANDOM_ACCESS_STREAM = "905A0FE1-BC53-11DF-8C49-001E4FC686DA"
IID_INPUT_STREAM = "905A0FE2-BC53-11DF-8C49-001E4FC686DA"
IID_BUFFER_FACTORY = "71AF914D-C10F-484B-BC50-14BC623B3A27"
IID_BUFFER_BYTE_ACCESS = "905A0FEF-BC53-11DF-8C49-001E4FC686DA"
BUFFER_CLASS = "Windows.Storage.Streams.Buffer"

# vtable slots (IInspectable has 6). Checked against Microsoft's windows-rs bindings.
MANAGER_GET_CURRENT_SESSION = 6
SESSION_APP_ID, SESSION_GET_PROPERTIES, SESSION_GET_TIMELINE, SESSION_GET_PLAYBACK = 6, 7, 8, 9
SESSION_COMMANDS = {"play": 10, "pause": 11, "stop": 12, "next": 16, "previous": 17, "toggle": 20}
PROPS_TITLE, PROPS_ARTIST, PROPS_ALBUM, PROPS_THUMBNAIL = 6, 9, 10, 15
PLAYBACK_CONTROLS, PLAYBACK_STATUS = 6, 7
CONTROLS = {"play": 6, "pause": 7, "next": 12, "previous": 13}
TIMELINE_END, TIMELINE_POSITION = 7, 10
ASYNC_STATUS = 7                 # IAsyncInfo
ASYNC_RESULTS = 8                # IAsyncOperation<T>.GetResults
ASYNC_PROGRESS_RESULTS = 10      # IAsyncOperationWithProgress<T, P>.GetResults

STATUS = {0: "closed", 1: "opened", 2: "changing", 3: "stopped", 4: "playing", 5: "paused"}
LOOK_EVERY_S = 1.0
ART_LIMIT = 4 * 1024 * 1024      # album art larger than this is not read

# Windows names the app by its "app user model id". The ones worth a friendlier name:
APP_NAMES = (("spotify", "Spotify"), ("applemusic", "Apple Music"), ("itunes", "iTunes"),
             ("chrome", "Google Chrome"), ("msedge", "Microsoft Edge"), ("firefox", "Firefox"),
             ("308046b0af4a39cb", "Firefox"), ("opera", "Opera"), ("brave", "Brave"),
             ("zunemusic", "Media Player"), ("zunevideo", "Films & TV"), ("vlc", "VLC"),
             ("foobar", "foobar2000"), ("musicbee", "MusicBee"), ("tidal", "TIDAL"),
             ("deezer", "Deezer"), ("amazonmusic", "Amazon Music"), ("youtube", "YouTube"),
             ("discord", "Discord"), ("winamp", "Winamp"), ("aimp", "AIMP"))


def app_name(app_id: str) -> str:
    low = (app_id or "").lower()
    for key, name in APP_NAMES:
        if key in low:
            return name
    base = app_id.split("!")[0].split("\\")[-1]
    if base.lower().endswith(".exe"):
        base = base[:-4]
    return base or "An app"


@dataclass
class NowPlaying:
    app_id: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""
    status: str = "closed"
    can: dict = field(default_factory=dict)      # "play", "pause", "next", "previous": bool
    position_s: float = 0.0
    length_s: float = 0.0
    art: bytes = b""                             # album art or video thumbnail (PNG or JPEG)

    @property
    def app(self) -> str:
        return app_name(self.app_id)

    @property
    def playing(self) -> bool:
        return self.status == "playing"

    def track(self) -> tuple:
        """What it is, without how it is going: a new track when this changes."""
        return (self.app_id, self.title, self.artist, self.album)

    def same(self, other) -> bool:
        return other is not None and self.track() == other.track() and self.status == other.status \
            and self.can == other.can


class _WinRT:
    """The few WinRT basics needed, through combase.dll."""

    def __init__(self):
        rt = ctypes.WinDLL("combase")
        rt.RoInitialize.argtypes = [c_int32]
        rt.RoInitialize.restype = c_int32
        rt.WindowsCreateString.argtypes = [c_wchar_p, c_uint32, POINTER(c_void_p)]
        rt.WindowsCreateString.restype = c_int32
        rt.WindowsDeleteString.argtypes = [c_void_p]
        rt.WindowsGetStringRawBuffer.argtypes = [c_void_p, POINTER(c_uint32)]
        rt.WindowsGetStringRawBuffer.restype = c_void_p
        rt.RoGetActivationFactory.argtypes = [c_void_p, POINTER(GUID), POINTER(c_void_p)]
        rt.RoGetActivationFactory.restype = c_int32
        self.rt = rt
        rt.RoInitialize(1)                       # multithreaded; already done is fine too

    def factory(self, class_name: str, iid: str) -> c_void_p:
        name = c_void_p()
        self.rt.WindowsCreateString(class_name, len(class_name), byref(name))
        try:
            out = c_void_p()
            hr = self.rt.RoGetActivationFactory(name, byref(guid(iid)), byref(out))
            if hr < 0 or not out:
                raise OSError(hr, f"{class_name} is not available")
            return out
        finally:
            self.rt.WindowsDeleteString(name)

    def text(self, obj: c_void_p, slot: int) -> str:
        """A string property (HSTRING), read and freed."""
        h = c_void_p()
        method(obj, slot, c_int32, POINTER(c_void_p))(byref(h))
        if not h:
            return ""
        try:
            length = c_uint32()
            raw = self.rt.WindowsGetStringRawBuffer(h, byref(length))
            return ctypes.wstring_at(raw, length.value) if raw else ""
        finally:
            self.rt.WindowsDeleteString(h)

    @staticmethod
    def get(obj: c_void_p, slot: int) -> c_void_p:
        out = c_void_p()
        hr = method(obj, slot, c_int32, POINTER(c_void_p))(byref(out))
        if hr < 0:
            raise OSError(hr, f"call {slot} failed")
        return out

    @staticmethod
    def query(obj: c_void_p, iid: str) -> c_void_p:
        out = c_void_p()
        hr = method(obj, 0, c_int32, POINTER(GUID), POINTER(c_void_p))(byref(guid(iid)), byref(out))
        if hr < 0 or not out:
            raise OSError(hr, "interface not offered")
        return out

    @staticmethod
    def release(obj) -> None:
        if obj is not None and obj.value:
            method(obj, 2, ctypes.c_ulong)()
            obj.value = None

    def wait(self, op: c_void_p, results_slot: int = ASYNC_RESULTS, timeout: float = 3.0) -> c_void_p:
        """Waits for an async operation to finish, then returns its result."""
        info = self.query(op, IID_ASYNC_INFO)
        try:
            status = c_int32(0)
            end = time.monotonic() + timeout
            while True:
                method(info, ASYNC_STATUS, c_int32, POINTER(c_int32))(byref(status))
                if status.value != 0:
                    break
                if time.monotonic() > end:
                    raise TimeoutError("Windows did not answer in time")
                time.sleep(0.01)
            if status.value != 1:
                raise OSError(status.value, "the operation did not complete")
        finally:
            self.release(info)
        return self.get(op, results_slot)


class MediaWatcher:
    """Watches what Windows says is playing. Not on Windows, it simply reports nothing."""

    def __init__(self, on_change, reader=None):
        self.on_change = on_change
        self.available = reader is not None or sys.platform == "win32"
        self._reader = reader
        self._commands: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = None
        self.now = None                          # the last NowPlaying reported

    def start(self) -> None:
        if not self.available or (self._thread is not None and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="Now playing", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._commands.put(None)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def command(self, what: str) -> None:
        """"play", "pause", "toggle", "next" or "previous", for the app playing now."""
        if what in SESSION_COMMANDS:
            self._commands.put(what)

    # ---------------------------------------------------------------- the thread
    def _run(self) -> None:
        reader = self._reader or _WindowsReader()
        art_for = None
        art = b""
        while not self._stop.is_set():
            try:
                now = reader.read()
            except Exception:
                now = None
                reader.reset()
            if now is not None:
                if now.track() != art_for:              # a new track: its picture once
                    art_for = now.track()
                    try:
                        art = reader.art() or b""
                    except Exception:
                        art = b""
                now.art = art
            if not (now is None and self.now is None) and not (now is not None and now.same(self.now)):
                self.now = now
                try:
                    self.on_change(now)
                except Exception:
                    pass
            try:
                what = self._commands.get(timeout=LOOK_EVERY_S)
            except queue.Empty:
                continue
            if what is None:
                break
            try:
                reader.command(what)
            except Exception:
                reader.reset()
            time.sleep(0.25)                            # let the app catch up, then look again
        reader.close()


class _WindowsReader:
    def __init__(self):
        self.rt = _WinRT()
        self.manager = None
        self.session = None
        self.props = None

    def reset(self) -> None:
        for name in ("props", "session", "manager"):
            obj = getattr(self, name)
            try:
                self.rt.release(obj)
            except Exception:
                pass
            setattr(self, name, None)

    def close(self) -> None:
        self.reset()

    def _manager(self) -> c_void_p:
        if self.manager is None:
            statics = self.rt.factory(MANAGER_CLASS, IID_MANAGER_STATICS)
            try:
                op = self.rt.get(statics, 6)                # RequestAsync
                try:
                    self.manager = self.rt.wait(op)
                finally:
                    self.rt.release(op)
            finally:
                self.rt.release(statics)
        return self.manager

    def read(self):
        rt = self.rt
        for name in ("props", "session"):
            rt.release(getattr(self, name))
            setattr(self, name, None)
        session = rt.get(self._manager(), MANAGER_GET_CURRENT_SESSION)
        if not session:
            return None
        self.session = session
        now = NowPlaying(app_id=rt.text(session, SESSION_APP_ID))
        op = rt.get(session, SESSION_GET_PROPERTIES)
        try:
            self.props = rt.wait(op)
        finally:
            rt.release(op)
        now.title = rt.text(self.props, PROPS_TITLE)
        now.artist = rt.text(self.props, PROPS_ARTIST)
        now.album = rt.text(self.props, PROPS_ALBUM)
        info = rt.get(session, SESSION_GET_PLAYBACK)
        try:
            status = c_int32()
            method(info, PLAYBACK_STATUS, c_int32, POINTER(c_int32))(byref(status))
            now.status = STATUS.get(status.value, "closed")
            controls = rt.get(info, PLAYBACK_CONTROLS)
            try:
                for what, slot in CONTROLS.items():
                    flag = c_bool()
                    method(controls, slot, c_int32, POINTER(c_bool))(byref(flag))
                    now.can[what] = bool(flag.value)
            finally:
                rt.release(controls)
        finally:
            rt.release(info)
        timeline = rt.get(session, SESSION_GET_TIMELINE)
        try:
            for attr, slot in (("length_s", TIMELINE_END), ("position_s", TIMELINE_POSITION)):
                ticks = c_int64()
                method(timeline, slot, c_int32, POINTER(c_int64))(byref(ticks))
                setattr(now, attr, ticks.value / 1e7)
        finally:
            rt.release(timeline)
        return now

    def art(self) -> bytes:
        """The picture of the track read last (album art, or a video's thumbnail)."""
        rt = self.rt
        if self.props is None:
            return b""
        ref = rt.get(self.props, PROPS_THUMBNAIL)
        if not ref:
            return b""
        stream = streamy = reader_in = buffer = factory = None
        try:
            op = rt.get(ref, 6)                          # OpenReadAsync
            try:
                stream = rt.wait(op)
            finally:
                rt.release(op)
            streamy = rt.query(stream, IID_RANDOM_ACCESS_STREAM)
            size = ctypes.c_uint64()
            method(streamy, 6, c_int32, POINTER(ctypes.c_uint64))(byref(size))
            if not 0 < size.value <= ART_LIMIT:
                return b""
            factory = rt.factory(BUFFER_CLASS, IID_BUFFER_FACTORY)
            buffer = c_void_p()
            method(factory, 6, c_int32, c_uint32, POINTER(c_void_p))(size.value, byref(buffer))
            reader_in = rt.query(stream, IID_INPUT_STREAM)
            op = c_void_p()
            method(reader_in, 6, c_int32, c_void_p, c_uint32, c_int32, POINTER(c_void_p))(
                buffer, size.value, 0, byref(op))
            try:
                filled = rt.wait(op, ASYNC_PROGRESS_RESULTS)
            finally:
                rt.release(op)
            try:
                length = c_uint32()
                method(filled, 7, c_int32, POINTER(c_uint32))(byref(length))   # IBuffer.Length
                access = rt.query(filled, IID_BUFFER_BYTE_ACCESS)
                try:
                    data = c_void_p()
                    method(access, 3, c_int32, POINTER(c_void_p))(byref(data))
                    return ctypes.string_at(data.value, length.value) if data.value else b""
                finally:
                    rt.release(access)
            finally:
                rt.release(filled)
        finally:
            for obj in (buffer, factory, reader_in, streamy, stream, ref):
                try:
                    rt.release(obj)
                except Exception:
                    pass

    def command(self, what: str) -> None:
        if self.session is None:
            self.read()
        if self.session is None:
            return
        op = self.rt.get(self.session, SESSION_COMMANDS[what])
        try:
            self.rt.wait(op)                             # its result (done or not) is not needed
        finally:
            self.rt.release(op)
