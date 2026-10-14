# PyInstaller recipe for SpeakerWeave.exe.
# Run through "Build installer.bat" (or: python packaging/build.py), not by hand.
import os
import re
import sys

root = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, root)
from speakerweave import release  # noqa: E402

with open(os.path.join(root, "speakerweave", "__init__.py"), encoding="utf-8") as fh:
    version = re.search(r'__version__ = "([^"]+)"', fh.read()).group(1)
numbers = [int(n) for n in (version.split(".") + ["0", "0", "0", "0"])[:4]]

datas = [(os.path.join(root, "Guide.html"), "."), (os.path.join(root, "README.md"), ".")]

# The SpeakerWeave plugin for SimHub, built by build.py when SimHub is on this PC
plugin = os.environ.get("SPEAKERWEAVE_SIMHUB_PLUGIN", "")
if plugin and os.path.exists(plugin):
    datas.append((plugin, "simhub"))

# Controllers: only the core SDL2 library is shipped (zlib licence), none of the
# extra image, sound and font libraries that come in the same package.
binaries = []
try:
    import sdl2dll
    sdl_name = "SDL2.dll" if sys.platform == "win32" else None
    if sdl_name is None:
        sdl_name = next(n for n in os.listdir(sdl2dll.get_dllpath()) if n.startswith("libSDL2-2"))
    binaries.append((os.path.join(sdl2dll.get_dllpath(), sdl_name), "sdl2"))
except Exception as exc:                    # the self test will then report it
    print("WARNING: SDL2 library not found:", exc)

# The details Windows shows under Properties > Details of the .exe
version_file = None
work_dir = globals().get("workpath") or globals().get("WORKPATH") or os.path.join(root, "build")
if sys.platform == "win32" or os.environ.get("SPEAKERWEAVE_WRITE_VERSION_FILE"):
    version_file = os.path.join(work_dir, "version_info.txt")
    os.makedirs(work_dir, exist_ok=True)
    with open(version_file, "w", encoding="utf-8") as fh:
        fh.write(f"""
VSVersionInfo(
  ffi=FixedFileInfo(filevers={tuple(numbers)}, prodvers={tuple(numbers)}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', {release.PUBLISHER!r}),
      StringStruct('FileDescription', {release.APP_NAME!r}),
      StringStruct('FileVersion', {version!r}),
      StringStruct('InternalName', {release.APP_NAME!r}),
      StringStruct('OriginalFilename', {release.APP_NAME + '.exe'!r}),
      StringStruct('ProductName', {release.APP_NAME!r}),
      StringStruct('ProductVersion', {version!r})])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""")

a = Analysis(
    [os.path.join(root, "packaging", "run_speakerweave.py")],
    pathex=[root],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    excludes=["tkinter", "pytest", "matplotlib", "IPython", "PySide6.QtTest", "openrgb", "sdl2dll",
              "sdl2.ext", "sdl2.sdlimage", "sdl2.sdlmixer", "sdl2.sdlttf", "sdl2.sdlgfx",
              "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtNetwork", "PySide6.QtOpenGL"],
    noarchive=False,
)
# Leave out parts the app never uses. Smaller download, and nothing is shipped whose
# licence was not checked (for example the ASIO builds of PortAudio).
UNUSED = ("opengl32sw.dll", "libportaudio32bit", "libportaudioarm64", "-asio.dll",
          "Qt6Pdf", "Qt6Qml", "Qt6Quick", "Qt6VirtualKeyboard", "Qt6Network",
          "translations", "qmltooling", "virtualkeyboard", "networkinformation",
          "platforminputcontexts", os.sep + "tls" + os.sep, "/tls/")


def wanted(entry):
    dest = entry[0].replace("\\", "/")
    return not any(part.replace("\\", "/") in dest for part in UNUSED)


a.binaries = [b for b in a.binaries if wanted(b)]
a.datas = [d for d in a.datas if wanted(d)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=release.APP_NAME,
    console=False,                      # no black window behind the app
    upx=False,                          # packed files look suspicious to virus scanners
    icon=os.path.join(root, "packaging", "SpeakerWeave.ico"),
    version=version_file if sys.platform == "win32" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name=release.APP_NAME)
