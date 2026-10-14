"""Putting the installer on a USB drive: the right drive, every file, checked."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packaging"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import make_usb
from speakerweave import release

DRIVES = [("C:\\", 3, "Windows"), ("D:\\", 3, "Games"), ("E:\\", 2, "ESD-USB"), ("F:\\", 2, "SIM KIT")]


def test_one_usb_stick_is_used_without_asking():
    assert make_usb.pick_drive([], drives=DRIVES[:3], ask=lambda _q: "X") == "E:\\"


def test_several_usb_sticks_ask_which():
    assert make_usb.pick_drive([], drives=DRIVES, ask=lambda _q: "f") == "F:\\"
    assert make_usb.pick_drive([], drives=DRIVES, ask=lambda _q: "") == ""


def test_a_drive_letter_given_is_used():
    assert make_usb.pick_drive(["G:"], drives=DRIVES) == "G:\\"


def test_everything_is_copied_and_checked(tmp_path, monkeypatch):
    shown = release.version_name()
    built = tmp_path / "installer"
    built.mkdir()
    setup = built / f"SpeakerWeave-Setup-{shown.replace(' ', '-')}.exe"
    setup.write_bytes(os.urandom(4096))
    (built / (setup.name + ".sha256")).write_text("abc  x\n")
    (built / f"Release notes {shown}.md").write_text("notes")
    usb = tmp_path / "usb"
    usb.mkdir()
    pack = tmp_path / "VBCABLE_Driver_Pack45.zip"
    pack.write_bytes(b"zip")
    monkeypatch.setattr(make_usb, "RESULT", str(built))
    monkeypatch.setattr(make_usb, "REPORT", str(tmp_path / "usb copy.txt"))
    monkeypatch.setattr(make_usb, "newest_source_time", lambda: 0.0)
    monkeypatch.setattr(make_usb, "pick_drive", lambda *a: str(usb) + os.sep)
    monkeypatch.setattr(make_usb, "vbcable_pack", lambda: str(pack))
    assert make_usb.main([]) == 0
    folder = usb / make_usb.FOLDER
    names = sorted(p.name for p in folder.iterdir())
    assert names == sorted([setup.name, setup.name + ".sha256", f"Release notes {shown}.md",
                            "How to install.txt", "VB-CABLE"])
    assert (folder / setup.name).read_bytes() == setup.read_bytes()
    assert (folder / "VB-CABLE" / pack.name).exists()
    assert "Run as administrator" in (folder / "How to install.txt").read_text()
    assert "Done, and checked" in (tmp_path / "usb copy.txt").read_text()


def test_an_old_installer_is_not_copied(tmp_path, monkeypatch):
    shown = release.version_name()
    built = tmp_path / "installer"
    built.mkdir()
    setup = built / f"SpeakerWeave-Setup-{shown.replace(' ', '-')}.exe"
    setup.write_bytes(b"old")
    os.utime(setup, (1000, 1000))
    monkeypatch.setattr(make_usb, "RESULT", str(built))
    monkeypatch.setattr(make_usb, "REPORT", str(tmp_path / "usb copy.txt"))
    monkeypatch.setattr(make_usb, "pick_drive", lambda *a: (_ for _ in ()).throw(AssertionError("asked")))
    assert make_usb.main([]) == 1
    assert "older than the latest changes" in (tmp_path / "usb copy.txt").read_text()
