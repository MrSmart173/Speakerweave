"""Puts everything needed to install SpeakerWeave on another PC into a folder on a USB drive.

    python packaging\\make_usb.py [drive letter]

Copies the installer from dist\\installer with its checksum and release notes, writes a
short "How to install.txt", and adds the VB-CABLE driver pack when one has been
downloaded to this PC (SpeakerWeave needs VB-CABLE, and the other PC may be offline).
Without a drive letter it finds the USB drive itself, and asks when there are several.
A report of what it did is written to "usb copy.txt" next to this project.
"""
from __future__ import annotations

import glob
import hashlib
import os
import shutil
import string
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULT = os.path.join(ROOT, "dist", "installer")
FOLDER = "SpeakerWeave installer"
REPORT = os.path.join(ROOT, "usb copy.txt")
REMOVABLE = 2                     # GetDriveType: a USB stick or memory card
FIXED = 3                         # also USB hard drives and SSDs, which say they are fixed

sys.path.insert(0, ROOT)


def _windows_drives() -> list:
    """[(root, type, label)] of every drive with a letter."""
    import ctypes
    kernel = ctypes.windll.kernel32
    mask = kernel.GetLogicalDrives()
    out = []
    for i, letter in enumerate(string.ascii_uppercase):
        if not mask & (1 << i):
            continue
        root = f"{letter}:\\"
        kind = kernel.GetDriveTypeW(root)
        label = ctypes.create_unicode_buffer(261)
        kernel.GetVolumeInformationW(root, label, 261, None, None, None, None, 0)
        out.append((root, kind, label.value))
    return out


def usb_drives(drives=None) -> list:
    """[(root, label)] of the removable drives (never C:)."""
    drives = _windows_drives() if drives is None else drives
    return [(root, label) for root, kind, label in drives
            if kind == REMOVABLE and not root.upper().startswith("C:")]


def pick_drive(argv: list, drives=None, ask=input) -> str:
    """The root of the drive to copy to, "" to stop."""
    if argv:
        letter = argv[0].strip().rstrip(":\\/").upper()[:1]
        return f"{letter}:\\" if letter else ""
    found = usb_drives(drives)
    if len(found) == 1:
        return found[0][0]
    if found:
        print("More than one USB drive is plugged in:")
        for root, label in found:
            print(f"   {root[:2]}  {label or '(no name)'}")
    else:
        print("No USB stick was found. A USB hard drive can still be used.")
    answer = ask("Type the drive letter to copy to (for example F) and press Enter: ")
    letter = answer.strip().rstrip(":\\/").upper()[:1]
    return f"{letter}:\\" if letter in string.ascii_uppercase and letter else ""


def newest(pattern: str) -> str:
    files = [f for f in glob.glob(pattern) if os.path.isfile(f)]
    return max(files, key=os.path.getmtime) if files else ""


def newest_source_time() -> float:
    times = [os.path.getmtime(f) for f in glob.glob(os.path.join(ROOT, "speakerweave", "**", "*.py"),
                                                    recursive=True)]
    return max(times) if times else 0.0


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def vbcable_pack() -> str:
    """A VB-CABLE driver pack downloaded to this PC, "" if none."""
    places = [os.path.join(os.path.expanduser("~"), "Downloads"), os.path.join(ROOT, "third_party")]
    found = [newest(os.path.join(place, "VBCABLE_Driver_Pack*.zip")) for place in places]
    found = [f for f in found if f]
    return max(found, key=os.path.getmtime) if found else ""


def how_to_install(setup: str, shown: str, cable: str) -> str:
    cable_step = (
        f"2. SpeakerWeave needs VB-CABLE, a free virtual sound device by VB-Audio.\n"
        f"   It is in the VB-CABLE folder here: open {os.path.basename(cable)}, extract it,\n"
        f"   right click VBCABLE_Setup_x64.exe, choose Run as administrator and press\n"
        f"   Install Driver. Then restart the PC.\n"
        if cable else
        "2. SpeakerWeave needs VB-CABLE, a free virtual sound device by VB-Audio.\n"
        "   Download the VB-CABLE Driver Pack from https://vb-audio.com/Cable/ , extract it,\n"
        "   right click VBCABLE_Setup_x64.exe, choose Run as administrator and press\n"
        "   Install Driver. Then restart the PC. (SpeakerWeave's Errors page also\n"
        "   points you there when VB-CABLE is missing.)\n")
    return (
        f"SpeakerWeave {shown}: installing it on another PC\n"
        f"\n"
        f"1. Double click {setup}.\n"
        f"   Windows may warn that it is from an unknown publisher, because the installer\n"
        f"   is not signed yet. Choose More info, then Run anyway.\n"
        f"{cable_step}"
        f"3. Open SpeakerWeave and tick your speakers. A short tour shows you around.\n"
        f"\n"
        f"To check the installer copied without damage (not needed): open PowerShell in\n"
        f"this folder and run  Get-FileHash \".\\{setup}\"  . The result should match the\n"
        f"number in {setup}.sha256.\n")


def main(argv=None, drives=None, ask=input) -> int:
    argv = sys.argv[1:] if argv is None else argv
    lines = []

    def say(text=""):
        lines.append(text)
        print(text, flush=True)

    try:
        return _copy(say, argv, drives, ask)
    finally:
        try:
            with open(REPORT, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
        except OSError:
            pass


def _copy(say, argv, drives, ask) -> int:
    from speakerweave import release
    shown = release.version_name()
    setup = os.path.join(RESULT, f"SpeakerWeave-Setup-{shown.replace(' ', '-')}.exe")
    if not os.path.isfile(setup):
        say(f"There is no installer at {setup}. Run Build installer.bat first.")
        return 1
    if os.path.getmtime(setup) < newest_source_time():
        say("The installer is older than the latest changes to SpeakerWeave, so it would")
        say("install an old version. Run Build installer.bat first, then this again.")
        return 1
    root = pick_drive(argv, drives, ask)
    if not root or not os.path.isdir(root):
        say(f"No drive {root[:2] or ''} to copy to. Nothing was copied.")
        return 1
    if root.upper().startswith("C:"):
        say("That is this PC's own drive, not a USB drive. Nothing was copied.")
        return 1
    target = os.path.join(root, FOLDER)
    need = os.path.getsize(setup) + 5 * 1024 * 1024
    cable = vbcable_pack()
    if cable:
        need += os.path.getsize(cable)
    if shutil.disk_usage(root).free < need:
        say(f"{root[:2]} has too little free space ({need / 1048576:.0f} MB needed). Nothing was copied.")
        return 1
    os.makedirs(target, exist_ok=True)
    say(f"Copying SpeakerWeave {shown} to {target}")
    copies = [setup, setup + ".sha256", os.path.join(RESULT, f"Release notes {shown}.md")]
    for path in copies:
        if os.path.isfile(path):
            shutil.copy2(path, os.path.join(target, os.path.basename(path)))
            say(f"   {os.path.basename(path)}")
    if cable:
        os.makedirs(os.path.join(target, "VB-CABLE"), exist_ok=True)
        shutil.copy2(cable, os.path.join(target, "VB-CABLE", os.path.basename(cable)))
        say(f"   VB-CABLE\\{os.path.basename(cable)}")
    with open(os.path.join(target, "How to install.txt"), "w", encoding="utf-8") as fh:
        fh.write(how_to_install(os.path.basename(setup), shown, cable))
    say("   How to install.txt")
    copied = os.path.join(target, os.path.basename(setup))
    if sha256_of(copied) != sha256_of(setup):
        say("The installer on the USB drive does not match the original. Try again or use another drive.")
        return 1
    say()
    say(f"Done, and checked: the installer on {root[:2]} matches the original exactly.")
    if not cable:
        say("No VB-CABLE driver pack was found in Downloads, so How to install.txt says where to get it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
