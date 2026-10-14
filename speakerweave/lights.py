"""Our own connection to OpenRGB.

OpenRGB is a separate free program that knows how to talk to RGB hardware. While
its "SDK Server" is switched on, other programs can send it colours over a local
network connection. This module speaks that protocol directly, written from the
published OpenRGB SDK protocol description, so SpeakerWeave needs no extra
library for it.

Every packet starts with a 16 byte header (all numbers little endian):
    "ORGB", device index (uint32), packet id (uint32), payload size (uint32)
"""
from __future__ import annotations

import socket
import struct
import threading
from dataclasses import dataclass, field

MAGIC = b"ORGB"
HEADER = struct.Struct("<4sIII")

REQUEST_CONTROLLER_COUNT = 0
REQUEST_CONTROLLER_DATA = 1
REQUEST_PROTOCOL_VERSION = 40
SET_CLIENT_NAME = 50
DEVICE_LIST_UPDATED = 100
UPDATE_LEDS = 1050
UPDATE_ZONE_LEDS = 1051
SET_CUSTOM_MODE = 1100

# Protocol versions we can read. The server is asked for its newest version and
# then sends device descriptions in whichever is lower, its or ours.
MAX_PROTOCOL = 3
MAX_PAYLOAD = 16 * 1024 * 1024


class LightsError(Exception):
    pass


@dataclass
class RGBZone:
    index: int
    name: str
    led_count: int


@dataclass
class RGBDevice:
    index: int
    name: str
    kind: int = 0
    vendor: str = ""
    description: str = ""
    led_count: int = 0
    zones: list = field(default_factory=list)
    modes: list = field(default_factory=list)


# ------------------------------------------------------------------ decoding

class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def take(self, n: int) -> bytes:
        if n < 0 or self.pos + n > len(self.data):
            raise LightsError("OpenRGB sent a device description that ends too early")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def u16(self) -> int:
        return struct.unpack("<H", self.take(2))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def i32(self) -> int:
        return struct.unpack("<i", self.take(4))[0]

    def text(self) -> str:
        raw = self.take(self.u16())
        return raw.split(b"\0", 1)[0].decode("utf-8", errors="replace")


def parse_device(index: int, data: bytes, protocol: int) -> RGBDevice:
    """Reads one device description (the answer to REQUEST_CONTROLLER_DATA)."""
    r = _Reader(data)
    r.u32()                                     # total size
    dev = RGBDevice(index=index, name="")
    dev.kind = r.i32()
    dev.name = r.text()
    if protocol >= 1:
        dev.vendor = r.text()
    dev.description = r.text()
    r.text()                                    # version
    r.text()                                    # serial
    r.text()                                    # location
    mode_count = r.u16()
    r.i32()                                     # active mode
    for _ in range(mode_count):
        name = r.text()
        r.i32()                                 # value
        r.u32()                                 # flags
        r.u32()                                 # speed min
        r.u32()                                 # speed max
        if protocol >= 3:
            r.u32()                             # brightness min
            r.u32()                             # brightness max
        r.u32()                                 # colours min
        r.u32()                                 # colours max
        r.u32()                                 # speed
        if protocol >= 3:
            r.u32()                             # brightness
        r.u32()                                 # direction
        r.u32()                                 # colour mode
        r.take(4 * r.u16())                     # mode colours
        dev.modes.append(name)
    for zone_index in range(r.u16()):
        name = r.text()
        r.i32()                                 # zone type
        r.u32()                                 # leds min
        r.u32()                                 # leds max
        count = r.u32()
        matrix = r.u16()
        if matrix:
            r.take(matrix)                      # height, width and the map itself
        dev.zones.append(RGBZone(zone_index, name, count))
    led_count = r.u16()
    for _ in range(led_count):
        r.text()                                # led name
        r.u32()                                 # led value
    dev.led_count = led_count
    return dev


def encode_colors(colors) -> bytes:
    """(r, g, b) tuples to OpenRGB's 4 bytes per colour: red, green, blue, unused."""
    out = bytearray()
    for r, g, b in colors:
        out += bytes((int(r) & 255, int(g) & 255, int(b) & 255, 0))
    return bytes(out)


# ------------------------------------------------------------------ connection

class OpenRGBConnection:
    """One connection to a running OpenRGB SDK server."""

    def __init__(self, host: str = "127.0.0.1", port: int = 6742, client_name: str = "SpeakerWeave",
                 timeout: float = 3.0):
        self.host, self.port, self.client_name, self.timeout = host, int(port), client_name, timeout
        self.sock = None
        self.protocol = 0
        self.devices: list[RGBDevice] = []
        self.changed = False                # OpenRGB said its device list changed
        self._lock = threading.Lock()

    # ---------------------------------------------------------- low level
    def _send(self, packet_id: int, device: int = 0, payload: bytes = b"") -> None:
        if self.sock is None:
            raise LightsError("not connected to OpenRGB")
        try:
            self.sock.sendall(HEADER.pack(MAGIC, device, packet_id, len(payload)) + payload)
        except OSError as exc:
            self.close()
            raise LightsError(f"the connection to OpenRGB was lost ({exc})") from exc

    def _receive_exact(self, n: int) -> bytes:
        chunks, got = [], 0
        while got < n:
            chunk = self.sock.recv(n - got)
            if not chunk:
                raise LightsError("OpenRGB closed the connection")
            chunks.append(chunk)
            got += len(chunk)
        return b"".join(chunks)

    def _receive(self) -> tuple[int, int, bytes]:
        magic, device, packet_id, size = HEADER.unpack(self._receive_exact(HEADER.size))
        if magic != MAGIC:
            raise LightsError("the other side does not speak the OpenRGB protocol")
        if size > MAX_PAYLOAD:
            raise LightsError("OpenRGB sent an impossibly large packet")
        return device, packet_id, self._receive_exact(size)

    def _ask(self, packet_id: int, device: int = 0, payload: bytes = b"") -> bytes:
        """Sends a request and returns the matching answer. Notices that arrive
        in between (such as "the device list changed") are noted and skipped."""
        self._send(packet_id, device, payload)
        while True:
            try:
                _dev, got_id, data = self._receive()
            except socket.timeout as exc:
                raise LightsError("OpenRGB did not answer in time") from exc
            except OSError as exc:
                self.close()
                raise LightsError(f"the connection to OpenRGB was lost ({exc})") from exc
            if got_id == packet_id:
                return data
            if got_id == DEVICE_LIST_UPDATED:
                self.changed = True

    # ---------------------------------------------------------- public
    def connect(self) -> None:
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            self.sock = None
            raise LightsError(f"could not reach OpenRGB at {self.host}:{self.port} ({exc})") from exc
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        with self._lock:
            self.protocol = self._negotiate()
            self._send(SET_CLIENT_NAME, 0, self.client_name.encode("utf-8") + b"\0")
            self._load_devices()

    def _negotiate(self) -> int:
        """Very old OpenRGB versions do not answer this question at all."""
        self.sock.settimeout(min(self.timeout, 1.0))
        try:
            data = self._ask(REQUEST_PROTOCOL_VERSION, 0, struct.pack("<I", MAX_PROTOCOL))
            server = struct.unpack("<I", data[:4])[0] if len(data) >= 4 else 0
        except LightsError:
            if self.sock is None:
                raise
            server = 0
        finally:
            if self.sock is not None:
                self.sock.settimeout(self.timeout)
        return min(server, MAX_PROTOCOL)

    def _load_devices(self) -> None:
        count = struct.unpack("<I", self._ask(REQUEST_CONTROLLER_COUNT)[:4])[0]
        payload = struct.pack("<I", self.protocol) if self.protocol >= 1 else b""
        devices = []
        for index in range(count):
            data = self._ask(REQUEST_CONTROLLER_DATA, index, payload)
            devices.append(parse_device(index, data, self.protocol))
        self.devices = devices
        self.changed = False
        for dev in devices:                     # hand the LEDs over to us ("direct" mode)
            self._send(SET_CUSTOM_MODE, dev.index)

    def refresh(self) -> None:
        with self._lock:
            self._load_devices()

    def set_leds(self, device: int, colors) -> None:
        """Colours for every LED of a device, in order."""
        colors = list(colors)
        body = struct.pack("<H", len(colors)) + encode_colors(colors)
        with self._lock:
            self._send(UPDATE_LEDS, device, struct.pack("<I", 4 + len(body)) + body)

    def set_zone_leds(self, device: int, zone: int, colors) -> None:
        """Colours for every LED of one zone of a device."""
        colors = list(colors)
        body = struct.pack("<IH", zone, len(colors)) + encode_colors(colors)
        with self._lock:
            self._send(UPDATE_ZONE_LEDS, device, struct.pack("<I", 4 + len(body)) + body)

    def close(self) -> None:
        sock, self.sock = self.sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
