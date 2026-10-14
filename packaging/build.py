"""Builds SpeakerWeave.exe and its installer. Started by "Build installer.bat".

Steps:
  0. the SpeakerWeave plugin for SimHub is built, when SimHub is on this PC
  1. PyInstaller turns the Python code into dist/SpeakerWeave/SpeakerWeave.exe
  2. the finished .exe is started once in self test mode to prove it is complete
  3. (optional) the .exe is signed with your code signing certificate
  4. Inno Setup wraps it into dist/installer/SpeakerWeave-Setup-<version>.exe
  5. (optional) the installer is signed, and its checksum is written next to it

Optional extras are switched on in packaging/build_settings.ini (created on the
first run, with explanations inside).
"""
from __future__ import annotations

import configparser
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SETTINGS = os.path.join(HERE, "build_settings.ini")


def work_root() -> str:
    """Where the thousands of temporary build files go. On Windows that is a
    folder outside the project, because a project kept in OneDrive or another
    synced folder gets its files locked by the sync while they are written."""
    base = os.environ.get("LOCALAPPDATA") if os.name == "nt" else ""
    if base:
        return os.path.join(base, "SpeakerWeaveBuild")
    return ROOT


WORK = work_root()
DIST = os.path.join(WORK, "dist")           # the built app folder and the raw installer
RESULT = os.path.join(ROOT, "dist", "installer")   # where the finished installer is copied to

DEFAULT_SETTINGS = """\
; Optional settings for building the SpeakerWeave installer.

[signing]
; Leave "subject" empty to build without a signature.
; To sign, plug in the token of your code signing certificate and write the
; name the certificate was issued to, exactly as shown in the certificate,
; for example:   subject = Eli Smart
subject =
; The time stamp server of your certificate provider.
timestamp = http://timestamp.digicert.com
; Full path of signtool.exe. Leave empty to search the usual places.
signtool =
"""


def say(text: str = "") -> None:
    print(text, flush=True)


def fail(text: str):
    say()
    say("STOPPED: " + text)
    sys.exit(1)


def run(args: list, **kw) -> int:
    say("  > " + " ".join(f'"{a}"' if " " in str(a) else str(a) for a in args))
    return subprocess.call(args, **kw)


def read_version() -> str:
    with open(os.path.join(ROOT, "speakerweave", "__init__.py"), encoding="utf-8") as fh:
        match = re.search(r'__version__ = "([^"]+)"', fh.read())
    if not match:
        fail("could not find the version number in speakerweave/__init__.py")
    return match.group(1)


def read_settings() -> configparser.ConfigParser:
    if not os.path.exists(SETTINGS):
        with open(SETTINGS, "w", encoding="utf-8") as fh:
            fh.write(DEFAULT_SETTINGS)
    parser = configparser.ConfigParser()
    parser.read(SETTINGS, encoding="utf-8")
    return parser


# ---------------------------------------------------------------- tools

def program_folders() -> list:
    names = ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432", "LocalAppData")
    found = []
    for name in names:
        value = os.environ.get(name)
        if value and value not in found:
            found.append(value)
    return found


def find_inno() -> str:
    on_path = shutil.which("ISCC") or shutil.which("iscc")
    if on_path:
        return on_path
    for base in program_folders():
        for sub in ("Inno Setup 6", os.path.join("Programs", "Inno Setup 6")):
            candidate = os.path.join(base, sub, "ISCC.exe")
            if os.path.exists(candidate):
                return candidate
    return ""


def find_signtool(configured: str) -> str:
    if configured and os.path.exists(configured):
        return configured
    on_path = shutil.which("signtool")
    if on_path:
        return on_path
    best = ""
    for base in program_folders():
        kits = os.path.join(base, "Windows Kits", "10", "bin")
        if not os.path.isdir(kits):
            continue
        for version in sorted(os.listdir(kits), reverse=True):
            candidate = os.path.join(kits, version, "x64", "signtool.exe")
            if os.path.exists(candidate):
                best = best or candidate
    return best


def offer_inno_install() -> str:
    say()
    say("Inno Setup (the free tool that makes the installer) is not on this PC yet.")
    if not shutil.which("winget"):
        say("Download it from https://jrsoftware.org/isdl.php , install it, then run this again.")
        return ""
    say("Installing it now with the Windows package manager (winget). If Windows asks for")
    say("permission, press Yes.")
    run(["winget", "install", "--id", "JRSoftware.InnoSetup", "-e",
         "--accept-source-agreements", "--accept-package-agreements"])
    return find_inno()


def sign(path: str, settings: configparser.ConfigParser) -> bool:
    """Signs one file if signing is switched on. Returns True if it was signed."""
    subject = settings.get("signing", "subject", fallback="").strip()
    if not subject:
        return False
    tool = find_signtool(settings.get("signing", "signtool", fallback="").strip())
    if not tool:
        fail("signing is switched on, but signtool.exe was not found. Install the Windows SDK "
             "or write its full path into packaging/build_settings.ini")
    stamp = settings.get("signing", "timestamp", fallback="").strip() or "http://timestamp.digicert.com"
    code = run([tool, "sign", "/n", subject, "/fd", "SHA256", "/tr", stamp, "/td", "SHA256",
                "/d", "SpeakerWeave", path])
    if code != 0:
        fail(f"signing {os.path.basename(path)} failed. Is the certificate token plugged in, and "
             f"is the subject name in build_settings.ini exactly right?")
    return True


# Bundled components: (distribution name, shown name, licence)
COMPONENTS = [
    ("PySide6_Essentials", "Qt for Python (PySide6) and the Qt libraries", "LGPL-3.0"),
    ("shiboken6", "Shiboken (part of Qt for Python)", "LGPL-3.0"),
    ("numpy", "NumPy", "BSD-3-Clause and others"),
    ("scipy", "SciPy", "BSD-3-Clause and others"),
    ("sounddevice", "python-sounddevice", "MIT"),
    ("cffi", "CFFI", "MIT"),
    ("PyAudioWPatch", "PyAudioWPatch", "Apache-2.0"),
    ("PySDL2", "PySDL2 (controller support)", "Public domain / zlib"),
    ("pysdl2-dll", "SDL2 library (controller support)", "zlib (SDL2), MPL-2.0 (packaging)"),
]
# For these packages only some licence files belong to what is shipped
ONLY = {"pysdl2-dll": ("licenses/LICENSE", "SDL2/")}
LICENCE_WORDS = ("LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS")


def collect_licences(app_dir: str) -> None:
    """Puts the licence texts of everything bundled into <app>/licenses, plus an
    overview, as the licences of those components require."""
    import importlib.metadata as metadata

    target = os.path.join(app_dir, "licenses")
    shutil.rmtree(target, ignore_errors=True)
    os.makedirs(target)
    lines = ["SpeakerWeave includes the following components made by other authors.",
             "Each is provided under its own licence. The licence texts are in this folder.", ""]
    python_licence = os.path.join(sys.base_prefix, "LICENSE.txt")
    if os.path.exists(python_licence):
        shutil.copy2(python_licence, os.path.join(target, "Python LICENSE.txt"))
        lines.append(f"Python {sys.version.split()[0]}  (Python Software Foundation License)"
                     f"  see 'Python LICENSE.txt'")
    else:
        lines.append(f"Python {sys.version.split()[0]}  (Python Software Foundation License)"
                     f"  https://docs.python.org/3/license.html")
    for dist_name, shown, licence in COMPONENTS:
        try:
            dist = metadata.distribution(dist_name)
        except metadata.PackageNotFoundError:
            continue
        folder = os.path.join(target, dist_name)
        copied = 0
        for item in dist.files or []:
            name = os.path.basename(str(item)).upper()
            wanted = ONLY.get(dist_name)
            if wanted and not any(part in str(item).replace("\\", "/") for part in wanted):
                continue
            if any(word in name for word in LICENCE_WORDS) or (wanted and "README" in name):
                source = item.locate()
                if os.path.isfile(source):
                    os.makedirs(folder, exist_ok=True)
                    flat = str(item).replace("/", "_").replace("\\", "_")
                    shutil.copy2(source, os.path.join(folder, flat))
                    copied += 1
        where = f"see folder '{dist_name}'" if copied else "see the licence files named below"
        lines.append(f"{shown} {dist.version}  ({licence})  {where}")
    for name in os.listdir(os.path.join(HERE, "licenses")):
        shutil.copy2(os.path.join(HERE, "licenses", name), os.path.join(target, name))
    lines += [
        "PortAudio (inside python-sounddevice and PyAudioWPatch)  (MIT)  see 'PortAudio.txt'",
        "",
        "Qt and Qt for Python are used under the GNU Lesser General Public License version 3",
        "('LGPL-3.0.txt', which builds on 'GPL-3.0.txt'). They are included unmodified as",
        "separate library files in the _internal\\PySide6 and _internal\\shiboken6 folders and may",
        "be replaced with other compatible versions. Their source code is available from",
        "https://download.qt.io/official_releases/QtForPython/ and https://code.qt.io",
        "",
        "VB-CABLE (if installed) is a product of VB-Audio Software, https://vb-audio.com/Cable/",
        "VB-CABLE is a donationware, all participations are welcome.",
    ]
    with open(os.path.join(target, "THIRD PARTY NOTICES.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def render_terms(app_dir: str) -> str:
    """Fills your publisher name into the licence terms shown by the installer."""
    import datetime

    sys.path.insert(0, ROOT)
    from speakerweave import release

    with open(os.path.join(HERE, "LICENSE_TEMPLATE.txt"), encoding="utf-8") as fh:
        text = fh.read()
    text = text.replace("{PUBLISHER}", release.PUBLISHER).replace("{YEAR}", str(datetime.date.today().year))
    path = os.path.join(app_dir, "LICENSE.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------- steps

def update_libraries() -> None:
    say("[0/4] Making sure every library the app needs is installed")
    code = run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                "-r", os.path.join(ROOT, "requirements.txt")])
    if code != 0:
        fail("could not install the libraries. Check the internet connection.")
    say()


def build_simhub_plugin() -> None:
    """Builds the SimHub plugin with the C# compiler that comes with Windows, so the
    app can put it into SimHub. Left out, with a note, when SimHub is not here."""
    say("      SimHub plugin:")
    out = os.path.join(WORK, "simhub")
    dll = os.path.join(out, "SpeakerWeave.SimHubPlugin.dll")
    if os.path.exists(dll):
        os.remove(dll)                          # never ship one left over from an older build
    os.environ.pop("SPEAKERWEAVE_SIMHUB_PLUGIN", None)
    if os.name != "nt":
        say("      skipped: it can only be built on Windows")
        return
    script = os.path.join(HERE, "simhub", "build_plugin.bat")
    # /s with the whole command in one more pair of quotes keeps paths with spaces whole
    code = subprocess.call(f'cmd /s /c ""{script}" "{out}""')
    if code == 0 and os.path.exists(dll):
        os.environ["SPEAKERWEAVE_SIMHUB_PLUGIN"] = dll
        say("      included")
    elif code in (2, 3):
        say("      left out, the app will say so on its Effects tab")
    else:
        fail("the SimHub plugin did not build (the compiler's message is above).")
    say()


def build_exe() -> str:
    say("[1/4] Turning the app into SpeakerWeave.exe (a few minutes)")
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        if run([sys.executable, "-m", "pip", "install", "--quiet", "pyinstaller"]) != 0:
            fail("could not download PyInstaller. Check the internet connection.")
    code = run([sys.executable, "-m", "PyInstaller", os.path.join(HERE, "SpeakerWeave.spec"),
                "--noconfirm", "--distpath", DIST, "--workpath", os.path.join(WORK, "build")],
               cwd=ROOT)
    name = "SpeakerWeave.exe" if os.name == "nt" else "SpeakerWeave"
    exe = os.path.join(DIST, "SpeakerWeave", name)
    if code != 0 or not os.path.exists(exe):
        fail("PyInstaller did not produce SpeakerWeave.exe. The first error is further up.")
    return exe


def self_test(exe: str) -> None:
    say()
    say("[2/4] Starting the finished .exe once to check that nothing is missing")
    report = os.path.join(tempfile.mkdtemp(), "selftest.txt")
    env = dict(os.environ)
    if os.name != "nt":
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        code = subprocess.call([exe, "--selftest", report], env=env, timeout=180)
    except subprocess.TimeoutExpired:
        fail("the .exe did not answer within three minutes")
    text = ""
    if os.path.exists(report):
        with open(report, encoding="utf-8") as fh:
            text = fh.read()
    for line in text.strip().splitlines():
        say("      " + line)
    if code != 0 or not text.startswith("ok"):
        fail("the built .exe failed its self test (details above). Nothing was packaged.")


def build_installer(version: str, settings: configparser.ConfigParser, terms: str) -> str:
    say()
    say("[3/4] Making the installer")
    if os.name != "nt":
        say("      skipped: installers can only be made on Windows")
        return ""
    iscc = find_inno() or offer_inno_install()
    if not iscc:
        fail("Inno Setup is needed to make the installer.")
    sys.path.insert(0, ROOT)
    from speakerweave import release

    args = [iscc, f"/DAppVersion={version}", f"/DPublisher={release.PUBLISHER}", f"/DDistDir={DIST}",
            f"/DLicenseFile={terms}"]
    if release.WEBSITE.strip():
        args.append(f"/DWebsite={release.WEBSITE.strip()}")
    cable = os.path.join(ROOT, "third_party", "VBCABLE", "VBCABLE_Setup_x64.exe")
    if os.path.exists(cable):
        say("      VB-CABLE driver pack found: it will be offered during installation")
        args.append("/DWithVbCable")
    else:
        say("      no VB-CABLE driver pack in third_party\\VBCABLE: the installer will not offer it")
    args.append(os.path.join(HERE, "SpeakerWeave.iss"))
    if run(args, cwd=HERE) != 0:
        fail("Inno Setup reported an error (see above).")
    installer = os.path.join(DIST, "installer", f"SpeakerWeave-Setup-{version}.exe")
    if not os.path.exists(installer):
        fail("Inno Setup finished but the installer file is missing.")
    return installer


def main() -> int:
    os.chdir(ROOT)
    version = read_version()
    settings = read_settings()
    say(f"Building SpeakerWeave {version}")
    say()
    update_libraries()
    build_simhub_plugin()
    exe = build_exe()
    collect_licences(os.path.dirname(exe))
    terms = render_terms(os.path.dirname(exe))
    self_test(exe)
    signed = sign(exe, settings)
    installer = build_installer(version, settings, terms)
    say()
    say("[4/4] Finishing")
    if not installer:
        say(f"      The app folder is ready: {os.path.dirname(exe)}")
        return 0
    signed = sign(installer, settings) or signed
    os.makedirs(RESULT, exist_ok=True)
    final = os.path.join(RESULT, os.path.basename(installer))
    shutil.copy2(installer, final)
    installer = final
    checksum = sha256_of(installer)
    with open(installer + ".sha256", "w", encoding="utf-8") as fh:
        fh.write(f"{checksum}  {os.path.basename(installer)}\n")
    size = os.path.getsize(installer) / (1024 * 1024)
    sys.path.insert(0, ROOT)
    from speakerweave import updates

    say(f"      Installer : {installer}  ({size:.0f} MB)")
    say(f"      Checksum  : {checksum}")
    say(f"      Signed    : {'yes' if signed else 'no (Windows will warn people who download it)'}")
    say(f"      Updates   : {'look at ' + updates.source_url() if updates.configured() else 'not set up yet (see RELEASING.md)'}")
    say()
    say("Done. RELEASING.md explains how to publish it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
