"""Our own OpenRGB connection, tested against a pretend OpenRGB server."""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fake_openrgb import FakeOpenRGB
from speakerweave.lights import LightsError, OpenRGBConnection, encode_colors
from speakerweave.model import Project
from speakerweave.rgb import RgbController

DEVICES = [("LED strip", [("Strip", 10, None)]),
           ("Motherboard", [("Header 1", 20, None), ("Keys", 6, (2, 3)), ("Header 2", 4, None)])]


def wait_for(condition, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_reads_the_devices_and_takes_over_their_leds():
    for server_protocol, used in ((3, 3), (5, 3), (2, 2), (1, 1)):
        server = FakeOpenRGB(DEVICES, protocol=server_protocol)
        conn = OpenRGBConnection("127.0.0.1", server.port, "SpeakerWeave")
        conn.connect()
        assert conn.protocol == used and server.asked_protocol == used
        strip, board = conn.devices
        assert (strip.name, strip.led_count, [z.name for z in strip.zones]) == ("LED strip", 10, ["Strip"])
        assert board.led_count == 30 and [(z.name, z.led_count) for z in board.zones] == [
            ("Header 1", 20), ("Keys", 6), ("Header 2", 4)]
        assert board.modes == ["Direct", "Rainbow"]
        assert board.vendor == ("Test vendor" if used >= 1 else "")
        assert wait_for(lambda: len(server.packets(1100)) == 2)       # custom mode on both
        assert server.packets(50)[0][1] == b"SpeakerWeave\0"          # our name
        conn.close()
        server.close()


def test_very_old_openrgb_that_does_not_answer_the_version_question():
    server = FakeOpenRGB(DEVICES, protocol=0, answer_version=False)
    conn = OpenRGBConnection("127.0.0.1", server.port, timeout=2.0)
    started = time.time()
    conn.connect()
    assert conn.protocol == 0 and server.asked_protocol == 0
    assert time.time() - started < 2.5
    assert [d.name for d in conn.devices] == ["LED strip", "Motherboard"]
    conn.close()
    server.close()


def test_colours_go_out_in_the_documented_layout():
    server = FakeOpenRGB(DEVICES)
    conn = OpenRGBConnection("127.0.0.1", server.port)
    conn.connect()
    conn.set_leds(0, [(255, 0, 0), (0, 255, 0), (1, 2, 3)])
    conn.set_zone_leds(1, 2, [(9, 8, 7)] * 4)
    assert wait_for(lambda: server.packets(1050) and server.packets(1051))
    dev, payload = server.packets(1050)[0]
    assert dev == 0
    assert payload == struct.pack("<IH", 18, 3) + bytes((255, 0, 0, 0, 0, 255, 0, 0, 1, 2, 3, 0))
    dev, payload = server.packets(1051)[0]
    assert dev == 1 and payload[:10] == struct.pack("<IIH", 26, 2, 4) and payload[10:14] == bytes((9, 8, 7, 0))
    assert encode_colors([(300, -1, 128)]) == bytes((44, 255, 128, 0))
    conn.close()
    server.close()


def test_notices_in_between_answers_are_handled():
    server = FakeOpenRGB(DEVICES, nag=True)
    conn = OpenRGBConnection("127.0.0.1", server.port)
    conn.connect()
    assert [d.name for d in conn.devices] == ["LED strip", "Motherboard"]
    conn.refresh()
    assert len(conn.devices) == 2
    conn.close()
    server.close()


def test_nothing_listening_gives_a_clear_message():
    import socket
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()                                   # a port nobody listens on
    conn = OpenRGBConnection("127.0.0.1", port, timeout=1.0)
    try:
        conn.connect()
    except LightsError as exc:
        assert "could not reach OpenRGB" in str(exc)
    else:
        raise AssertionError("expected a LightsError")


def test_speaker_lights_follow_the_sound_through_openrgb():
    server = FakeOpenRGB(DEVICES)
    proj = Project(mode="2.0", rgb_port=server.port)
    dev = proj.add_device("Amp", 2)
    left, right = dev.speakers
    left.rgb_device, left.rgb_mode = "LED strip", "vu"
    right.rgb_device, right.rgb_zone = "Motherboard", "Keys"
    right.rgb_mode, right.rgb_color = "static", "#00ff00"
    rgb = RgbController(proj, lambda spk_id: 1.0 if spk_id == left.id else 0.0)
    assert rgb.connect(), rgb.error
    assert ("Motherboard", "Keys", 6) in rgb.targets()
    assert wait_for(lambda: server.packets(1050) and server.packets(1051))
    rgb.disconnect()
    dev_index, payload = server.packets(1050)[-1]
    assert dev_index == 0 and struct.unpack("<H", payload[4:6])[0] == 10
    assert payload[6:9] == bytes.fromhex("4da3ff")            # front left blue, full level
    dev_index, payload = server.packets(1051)[-1]
    assert dev_index == 1 and struct.unpack("<IH", payload[4:10]) == (1, 6)
    assert payload[10:14] == bytes((0, 255, 0, 0))
    server.close()
    proj.rgb_port = 1
    rgb2 = RgbController(proj, lambda _id: 0.0)
    assert not rgb2.connect() and "SDK Server" in rgb2.error


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok   ", name)
