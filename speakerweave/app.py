"""Starts the SpeakerWeave window."""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback


def _install_error_log(folder: str) -> None:
    """Anything unexpected is written to a file and shown once, instead of
    disappearing silently (the app normally runs without a console window)."""
    from PySide6.QtWidgets import QMessageBox

    path = os.path.join(folder, "error log.txt")
    last_shown = [0.0]

    def hook(kind, value, tb):
        text = "".join(traceback.format_exception(kind, value, tb))
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(time.strftime("%Y %m %d %H:%M:%S") + "\n" + text + "\n")
        except Exception:
            pass
        sys.__stderr__ and sys.__stderr__.write(text)
        if time.monotonic() - last_shown[0] > 10.0:
            last_shown[0] = time.monotonic()
            QMessageBox.warning(None, "SpeakerWeave",
                                f"Something went wrong:\n\n{kind.__name__}: {value}\n\n"
                                f"The details were saved to\n{path}")

    sys.excepthook = hook


def _selftest_windows(lines: list) -> int:
    """Checks the parts that talk to Windows itself, without changing anything:
    reading the default sound output, and reading a sound file through Windows."""
    if not sys.platform.startswith("win"):
        return 0
    code = 0
    from . import sounds, windefault
    try:
        outputs = windefault.list_outputs()
        _, name = windefault.default_output()
        found = windefault.find(name, outputs) if name else ""
        lines.append(f"windows default output: {name or 'none'} "
                     f"({len(outputs)} outputs, {'matched' if found or not name else 'NOT matched'})")
        if name and not found:
            code = 1
        # choosing the default: each role is set to the device it already has, so nothing changes
        before = windefault.defaults()
        for role, dev_id in before.items():
            if dev_id:
                windefault.set_default(dev_id, roles=(int(role),))
        same = windefault.defaults() == before
        lines.append("windows default output can be chosen: " + ("yes" if same else "CHANGED"))
        if not same:
            code = 1
    except Exception as exc:
        lines.append(f"windows default output: FAILED {exc!r}")
        code = 1
    try:
        # the volume the speakers follow: read once from the current default output
        from .wincom import Apartment
        from .winvolume import _EndpointVolume
        _, name = windefault.default_output()
        if name:
            with Apartment() as com:
                volume = _EndpointVolume(com, name)
                try:
                    gain, muted, percent = volume.read()
                finally:
                    volume.close()
            good = 0.0 <= gain <= 1.0001 and 0.0 <= percent <= 100.01
            lines.append(f"windows volume: {percent:.0f}%{' muted' if muted else ''}, "
                         f"gain {gain:.3f} ({'readable' if good else 'ODD'})")
            if not good:
                code = 1
    except Exception as exc:
        lines.append(f"windows volume: FAILED {exc!r}")
        code = 1
    try:
        import glob
        media = sorted(glob.glob(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Media", "*.wav")))
        if media:
            samples, rate = sounds._read_with_windows(media[0], 10.0)
            direct, direct_rate = sounds.read_wav(media[0])
            seconds, expected = samples.shape[0] / rate, direct.shape[0] / direct_rate
            same = abs(seconds - expected) < 0.1
            lines.append(f"windows sound reader: {seconds:.2f} s from {os.path.basename(media[0])}"
                         f" ({'same as' if same else 'DIFFERENT from'} {expected:.2f} s)")
            sound, _ = sounds.prepare(samples, rate)
            lines.append(f"test sound shaping: {len(sound) / sounds.RATE:.2f} s ready")
            if not same:
                code = 1
        else:
            lines.append("windows sound reader: no Windows sounds to try")
    except Exception as exc:
        lines.append(f"windows sound reader: FAILED {exc!r}")
        code = 1
    return code


def selftest(report_path: str) -> int:
    """Loads every part of the app once without showing anything, then writes
    "ok" or the error to report_path. The build script runs this against the
    finished SpeakerWeave.exe to prove that nothing was left out of it."""
    lines = []
    code = 0
    try:
        import numpy
        import scipy
        from scipy import signal  # noqa: F401
        from scipy.optimize import linear_sum_assignment  # noqa: F401
        import sounddevice
        from PySide6 import __version__ as qt_version
        from PySide6.QtWidgets import QApplication
        from . import __version__, backend, paths, updates  # noqa: F401
        from .ui import theme
        from .ui.state import AppState
        from .ui.window import MainWindow

        from .release import version_name
        lines.append(f"SpeakerWeave {version_name()} ({__version__}), Python {sys.version.split()[0]}, "
                     f"numpy {numpy.__version__}, scipy {scipy.__version__}, Qt {qt_version}, "
                     f"sounddevice {sounddevice.__version__}")
        from . import lights
        sample = lights.encode_colors([(255, 128, 0)])
        lights.parse_device(0, b"\0" * 4 + b"\0" * 4 + b"\1\0\0" + b"\1\0\0" * 4
                            + b"\0\0" + b"\0" * 4 + b"\0\0" + b"\0\0" + b"\0\0", 0)
        lines.append("lights: own OpenRGB connection ready" if sample == b"\xff\x80\x00\x00"
                     else "lights: FAILED")
        if sys.platform.startswith("win"):
            lines.append("loopback library: " + ("present" if backend.loopback_available() else "MISSING"))
            if not backend.loopback_available():
                code = 1
        lines.append(f"sound outputs seen: {len(backend.list_outputs())}")
        lines.append("guide: " + ("present" if os.path.exists(paths.resource("Guide.html")) else "MISSING"))
        app = QApplication.instance() or QApplication(sys.argv[:1])
        app.setApplicationName("SpeakerWeave selftest")
        theme.apply(app)
        state = AppState("")
        state.settings.start_sound = False
        state.settings.check_updates = False
        state.settings.remote_enabled = False
        state.settings.simhub_link = False
        state.settings.tour_done = True          # no tour over the window in a self test
        state.project.rgb_enabled = False
        state.settings.default_output = False    # a self test never changes Windows settings
        state.save_settings = lambda: None
        state.save_soon = lambda: None           # never write settings from a self test
        state.save_now = lambda: None
        window = MainWindow(state)
        app.processEvents()
        window.grab()                            # forces one full paint
        for page in range(4):
            window.show_page(page)
            window.pages.currentWidget().grab()
        state.runner.stop()
        lines.append("window: built and painted, all pages")
        if window.pads.available:
            lines.append(f"controllers: ready, {len(window.pads.devices())} found")
        else:
            lines.append(f"controllers: MISSING ({window.pads.error})")
            code = 1
        window.pads.stop()
        from . import speaker_library
        lines.append(f"speaker library: {len(speaker_library.LIBRARY)} entries")
        from . import simhub
        lines.append("SimHub plugin: " + ("included" if simhub.plugin_source() else
                                          "not included (SimHub is not on the PC that built this)"))
        # every colour theme builds and paints
        for key in theme.PRESETS:
            theme.apply(app, theme.PRESETS[key][2])
            window.grab()
        theme.apply(app, theme.PRESETS[theme.DEFAULT_THEME][2])
        lines.append(f"colour themes: {len(theme.PRESETS)} presets painted")
        code = max(code, _selftest_windows(lines))
        lines.insert(0, "ok" if code == 0 else "FAILED")
    except Exception:
        lines.insert(0, "FAILED")
        lines.append(traceback.format_exc())
        code = 1
    text = "\n".join(lines) + "\n"
    try:
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write(text)
    except Exception:
        pass
    if sys.stdout:
        try:
            sys.stdout.write(text)
        except Exception:
            pass
    return code


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="speakerweave",
                                     description="One sound input, many outputs, arranged as surround.")
    parser.add_argument("setup", nargs="?", default="", help="a saved setup file to open")
    parser.add_argument("--selftest", metavar="REPORT", default="",
                        help="load everything once, write the result to REPORT and quit")
    parser.add_argument("--tray", action="store_true",
                        help="start hidden, with only the icon in the system tray")
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest(args.selftest)

    from PySide6.QtWidgets import QApplication
    from .ui import theme
    from .ui.state import AppState, config_dir
    from .ui.window import MainWindow

    if sys.platform.startswith("win"):
        try:    # gives the window its own taskbar icon
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SpeakerWeave.App")
        except Exception:
            pass

    from . import uninstall
    uninstall.hold_running_mutex()      # the uninstaller waits until this copy has closed

    app = QApplication(sys.argv[:1])
    app.setApplicationName("SpeakerWeave")
    app.setWindowIcon(theme.app_icon())
    theme.apply(app)
    _install_error_log(config_dir())
    uninstall.mark_data_for_removal(config_dir(), False)   # an uninstall was cancelled: keep the data
    state = AppState(args.setup)
    theme.apply(app, theme.colors_for(state.settings))
    window = MainWindow(state)
    hidden = (args.tray or state.settings.start_in_tray) and window.tray is not None
    if not hidden:
        window.show()
    code = app.exec()
    state.shutdown()
    return code


if __name__ == "__main__":
    sys.exit(main())
