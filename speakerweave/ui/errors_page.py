"""The Errors page: everything that keeps sound from reaching the speakers, and
everything wrong with the surround setup, each with what to do about it.

The quick checks run on their own whenever something changes. "Run a full
sound check" also sends a silent test tone through the whole chain.
"""
from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from .. import paths, soundcheck, windefault
from ..release import version_name
from . import theme
from .panels import dim, scrolled

COLORS = {"error": "BAD", "warning": "WARN", "ok": "GOOD", "notice": "ACCENT"}
ACTION_TEXT = {
    "claim": "Fix it",
    "start": "Start the sound",
    "surround": "Set it to 7.1",
    "listen_virtual": "Listen to the PC",
    "rescan": "Rescan",
    "sound_panel": "Open the Sound control panel",
    "positions": "Choose positions",
    "room": "Go to the room",
    "simhub_install": "Install",
    "update": "Download and install",
    "update_page": "Open the download page",
    "simhub_port": "Choose a port",
}
GLITCH_LIMIT = 20          # interruptions in a run before it is worth a warning


class _Relay(QObject):
    done = Signal(object)


def _card(finding: soundcheck.Finding, on_action) -> QFrame:
    card = QFrame()
    card.setObjectName("card")
    color = getattr(theme, COLORS.get(finding.level, "DIM"))
    card.setStyleSheet(f"QFrame#card {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER}; "
                       f"border-left: 4px solid {color}; border-radius: 8px; }}")
    row = QHBoxLayout(card)
    row.setContentsMargins(14, 10, 12, 10)
    text = QVBoxLayout()
    text.setSpacing(3)
    kind = {"error": "Error", "warning": "Warning", "ok": "Working",
            "notice": "Notice"}.get(finding.level, "")
    if finding.area == "surround" and finding.level != "ok":
        kind += ", surround"
    head = QLabel(f"<span style='color:{color}; font-weight:700'>{kind}</span>"
                  f"&nbsp;&nbsp;<b>{finding.title}</b>")
    head.setWordWrap(True)
    text.addWidget(head)
    if finding.detail:
        text.addWidget(dim(finding.detail))
    if finding.fix:
        fix = QLabel(f"What to do: {finding.fix}")
        fix.setWordWrap(True)
        text.addWidget(fix)
    row.addLayout(text, 1)
    action = finding.action
    if action:
        label = "Untick it" if action.startswith("untick:") else ACTION_TEXT.get(action, "Fix it")
        button = QPushButton(label)
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        button.clicked.connect(lambda _=False, a=action: on_action(a))
        row.addWidget(button, 0, Qt.AlignTop)
    return card


class ErrorsPage(QWidget):
    countChanged = Signal(int, int, int)   # errors, warnings, notices

    def __init__(self, state, window):
        super().__init__()
        self.state = state
        self.window = window
        self.full_report = None            # the last full sound check
        self.last_found = []               # the errors and warnings of the last look, worst first
        self.full_time = ""
        self._checking = False
        self._relay = _Relay()
        self._relay.done.connect(self._full_done)

        inner = QWidget()
        outer = QHBoxLayout(inner)
        outer.setContentsMargins(16, 16, 16, 16)
        column = QWidget()
        column.setMaximumWidth(860)
        outer.addWidget(column, 1)
        outer.addStretch(0)
        self.col = QVBoxLayout(column)
        self.col.setSpacing(8)
        page = QVBoxLayout(self)
        page.setContentsMargins(0, 0, 0, 0)
        page.addWidget(scrolled(inner))

        head = QHBoxLayout()
        title = QLabel("Errors")
        title.setObjectName("title")
        head.addWidget(title)
        head.addStretch(1)
        self.full_btn = QPushButton("Run a full sound check")
        self.full_btn.setToolTip("Sends a silent test tone through the whole chain, from the PC to "
                                 "every speaker. Takes a few seconds.")
        head.addWidget(self.full_btn)
        self.col.addLayout(head)
        self.summary = dim("")
        self.col.addWidget(self.summary)
        self.list_box = QVBoxLayout()
        self.list_box.setSpacing(8)
        self.col.addLayout(self.list_box)
        self.col.addStretch(1)

        self.full_btn.clicked.connect(self.run_full_check)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self.refresh)
        self._live = QTimer(self)                   # catches trouble while the sound runs
        self._live.timeout.connect(self.refresh_soon)
        self._live.start(5000)
        for sig in (state.structureChanged, state.devicesScanned, state.runningChanged,
                    state.settingsChanged, state.problems, state.inputChanged):
            sig.connect(self.refresh_soon)

    # ------------------------------------------------------------ gathering
    def refresh_soon(self, *_args) -> None:
        self._timer.start()

    def findings(self) -> list:
        state = self.state
        report = soundcheck.Report()
        default = soundcheck.windows_default_name() if windefault.supported() else ""
        soundcheck.check_setup(state.project, state.outputs, state.loopbacks, report, default,
                               running=state.runner.running)
        for text in state.last_errors:
            if "not connected right now" in text:
                continue                            # already listed by the setup check
            report.add("error", text.split(":")[0] if ":" in text else "Starting the sound", text,
                       "Close other apps that use this output in exclusive mode, press Rescan, "
                       "then Start again.", action="rescan")
        runner = state.runner
        if runner.running:
            for dev_id, (_fill, _ppm, glitches) in runner.status().items():
                dev = state.project.find_device(dev_id)
                if dev is not None and glitches > GLITCH_LIMIT:
                    report.add("warning", f"{dev.title} keeps being interrupted",
                               f"{glitches} interruptions since the sound started.",
                               "Raise the Safety buffer on the Sound tab.")
            if runner.callback_errors:
                report.add("error", "The mixing engine reported errors",
                           f"{runner.callback_errors} blocks could not be processed.",
                           "Send the error log (Settings page, Open that folder) to the developer.")
            if state.engine.src_channels > 2 and not state.engine.surround_now:
                report.add("ok", "Stereo sound right now, spread over every speaker",
                           "As soon as a game sends surround, each channel goes to its own speaker.",
                           area="surround")
            elif state.engine.surround_now:
                report.add("ok", "Surround sound is arriving",
                           "Each channel goes to its own position.", area="surround")
        self._simhub_findings(report)
        self._update_findings(report)
        seen = {(f.level, f.title) for f in report.findings}
        if self.full_report is not None:
            for f in self.full_report.findings:
                if (f.level, f.title) not in seen:
                    report.findings.append(f)
                    seen.add((f.level, f.title))
        return report.findings

    def _update_findings(self, report) -> None:
        updater = getattr(self.window, "updater", None)
        info = getattr(updater, "info", None)
        if info is None:
            return
        version = version_name(info.version)
        notes = " ".join((info.notes or "").split())
        if len(notes) > 280:
            notes = notes[:280].rsplit(" ", 1)[0] + " ..."
        if info.url and paths.is_built():
            fix = ("Press Download and install: SpeakerWeave closes, updates itself and opens "
                   "again. Your settings and setups stay as they are.")
            action = "update"
        else:
            fix = "Open the download page and run the new installer."
            action = "update_page"
        report.add("notice", f"SpeakerWeave {version} is available",
                   f"You have {version_name()}." + (f" What's new: {notes}" if notes else ""),
                   fix, action=action, area="update")

    def _simhub_findings(self, report) -> None:
        settings, window = self.state.settings, self.window
        if not settings.simhub_link:
            return
        remote = window.remote
        if not remote.running and remote.error:
            report.add("warning", "The SimHub link could not start", remote.error,
                       "Choose a different link port on the Controls page.", action="simhub_port",
                       area="simhub")
        box = getattr(getattr(window, "extras_panel", None), "simhub_box", None)
        plugin = getattr(box, "plugin", "")
        if plugin in ("missing", "old"):
            title = ("The SpeakerWeave plugin is not in SimHub yet" if plugin == "missing"
                     else "SimHub has an older SpeakerWeave plugin")
            report.add("warning", title,
                       "SimHub is on this PC. With the plugin, SpeakerWeave loads your speaker setup "
                       "for each game, and SimHub buttons and dashboards can use SpeakerWeave.",
                       "Press Install and say yes when Windows asks. Then start SimHub and enable "
                       "the plugin when it asks. Don't want it? Untick Link with SimHub on the "
                       "Effects tab.", action="simhub_install", area="simhub")

    def refresh(self) -> None:
        found = self.findings()
        order = {"notice": 0, "error": 1, "warning": 2, "ok": 3}
        found.sort(key=lambda f: (order.get(f.level, 4), f.area == "surround"))
        while self.list_box.count():
            item = self.list_box.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        errors = len([f for f in found if f.level == "error"])
        warnings = len([f for f in found if f.level == "warning"])
        notices = len([f for f in found if f.level == "notice"])
        if not [f for f in found if f.level != "notice"]:
            found.append(soundcheck.Finding("ok", "No problems found",
                                            "Run a full sound check to test the whole chain."))
        heading = None
        for f in found:
            section = "Notices" if f.level == "notice" else "Sound and setup"
            if notices and section != heading:
                head = QLabel(section)
                head.setObjectName("subtitle")
                self.list_box.addWidget(head)
                heading = section
            self.list_box.addWidget(_card(f, self.do_action))
        parts = []
        if notices:
            parts.append(f"{notices} notice{'s' if notices != 1 else ''}")
        if errors:
            parts.append(f"{errors} error{'s' if errors != 1 else ''}")
        if warnings:
            parts.append(f"{warnings} warning{'s' if warnings != 1 else ''}")
        text = (", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else
                parts[0] if parts else "Nothing wrong") + "."
        if self.full_time:
            text += f"  Last full sound check: {self.full_time}."
        self.summary.setText(text)
        self.last_found = [f for f in found if f.level in ("error", "warning")]
        self.countChanged.emit(errors, warnings, notices)

    # ------------------------------------------------------------ full check
    def run_full_check(self) -> None:
        if self._checking:
            return
        self._checking = True
        self.full_btn.setEnabled(False)
        self.full_btn.setText("Checking...")
        state = self.state
        self._was_running = state.runner.running
        if self._was_running:
            state.stop(keep_windows=True)           # the check needs the devices for a moment
        project = state.project

        def work():
            try:
                report = soundcheck.run(project)
            except Exception as exc:                # never take the app down
                report = soundcheck.Report()
                report.add("error", "The sound check could not run", repr(exc))
            self._relay.done.emit(report)
        threading.Thread(target=work, daemon=True).start()

    def _full_done(self, report) -> None:
        self._checking = False
        self.full_btn.setEnabled(True)
        self.full_btn.setText("Run a full sound check")
        self.full_report = report
        self.full_time = time.strftime("%H:%M")
        if self._was_running:
            self.state.start()
        self.refresh()

    # ------------------------------------------------------------ fixes
    def do_action(self, action: str) -> None:
        state, window = self.state, self.window
        if action in ("claim", "start"):
            if state.runner.running:
                problem = state.make_default_output()
            else:
                state.start()
                problem = " ".join(state.last_errors)
            if problem:
                window.statusBar().showMessage(problem, 10000)
        elif action == "surround":
            listened = state.project.input_name.replace(" [Loopback]", "")
            was = state.runner.running
            if was:
                state.stop(keep_windows=True)
            settings = state.settings
            keep, settings.auto_surround = settings.auto_surround, True
            problem = state.ensure_surround(listened)
            settings.auto_surround = keep
            state.scan_devices()
            if was:
                state.start()
            if problem:
                window.statusBar().showMessage(problem, 10000)
        elif action == "listen_virtual":
            device, problem = state.prepare_source()
            if not device:
                state.settings.default_output = True
                device, problem = state.prepare_source()
            window.statusBar().showMessage(problem or f"Listening to {device}.", 8000)
            if state.runner.running:
                state.touch_streams()
        elif action == "rescan":
            state.scan_devices()
        elif action.startswith("untick:"):
            dev = state.project.find_device(action.split(":", 1)[1])
            if dev is not None:
                dev.enabled = False
                state.touch_streams()
        elif action == "sound_panel":
            import subprocess
            try:
                subprocess.Popen(["control", "mmsys.cpl"])
            except Exception:
                window.statusBar().showMessage("Open it with Win + R, then type mmsys.cpl", 8000)
        elif action == "positions":
            window.show_page(0)
            window._open_positions()
        elif action == "room":
            window.show_page(0)
        elif action in ("update", "update_page"):
            window.updater.install()
        elif action == "simhub_install":
            window.show_page(0)
            window.tabs.setCurrentWidget(window.extras_panel)
            box = window.extras_panel.simhub_box
            if box is not None and box.install_btn.isVisible():
                box._install()
        elif action == "simhub_port":
            window.show_page(1)                     # Controls
        self.refresh_soon()


def badge_text(errors: int, warnings: int, notices: int = 0) -> str:
    if errors:
        return f"Errors ({errors})"
    if notices:
        return f"Errors ({notices} new)"
    return "Errors"


def badge_style(errors: int, warnings: int, notices: int = 0) -> str:
    """The Errors button at rest. Warnings leave it in the theme's own colours: it only
    lights up yellow for a moment when one appears (see badge_flash_style)."""
    if errors:
        return (f"QPushButton {{ border-color: {theme.BAD}; color: {theme.BAD}; font-weight: 600; }}"
                f"QPushButton:checked {{ background: {theme.BAD}; color: #ffffff; }}")
    if notices:
        return f"QPushButton {{ border-color: {theme.ACCENT}; color: {theme.ACCENT}; font-weight: 600; }}"
    return ""


def badge_flash_style(kind: str) -> str:
    """The Errors button lit up: "warning" yellow (for a moment), "error" red (flashing)."""
    color = theme.WARN if kind == "warning" else theme.BAD
    ink = "#1b1b1b" if kind == "warning" else "#ffffff"
    return (f"QPushButton, QPushButton:checked {{ background: {color}; border-color: {color}; "
            f"color: {ink}; font-weight: 600; }}")
