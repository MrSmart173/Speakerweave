"""A very small helper for calling Windows COM interfaces with ctypes only.

SpeakerWeave needs two Windows services that have no Python library in the
standard set: choosing the default sound output, and reading audio files with
Media Foundation. Both are COM interfaces. Instead of bundling a COM library,
their methods are called straight through the interface's table of functions.
"""
from __future__ import annotations

import ctypes
import uuid
from ctypes import POINTER, byref, c_ulong, c_void_p

HRESULT = ctypes.HRESULT if hasattr(ctypes, "HRESULT") else ctypes.c_long
CLSCTX_ALL = 0x17


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]


def guid(text: str) -> GUID:
    return GUID.from_buffer_copy(uuid.UUID(text).bytes_le)


def method(obj: c_void_p, index: int, restype, *argtypes):
    """Function number index of the interface obj, ready to call with the
    remaining arguments (obj itself is passed for you)."""
    table = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
    proto = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)
    fn = proto(table[index])
    return lambda *args: fn(obj, *args)


def release(obj: c_void_p) -> None:
    if obj and obj.value:
        method(obj, 2, c_ulong)()
        obj.value = None


class Apartment:
    """Makes sure COM is ready on this thread, and tidies up afterwards if
    this object was the one that set it up."""

    def __enter__(self):
        self._ole32 = ctypes.WinDLL("ole32")
        self._ole32.CoInitializeEx.restype = ctypes.c_long
        result = self._ole32.CoInitializeEx(None, 0x2)      # apartment threaded
        # S_OK or S_FALSE: ours to undo. RPC_E_CHANGED_MODE: Qt set it up already, fine.
        self._undo = result in (0, 1)
        return self

    def __exit__(self, *exc):
        if self._undo:
            self._ole32.CoUninitialize()
        return False

    def create(self, clsid: str, iid: str) -> c_void_p:
        obj = c_void_p()
        create = self._ole32.CoCreateInstance
        create.restype = HRESULT
        create.argtypes = [POINTER(GUID), c_void_p, ctypes.c_uint32, POINTER(GUID), POINTER(c_void_p)]
        create(byref(guid(clsid)), None, CLSCTX_ALL, byref(guid(iid)), byref(obj))
        return obj

    def free(self, pointer) -> None:
        self._ole32.CoTaskMemFree.argtypes = [c_void_p]
        self._ole32.CoTaskMemFree(pointer)
