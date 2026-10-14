"""Reading and choosing the default sound output of Windows.

Windows has no public function for choosing the default output. Every tool
that does it (the Sound control panel itself, SoundSwitch, NirCmd) uses the
same built in interface, IPolicyConfig, and so does this module.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import POINTER, byref, c_uint32, c_ushort, c_void_p

from .wincom import GUID, HRESULT, Apartment, guid, method, release

CLSID_ENUMERATOR = "BCDE0395-E52F-467C-8E3D-C4579291692E"
IID_ENUMERATOR = "A95664D2-9614-4F35-A746-DE8DB63617E6"
CLSID_POLICY = "870AF99C-171D-4F9E-AF0D-E63DF40C2BC9"
IID_POLICY = "F8679F50-850A-41CF-9C72-430F290290C8"
FRIENDLY_NAME = ("A45C254E-DF1C-4EFD-8020-67D146A850E0", 14)

RENDER = 0
ACTIVE = 0x1
# console (most sound), multimedia (music and films), communications (calls)
ROLES = (0, 1, 2)


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", c_uint32)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort),
                ("value", c_void_p), ("extra", c_void_p)]


def supported() -> bool:
    return sys.platform.startswith("win")


def _device_id(com, device) -> str:
    text = c_void_p()
    method(device, 5, HRESULT, POINTER(c_void_p))(byref(text))
    try:
        return ctypes.wstring_at(text.value) if text.value else ""
    finally:
        com.free(text)


def _device_name(device) -> str:
    store = c_void_p()
    method(device, 4, HRESULT, ctypes.c_uint32, POINTER(c_void_p))(0, byref(store))
    try:
        key = PROPERTYKEY(guid(FRIENDLY_NAME[0]), FRIENDLY_NAME[1])
        value = PROPVARIANT()
        method(store, 5, HRESULT, POINTER(PROPERTYKEY), POINTER(PROPVARIANT))(byref(key), byref(value))
        try:
            if value.vt == 31 and value.value:          # VT_LPWSTR
                return ctypes.wstring_at(value.value)
            return ""
        finally:
            ole32 = ctypes.WinDLL("ole32")
            ole32.PropVariantClear.argtypes = [POINTER(PROPVARIANT)]
            ole32.PropVariantClear(byref(value))
    finally:
        release(store)


def list_outputs() -> list[tuple[str, str]]:
    """(id, name) of every sound output that is connected and switched on."""
    if not supported():
        return []
    out = []
    with Apartment() as com:
        enum = com.create(CLSID_ENUMERATOR, IID_ENUMERATOR)
        try:
            items = c_void_p()
            method(enum, 3, HRESULT, ctypes.c_int, ctypes.c_uint32, POINTER(c_void_p))(
                RENDER, ACTIVE, byref(items))
            try:
                count = c_uint32()
                method(items, 3, HRESULT, POINTER(c_uint32))(byref(count))
                for i in range(count.value):
                    device = c_void_p()
                    method(items, 4, HRESULT, ctypes.c_uint32, POINTER(c_void_p))(i, byref(device))
                    try:
                        out.append((_device_id(com, device), _device_name(device)))
                    finally:
                        release(device)
            finally:
                release(items)
        finally:
            release(enum)
    return out


def default_output(role: int = 0) -> tuple[str, str]:
    """(id, name) of the current default output for a role, or ("", "")."""
    if not supported():
        return "", ""
    with Apartment() as com:
        enum = com.create(CLSID_ENUMERATOR, IID_ENUMERATOR)
        try:
            device = c_void_p()
            try:
                method(enum, 4, HRESULT, ctypes.c_int, ctypes.c_int, POINTER(c_void_p))(
                    RENDER, role, byref(device))
            except OSError:
                return "", ""                            # no output at all
            try:
                return _device_id(com, device), _device_name(device)
            finally:
                release(device)
        finally:
            release(enum)


def defaults() -> dict:
    """{role: device id} of the current defaults."""
    return {str(role): default_output(role)[0] for role in ROLES}


def set_default(device_id: str, roles=ROLES) -> None:
    """Makes device_id the default output for the given roles."""
    if not supported():
        raise RuntimeError("Only Windows has a default sound output to choose.")
    with Apartment() as com:
        policy = com.create(CLSID_POLICY, IID_POLICY)
        try:
            set_endpoint = method(policy, 13, HRESULT, ctypes.c_wchar_p, ctypes.c_int)
            for role in roles:
                set_endpoint(device_id, int(role))
        finally:
            release(policy)


def find(name: str, outputs=None) -> str:
    """The id of the output whose Windows name matches name ("" if none).
    Names from the sound libraries can be cut short, so a name that starts
    the same way counts as well."""
    want = (name or "").strip().lower()
    if not want:
        return ""
    outputs = list_outputs() if outputs is None else outputs
    for dev_id, dev_name in outputs:
        if dev_name.strip().lower() == want:
            return dev_id
    for dev_id, dev_name in outputs:
        have = dev_name.strip().lower()
        if have and (have.startswith(want) or want.startswith(have)):
            return dev_id
    return ""


# ------------------------------------------------------------------ channel layout (stereo, 5.1, 7.1)

class WAVEFORMATEXTENSIBLE(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("wFormatTag", ctypes.c_uint16), ("nChannels", ctypes.c_uint16),
                ("nSamplesPerSec", c_uint32), ("nAvgBytesPerSec", c_uint32),
                ("nBlockAlign", ctypes.c_uint16), ("wBitsPerSample", ctypes.c_uint16),
                ("cbSize", ctypes.c_uint16), ("wValidBitsPerSample", ctypes.c_uint16),
                ("dwChannelMask", c_uint32), ("SubFormat", GUID)]


EXTENSIBLE = 0xFFFE
SUBTYPE_PCM = "00000001-0000-0010-8000-00AA00389B71"
SUBTYPE_FLOAT = "00000003-0000-0010-8000-00AA00389B71"
# which speakers a layout has, as Windows writes it (KSAUDIO_SPEAKER_...)
CHANNEL_MASKS = {2: 0x3, 4: 0x33, 6: 0x60F, 8: 0x63F}
PHYSICAL_SPEAKERS = ("1DA5D803-D492-4EDD-8C23-E0C0FFEE7F0E", 3)


def _read_format(pointer_value) -> dict:
    """The fields of a WAVEFORMATEX(TENSIBLE) Windows handed us."""
    base = ctypes.cast(pointer_value, POINTER(WAVEFORMATEXTENSIBLE)).contents
    fmt = {"tag": base.wFormatTag, "channels": base.nChannels, "rate": base.nSamplesPerSec,
           "bits": base.wBitsPerSample, "valid": base.wBitsPerSample, "float": base.wFormatTag == 3}
    if base.wFormatTag == EXTENSIBLE and base.cbSize >= 22:
        fmt["valid"] = base.wValidBitsPerSample or base.wBitsPerSample
        sub = bytes(base.SubFormat)
        fmt["float"] = sub == bytes(guid(SUBTYPE_FLOAT))
    return fmt


def _make_format(fmt: dict, channels: int) -> WAVEFORMATEXTENSIBLE:
    w = WAVEFORMATEXTENSIBLE()
    w.wFormatTag = EXTENSIBLE
    w.nChannels = channels
    w.nSamplesPerSec = fmt["rate"]
    w.wBitsPerSample = fmt["bits"]
    w.nBlockAlign = channels * fmt["bits"] // 8
    w.nAvgBytesPerSec = w.nSamplesPerSec * w.nBlockAlign
    w.cbSize = 22
    w.wValidBitsPerSample = fmt["valid"]
    w.dwChannelMask = CHANNEL_MASKS.get(channels, (1 << channels) - 1)
    w.SubFormat = guid(SUBTYPE_FLOAT if fmt["float"] else SUBTYPE_PCM)
    return w


def channel_count(device_id: str) -> int:
    """How many channels Windows mixes for this output (2 for stereo, 8 for 7.1)."""
    if not supported():
        return 0
    with Apartment() as com:
        policy = com.create(CLSID_POLICY, IID_POLICY)
        try:
            mix = c_void_p()
            method(policy, 3, HRESULT, ctypes.c_wchar_p, POINTER(c_void_p))(device_id, byref(mix))
            try:
                return _read_format(mix.value)["channels"]
            finally:
                com.free(mix)
        finally:
            release(policy)


def set_channels(device_id: str, channels: int = 8) -> None:
    """Sets an output to stereo (2), 5.1 (6) or 7.1 (8), like Configure in the
    Sound control panel does. Used for the virtual device SpeakerWeave listens
    to, so games send it real surround sound."""
    if not supported():
        raise RuntimeError("Only Windows has sound outputs to set up.")
    with Apartment() as com:
        policy = com.create(CLSID_POLICY, IID_POLICY)
        try:
            device_fmt, mix_fmt = c_void_p(), c_void_p()
            method(policy, 4, HRESULT, ctypes.c_wchar_p, ctypes.c_int, POINTER(c_void_p))(
                device_id, 0, byref(device_fmt))
            method(policy, 3, HRESULT, ctypes.c_wchar_p, POINTER(c_void_p))(device_id, byref(mix_fmt))
            try:
                endpoint = _make_format(_read_format(device_fmt.value), channels)
                mix = _make_format(_read_format(mix_fmt.value), channels)
            finally:
                com.free(device_fmt)
                com.free(mix_fmt)
            # the speaker layout shown in the Sound control panel (not every device keeps it)
            try:
                value = PROPVARIANT()
                value.vt = 19                                 # VT_UI4
                value.value = CHANNEL_MASKS.get(channels, (1 << channels) - 1)
                key = PROPERTYKEY(guid(PHYSICAL_SPEAKERS[0]), PHYSICAL_SPEAKERS[1])
                method(policy, 12, HRESULT, ctypes.c_wchar_p, POINTER(PROPERTYKEY),
                       POINTER(PROPVARIANT))(device_id, byref(key), byref(value))
            except OSError:
                pass
            method(policy, 6, HRESULT, ctypes.c_wchar_p, POINTER(WAVEFORMATEXTENSIBLE),
                   POINTER(WAVEFORMATEXTENSIBLE))(device_id, byref(endpoint), byref(mix))
        finally:
            release(policy)


def _main(argv) -> int:
    """python -m speakerweave.windefault [surround NAME]  prints the outputs,
    or sets the named one to 7.1 and shows the channel count before and after."""
    for dev_id, name in list_outputs():
        try:
            count = channel_count(dev_id)
        except OSError as exc:
            count = f"? ({exc})"
        print(f"{name}: {count} channels")
    if len(argv) >= 2 and argv[0] == "surround":
        dev_id = find(argv[1])
        print(f"Setting {argv[1]} ({dev_id}) to 7.1 ...")
        set_channels(dev_id, 8)
        print(f"Now: {channel_count(dev_id)} channels")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
