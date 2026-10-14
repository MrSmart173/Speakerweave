"""A pretend OpenRGB SDK server, written from the published protocol description,
so the lights connection can be tested without OpenRGB or any RGB hardware."""
import socket
import struct
import threading

HEADER = struct.Struct("<4sIII")


def text(s: str) -> bytes:
    raw = s.encode() + b"\0"
    return struct.pack("<H", len(raw)) + raw


def mode(name: str, protocol: int) -> bytes:
    out = text(name) + struct.pack("<iIII", 0, 0, 0, 0)
    if protocol >= 3:
        out += struct.pack("<II", 0, 100)
    out += struct.pack("<III", 1, 1, 0)
    if protocol >= 3:
        out += struct.pack("<I", 100)
    out += struct.pack("<II", 0, 1) + struct.pack("<H", 1) + bytes((1, 2, 3, 0))
    return out


def zone(name: str, leds: int, matrix=None) -> bytes:
    out = text(name) + struct.pack("<iIII", 1, leds, leds, leds)
    if matrix:
        h, w = matrix
        cells = struct.pack("<" + "I" * (h * w), *range(h * w))
        out += struct.pack("<HII", 8 + len(cells), h, w) + cells
    else:
        out += struct.pack("<H", 0)
    return out


def device(name: str, zones, protocol: int) -> bytes:
    total = sum(z[1] for z in zones)
    body = struct.pack("<i", 2) + text(name)
    if protocol >= 1:
        body += text("Test vendor")
    body += text("A test device") + text("1.0") + text("SN1") + text("USB")
    body += struct.pack("<H", 2) + struct.pack("<i", 0) + mode("Direct", protocol) + mode("Rainbow", protocol)
    body += struct.pack("<H", len(zones)) + b"".join(zone(*z) for z in zones)
    body += struct.pack("<H", total) + b"".join(text(f"LED {i}") + struct.pack("<I", i) for i in range(total))
    body += struct.pack("<H", total) + b"\0\0\0\0" * total
    return struct.pack("<I", 4 + len(body)) + body


class FakeOpenRGB:
    def __init__(self, devices, protocol=3, answer_version=True, nag=False):
        self.devices = devices                  # list of (name, [(zone name, leds, matrix)])
        self.protocol = protocol
        self.answer_version = answer_version
        self.nag = nag                          # send "device list changed" before answers
        self.received = []                      # (packet id, device index, payload)
        self.asked_protocol = None
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(4)
        self.port = self.server.getsockname()[1]
        self.event = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _send(self, conn, packet_id, dev, payload=b""):
        conn.sendall(HEADER.pack(b"ORGB", dev, packet_id, len(payload)) + payload)

    def _client(self, conn):
        used = 0
        try:
            while True:
                head = self._read(conn, 16)
                magic, dev, pid, size = HEADER.unpack(head)
                payload = self._read(conn, size) if size else b""
                self.received.append((pid, dev, payload))
                self.event.set()
                if self.nag and pid in (0, 1):
                    self._send(conn, 100, 0)
                if pid == 40 and self.answer_version:
                    self._send(conn, 40, 0, struct.pack("<I", self.protocol))
                elif pid == 0:
                    self._send(conn, 0, 0, struct.pack("<I", len(self.devices)))
                elif pid == 1:
                    used = struct.unpack("<I", payload)[0] if payload else 0
                    self.asked_protocol = used
                    name, zones = self.devices[dev]
                    self._send(conn, 1, dev, device(name, zones, used))
        except (OSError, ConnectionError):
            pass

    @staticmethod
    def _read(conn, n):
        data = b""
        while len(data) < n:
            chunk = conn.recv(n - len(data))
            if not chunk:
                raise ConnectionError
            data += chunk
        return data

    def packets(self, pid):
        return [(d, p) for i, d, p in self.received if i == pid]

    def close(self):
        self.server.close()
