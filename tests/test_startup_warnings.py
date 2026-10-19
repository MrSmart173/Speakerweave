"""Warnings that came up at startup without a real reason, or with one that is now fixed:
outputs interrupted thousands of times when the virtual device runs at 192 kHz, the SimHub
plugin called older after every build, and setups still at the old -6 dB start."""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from speakerweave import engine as engine_module, simhub
from speakerweave.engine import AdaptiveFifo
from speakerweave.model import Project


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def play(monkeypatch, sr, block, packet_ms, device_frames, device_ms, seconds=20.0):
    """Windows hands over the PC sound in packets; the output takes its own share on its own
    clock. Returns the buffer after `seconds` of simulated playing."""
    clock = Clock()
    monkeypatch.setattr(engine_module.time, "perf_counter", clock)
    fifo = AdaptiveFifo(2, sr, 0.0, block=block)
    packet = int(sr * packet_ms / 1000.0)
    quiet = np.full((block, 2), 0.1, dtype=np.float32)
    events = []
    t = 0.0
    while t < seconds:
        events.append((t, "packet"))
        t += packet_ms / 1000.0
    t = 0.0031                                       # the output's clock is not in step
    while t < seconds:
        events.append((t, "read"))
        t += device_ms / 1000.0
    events.sort()
    late = []
    for when, kind in events:
        clock.now = 1000.0 + when
        if kind == "packet":
            for _ in range(packet // block):
                fifo.write(quiet)                    # all of a packet's blocks at once
        else:
            before = fifo.underruns
            fifo.read(device_frames)
            if fifo.underruns > before:
                late.append(when)
        if kind == "packet":
            fifo.set_target(max(fifo.target, fifo.need))   # what the runner does after each block
    return fifo, late


def test_192_khz_packets_no_longer_run_the_outputs_dry(monkeypatch):
    # 10 ms packets at 192 kHz carry four of our 480 sample blocks: the buffer must bridge
    # the 10 ms between them. Before, it kept room for 2.5 ms and ran dry every packet.
    fifo, late = play(monkeypatch, 192000.0, 480, 10.0, 1920, 10.0)
    assert fifo.need >= 1920                         # it learned that a packet holds 1920
    assert len([t for t in late if t > 2.0]) == 0    # and after settling, never runs dry
    assert fifo.underruns <= 3


def test_48_khz_keeps_its_low_delay(monkeypatch):
    fifo, late = play(monkeypatch, 48000.0, 480, 10.0, 480, 10.0)
    assert fifo.need * 1000.0 / 48000.0 < 25.0      # about 18 ms, as before
    assert len([t for t in late if t > 2.0]) == 0


def fake_dotnet_dll(stamp: int, mvid: bytes, code: bytes) -> bytes:
    """A tiny file laid out like a .NET DLL from the C# compiler of Windows: a PE header with
    the build time, one section holding the CLI header and metadata with a #GUID heap."""
    data = bytearray(0x400)
    data[0:2] = b"MZ"
    pe = 0x80
    struct.pack_into("<I", data, 0x3C, pe)
    data[pe:pe + 4] = b"PE\0\0"
    struct.pack_into("<HHI", data, pe + 4, 0x14C, 1, stamp)      # machine, sections, time
    opt_size = 224
    struct.pack_into("<H", data, pe + 20, opt_size)
    opt = pe + 24
    struct.pack_into("<H", data, opt, 0x10B)                      # PE32
    struct.pack_into("<I", data, opt + 64, stamp ^ 0x5A5A)        # a checksum
    dirs = opt + 96
    struct.pack_into("<II", data, dirs + 14 * 8, 0x2000, 72)     # the CLI header
    sec = opt + opt_size
    struct.pack_into("<8sIIII", data, sec, b".text", 0x200, 0x2000, 0x200, 0x200)
    raw = 0x200
    struct.pack_into("<II", data, raw + 8, 0x2000 + 0x48, 0x100)  # metadata RVA and size
    meta = raw + 0x48
    version = b"v4.0.30319\0\0"
    struct.pack_into("<IHHII", data, meta, 0x424A5342, 1, 1, 0, len(version))
    data[meta + 16:meta + 16 + len(version)] = version
    at = meta + 16 + len(version)
    struct.pack_into("<HH", data, at, 0, 2)
    at += 4
    struct.pack_into("<II", data, at, 0x80, 16)                   # #~ : the code
    data[at + 8:at + 12] = b"#~\0\0"
    at += 12
    struct.pack_into("<II", data, at, 0x90, 16)                   # #GUID : the module id
    data[at + 8:at + 16] = b"#GUID\0\0\0"
    data[meta + 0x80:meta + 0x90] = code.ljust(16, b"\0")
    data[meta + 0x90:meta + 0xA0] = mvid
    return bytes(data)


def test_the_same_plugin_built_again_is_not_called_older(tmp_path):
    a = tmp_path / "a.dll"
    b = tmp_path / "b.dll"
    c = tmp_path / "c.dll"
    a.write_bytes(fake_dotnet_dll(0x6500_0000, b"\x11" * 16, b"same code"))
    b.write_bytes(fake_dotnet_dll(0x6512_3456, b"\x99" * 16, b"same code"))   # built later
    c.write_bytes(fake_dotnet_dll(0x6500_0000, b"\x11" * 16, b"new code!"))
    assert a.read_bytes() != b.read_bytes()
    assert simhub._digest(str(a)) == simhub._digest(str(b))
    assert simhub._digest(str(a)) != simhub._digest(str(c))   # a real change still counts
    other = tmp_path / "plain.bin"
    other.write_bytes(b"not a dll at all")
    assert simhub._digest(str(other))                         # anything else: compared whole

    folder = tmp_path / "SimHub"
    folder.mkdir()
    (folder / simhub.SIMHUB_EXE).write_bytes(b"")
    (folder / simhub.PLUGIN_FILE).write_bytes(a.read_bytes())
    assert simhub.plugin_state(str(folder), str(b)) == "current"
    assert simhub.plugin_state(str(folder), str(c)) == "old"


def test_setups_at_the_old_starting_volume_move_to_full_volume(tmp_path):
    assert Project().master_db == 0.0
    old = json.loads(Project().to_json())
    old["setup_version"], old["master_db"] = 2, -6.0
    assert Project.from_json(json.dumps(old)).master_db == 0.0
    old["master_db"] = -12.0                                   # chosen on purpose: kept
    assert Project.from_json(json.dumps(old)).master_db == -12.0
    moved = Project.from_json(json.dumps(dict(old, master_db=-6.0)))
    again = Project.from_json(moved.to_json())
    assert again.setup_version == 3
    again.master_db = -6.0                                     # set by hand after the update
    assert Project.from_json(again.to_json()).master_db == -6.0
