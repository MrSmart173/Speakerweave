"""The Effects tab: the link with SimHub, bass shakers, and extra sound sources
such as SimHub's ShakeIt effects or a spotter app, with each of their channels
sent to the speakers and shakers you pick."""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QProgressBar,
                               QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from .. import simhub
from ..model import SHAKER, ExtraSource, ROLE_NAMES
from ..speaker_library import recognise
from .panels import NumSlider, dim, scrolled, slim_combo

SURROUND_CHANNELS = ["front left", "front right", "centre", "LFE", "rear left", "rear right",
                     "side left", "side right"]
PRESETS = {
    "simhub": ("SimHub effects",
               "In SimHub, open ShakeIt Bass shakers and choose this device as the output. Give "
               "each effect group its own channel (for example tyres on front left, impacts on "
               "centre). Then send each channel below to the speakers or shakers that should play "
               "it."),
    "app": ("Spotter or voice app",
            "In Windows, open Settings, Sound, Volume mixer, and set the app's output (Crew Chief, "
            "Discord, a music app ...) to this device. Then send its channels below to the "
            "speakers that should play it."),
    "other": ("Extra sound", "Send each channel of this device to the speakers that should play it."),
}


def is_virtual(name: str) -> bool:
    entry = recognise(name.replace(" [Loopback]", ""))
    return entry is not None and entry.category == "virtual"


class RouteRow:
    """One channel of a source: its name, where it goes, how loud, and a meter."""

    def __init__(self, panel, grid: QGridLayout, row: int, src: ExtraSource, channel: int, count: int):
        self.panel, self.src, self.channel = panel, src, channel
        route = src.route(channel)
        default = (f"Channel {channel + 1} ({SURROUND_CHANNELS[channel]})"
                   if count > 2 and channel < len(SURROUND_CHANNELS)
                   else f"Channel {channel + 1}" + (" (left)" if channel == 0 and count == 2 else
                                                     " (right)" if channel == 1 and count == 2 else ""))
        self.name = QLineEdit(route.label)
        self.name.setPlaceholderText(default)
        self.name.setToolTip("Your own name for what plays on this channel, for example Tyres")
        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setTextVisible(False)
        self.meter.setFixedSize(46, 8)
        self.targets = QToolButton()
        self.targets.setPopupMode(QToolButton.InstantPopup)
        self.targets.setMinimumWidth(120)
        self.menu = QMenu(self.targets)
        self.menu.aboutToShow.connect(self._fill_menu)
        self.targets.setMenu(self.menu)
        self.gain = QDoubleSpinBox()
        self.gain.setRange(-30.0, 12.0)
        self.gain.setSingleStep(1.0)
        self.gain.setDecimals(1)
        self.gain.setSuffix(" dB")
        self.gain.setValue(route.gain_db)
        self.gain.setFixedWidth(84)
        self.gain.setToolTip("How loud this channel plays on the speakers it is sent to")
        self.name.setMinimumWidth(110)
        self.targets.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        grid.addWidget(self.name, row, 0)
        grid.addWidget(self.meter, row, 1)
        grid.addWidget(self.targets, row, 2)
        grid.addWidget(self.gain, row, 3)
        self.name.editingFinished.connect(self._renamed)
        self.gain.valueChanged.connect(self._gain_changed)
        self.update_text()

    def update_text(self) -> None:
        route = self.src.route(self.channel)
        names = []
        for spk_id in route.targets:
            dev, spk = self.panel.state.project.find_speaker(spk_id)
            if spk is not None:
                names.append(f"{spk.name} ({dev.title})")
        if not names:
            text = "Nowhere"
        elif len(names) <= 2:
            text = ", ".join(names)
        else:
            text = f"{len(names)} speakers"
        self.targets.setText(text)
        self.targets.setToolTip("Which speakers and shakers play this channel")

    def _fill_menu(self) -> None:
        self.menu.clear()
        project = self.panel.state.project
        route = self.src.route(self.channel)
        for dev in project.devices:
            self.menu.addSection(dev.title)
            for spk in dev.speakers:
                role = ROLE_NAMES.get(spk.role, spk.role)
                action = self.menu.addAction(f"{spk.name}   ({role})")
                action.setCheckable(True)
                action.setChecked(spk.id in route.targets)
                action.toggled.connect(lambda on, s=spk.id: self._toggle(s, on))
        if not project.devices:
            self.menu.addAction("Tick an output on the Room page first").setEnabled(False)

    def _toggle(self, spk_id: str, on: bool) -> None:
        route = self.src.route(self.channel)
        if on and spk_id not in route.targets:
            route.targets.append(spk_id)
        elif not on and spk_id in route.targets:
            route.targets.remove(spk_id)
        self.update_text()
        self.panel.state.touch_routing()

    def _renamed(self) -> None:
        self.src.route(self.channel).label = self.name.text().strip()
        self.panel.state.save_soon()

    def _gain_changed(self, value: float) -> None:
        self.src.route(self.channel).gain_db = float(value)
        self.panel.state.touch_routing()


class SimHubBox(QGroupBox):
    """The link with the SpeakerWeave plugin in SimHub, and a speaker setup per game."""

    CHOOSE = "?choose"

    def __init__(self, state, link):
        super().__init__("SimHub")
        self.state, self.link = state, link
        self._games_key = None
        self._install_until = 0.0
        v = QVBoxLayout(self)
        self.on = QCheckBox("Link with SimHub")
        self.on.setToolTip("SimHub tells SpeakerWeave which game runs, and can use SpeakerWeave's "
                           "actions on wheel buttons")
        self.status = dim("")
        top = QHBoxLayout()
        top.addWidget(self.on)
        top.addWidget(self.status, 1)
        v.addLayout(top)
        install_row = QHBoxLayout()
        self.install_btn = QPushButton("Install the SimHub plugin")
        self.install_btn.clicked.connect(self._install)
        install_row.addWidget(self.install_btn)
        install_row.addStretch(1)
        v.addLayout(install_row)
        self.install_note = dim("")
        v.addWidget(self.install_note)
        games_title = QLabel("Speaker setup for each game")
        games_title.setObjectName("subtitle")
        v.addWidget(games_title)
        v.addWidget(dim("When SimHub sees a game start, SpeakerWeave loads the setup picked here, "
                        "with its speakers, volumes and effects. Changes you make while a game runs "
                        "are kept in that game's setup."))
        self.games = QGridLayout()
        self.games.setHorizontalSpacing(6)
        self.games.setColumnStretch(1, 1)
        v.addLayout(self.games)
        v.addWidget(dim("In SimHub, Controls and events lists SpeakerWeave's actions (volume, mute, "
                        "setups ...) for wheel buttons, and dashboards can show its properties, for "
                        "example SpeakerWeavePlugin.VolumeDb."))
        self.on.toggled.connect(self._toggled)
        link.changed.connect(self.refresh)
        self._install_timer = QTimer(self)
        self._install_timer.timeout.connect(self._install_check)
        self.load()

    # ------------------------------------------------------------ showing
    def load(self) -> None:
        self.on.blockSignals(True)
        self.on.setChecked(self.state.settings.simhub_link)
        self.on.blockSignals(False)
        self._plugin_row()
        self._games_key = None
        self.refresh()

    def _plugin_row(self, note: str = "") -> None:
        self.folder = simhub.find_folder()
        self.plugin = simhub.plugin_state(self.folder)
        texts = {
            "no simhub": ("", "SimHub was not found on this PC. Get it from simhubdash.com, then come back here."),
            "no plugin": ("", "This copy of SpeakerWeave has no SimHub plugin with it. Build installer adds "
                              "it when SimHub is on the PC that builds."),
            "missing": ("Install the SimHub plugin", "The SpeakerWeave plugin is not in SimHub yet."),
            "old": ("Update the SimHub plugin", "SimHub has an older SpeakerWeave plugin."),
            "current": ("", "The SpeakerWeave plugin is in SimHub."),
        }
        button, text = texts[self.plugin]
        self.install_btn.setVisible(bool(button))
        self.install_btn.setText(button or "Install the SimHub plugin")
        self.install_note.setText(note or text)

    def refresh(self) -> None:
        settings, remote = self.state.settings, self.link.window.remote
        if not settings.simhub_link:
            text = "Off"
        elif not remote.running:
            text = remote.error or "The link could not start"
        elif remote.simhub_connected():
            game = simhub.game_title(self.link.game) if self.link.game else "no game running"
            text = f"Connected, {game}"
            if self.link.game and self.link.car:
                text += f" ({self.link.car})"
        elif self.plugin in ("missing", "no plugin", "no simhub"):
            text = "Not connected"
        else:
            text = "Waiting for SimHub (start it, and enable the SpeakerWeave plugin when it asks)"
        self.status.setText(text)
        key = (tuple(settings.games_seen), tuple(sorted(settings.game_setups.items())),
               tuple(settings.setup_slots), self.link.game)
        if key != self._games_key:
            self._games_key = key
            self._fill_games()

    def _fill_games(self) -> None:
        while self.games.count():
            item = self.games.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        settings = self.state.settings
        games = list(settings.games_seen)
        if self.link.game and self.link.game not in games:
            games.insert(0, self.link.game)
        rows = [""] + games
        for row, game in enumerate(rows):
            title = simhub.game_title(game)
            if game and game == self.link.game:
                title += "  (running)"
            label = QLabel(title)
            combo = slim_combo()
            self._fill_combo(combo, game)
            save = QPushButton("Use current")
            save.setToolTip("Save the speakers as they are now as the setup for " + simhub.game_title(game))
            combo.activated.connect(lambda _i, g=game, c=combo: self._chosen(g, c))
            save.clicked.connect(lambda _=False, g=game: self._save_current(g))
            self.games.addWidget(label, row, 0)
            self.games.addWidget(combo, row, 1)
            self.games.addWidget(save, row, 2)
        if not games:
            hint = dim("Games appear here once SimHub has seen them running.")
            self.games.addWidget(hint, len(rows), 0, 1, 3)

    def _fill_combo(self, combo: QComboBox, game: str) -> None:
        settings = self.state.settings
        chosen = settings.game_setups.get(game, "")
        combo.addItem("Keep the setup as it is", "")
        paths = []
        if chosen:
            paths.append((os.path.splitext(os.path.basename(chosen))[0], chosen))
        for i, path in enumerate(settings.setup_slots):
            if path and all(os.path.normcase(path) != os.path.normcase(p) for _, p in paths):
                paths.append((f"Slot {i + 1}: " + os.path.splitext(os.path.basename(path))[0], path))
        for text, path in paths:
            combo.addItem(text, path)
            if not os.path.isfile(path):
                combo.setItemText(combo.count() - 1, text + " (missing)")
        combo.addItem("Choose a setup file...", self.CHOOSE)
        index = combo.findData(chosen) if chosen else 0
        combo.setCurrentIndex(max(0, index))

    # ------------------------------------------------------------ changes
    def _toggled(self, on: bool) -> None:
        self.state.settings.simhub_link = on
        self.state.save_settings()
        self.link.window.apply_remote()
        self.refresh()

    def _chosen(self, game: str, combo: QComboBox) -> None:
        path = combo.currentData()
        if path == self.CHOOSE:
            from .simhub_link import game_dir
            path, _ = QFileDialog.getOpenFileName(self, f"Setup for {simhub.game_title(game)}", game_dir(),
                                                  "SpeakerWeave setup (*.json)")
            if not path:
                self._games_key = None
                self.refresh()
                return
        self.link.choose(game, path)

    def _save_current(self, game: str) -> None:
        path = self.link.save_current_for(game)
        self.state.notice.emit(f"Saved as the setup for {simhub.game_title(game)}: "
                               + os.path.basename(path))

    def _install(self) -> None:
        done, asked, message = simhub.install(self.folder, simhub.plugin_source())
        self._plugin_row(message)
        if done:
            self._plugin_row("Installed. Start SimHub and say yes when it asks to enable the "
                             "SpeakerWeave plugin.")
        elif asked:
            self._install_until = time.monotonic() + 60
            self._install_timer.start(1000)

    def _install_check(self) -> None:
        if simhub.plugin_state(self.folder) == "current":
            self._install_timer.stop()
            self._plugin_row("Installed. Start SimHub and say yes when it asks to enable the "
                             "SpeakerWeave plugin.")
        elif time.monotonic() > self._install_until:
            self._install_timer.stop()
            self._plugin_row("The plugin was not copied. Press the button again and answer yes "
                             "when Windows asks.")


class ExtrasPanel(QWidget):
    def __init__(self, state, simhub_link=None):
        super().__init__()
        self.state = state
        self._loading = False
        self.rows: dict = {}                 # source id -> [RouteRow]
        inner = QWidget()
        self.col = QVBoxLayout(inner)
        self.col.setContentsMargins(10, 10, 10, 10)
        self.col.setSpacing(6)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrolled(inner))

        self.simhub_box = None
        if simhub_link is not None:
            self.simhub_box = SimHubBox(state, simhub_link)
            self.col.addWidget(self.simhub_box)

        box = QGroupBox("Bass shakers")
        v = QVBoxLayout(box)
        v.addWidget(dim("Give a ButtKicker or any other tactile transducer the role Bass shaker on "
                        "the Speaker tab (or right click it on the map). It is then limited to 10 "
                        "to 80 Hz, change that on the Speaker tab."))
        self.game_bass = QCheckBox("Shakers feel the game's bass")
        self.game_bass.setToolTip("Off: shakers only play the effects sent to them below")
        v.addWidget(self.game_bass)
        row = QHBoxLayout()
        row.addWidget(QLabel("Game bass level"))
        self.game_level = NumSlider(-30.0, 6.0, 0.5, " dB")
        row.addWidget(self.game_level, 1)
        v.addLayout(row)
        self.shaker_note = dim("")
        v.addWidget(self.shaker_note)
        self.col.addWidget(box)

        head = QHBoxLayout()
        title = QLabel("Extra sound sources")
        title.setObjectName("title")
        head.addWidget(title)
        head.addStretch(1)
        self.add_btn = QPushButton("Add a source")
        add_menu = QMenu(self.add_btn)
        add_menu.addAction("SimHub effects (ShakeIt)", lambda: self.add_source("simhub"))
        add_menu.addAction("Spotter, voice chat or music app", lambda: self.add_source("app"))
        add_menu.addAction("Any other device", lambda: self.add_source("other"))
        self.add_btn.setMenu(add_menu)
        head.addWidget(self.add_btn)
        self.col.addLayout(head)
        self.col.addWidget(dim("Games mix all their sounds into one before Windows gets them, so "
                               "tyres or the spotter cannot be pulled out of the game sound. What "
                               "can be sent to chosen speakers: SimHub's ShakeIt effects, which "
                               "SimHub makes from the game's data, and other apps such as a "
                               "spotter or voice chat. Each plays into its own virtual device, and "
                               "SpeakerWeave mixes it into the speakers you pick here."))
        self.sources_box = QVBoxLayout()
        self.sources_box.setSpacing(8)
        self.col.addLayout(self.sources_box)
        self.col.addStretch(1)

        self.game_bass.toggled.connect(self._game_bass)
        self.game_level.valueChanged.connect(self._game_level)
        state.structureChanged.connect(self._refresh_soon)
        state.devicesScanned.connect(self._refresh_soon)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(150)
        self._refresh_timer.timeout.connect(self.load)
        self._meter_timer = QTimer(self)
        self._meter_timer.timeout.connect(self._meters)
        self._meter_timer.start(60)
        self._shown_ids: list = []
        self.load()

    # ------------------------------------------------------------ building
    def _refresh_soon(self, *_a) -> None:
        self._refresh_timer.start()

    def _choices(self, src: ExtraSource) -> list:
        """Devices this source can listen to: everything except the PC sound itself."""
        p = self.state.project
        out = []
        for text, kind, name in self.state.input_choices():
            if kind == "test" or (kind, name) == (p.input_kind, p.input_name):
                continue
            out.append((text, kind, name))
        if src.name and not any(n == src.name for _, _, n in out):
            out.append((f"Not connected: {src.name.replace(' [Loopback]', '')}", src.kind, src.name))
        return out

    def load(self) -> None:
        p = self.state.project
        self._loading = True
        self.game_bass.setChecked(p.shaker_game_on)
        self.game_level.setValue(p.shaker_game_db)
        self.game_level.setEnabled(p.shaker_game_on)
        shakers = [s for _, s in p.all_speakers() if s.role == SHAKER]
        self.shaker_note.setText(f"{len(shakers)} speaker{'s' if len(shakers) != 1 else ''} "
                                 f"set up as bass shaker." if shakers else
                                 "No speaker is a bass shaker yet.")
        while self.sources_box.count():
            item = self.sources_box.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.rows = {}
        for src in p.extra_sources:
            self.sources_box.addWidget(self._source_box(src))
        if not p.extra_sources:
            self.sources_box.addWidget(dim("No extra sources yet. Press Add a source."))
        self._loading = False

    def _source_box(self, src: ExtraSource) -> QGroupBox:
        box = QGroupBox(src.label)
        v = QVBoxLayout(box)
        top = QHBoxLayout()
        device = slim_combo()
        for text, kind, name in self._choices(src):
            device.addItem(text.replace("Everything this PC plays on: ", "Virtual device: "),
                           (kind, name))
        index = next((i for i in range(device.count()) if device.itemData(i)[1] == src.name), -1)
        if index < 0:
            device.insertItem(0, "Choose a device", ("", ""))
            index = 0
        device.setCurrentIndex(index)
        on = QCheckBox("On")
        on.setChecked(src.enabled)
        remove = QPushButton("Remove")
        top.addWidget(device, 1)
        top.addWidget(on)
        top.addWidget(remove)
        v.addLayout(top)
        kind = next((k for k, (title, _) in PRESETS.items() if title == src.label), "other")
        v.addWidget(dim(PRESETS[kind][1]))
        tools = QHBoxLayout()
        if kind == "app":
            mixer = QPushButton("Open the Windows volume mixer")
            mixer.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("ms-settings:apps-volume")))
            tools.addWidget(mixer)
        count = self._channels(src)
        if kind == "simhub" and src.name and is_virtual(src.name) and count < 8:
            seven = QPushButton("Give it 8 channels (7.1)")
            seven.setToolTip("ShakeIt can then put up to 8 effect groups on their own channels")
            seven.clicked.connect(lambda: self._make_71(src))
            tools.addWidget(seven)
        tools.addStretch(1)
        if tools.count() > 1:
            v.addLayout(tools)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(2, 2)
        rows = []
        if src.name:
            for ch in range(count):
                rows.append(RouteRow(self, grid, ch, src, ch, count))
        self.rows[src.id] = rows
        v.addLayout(grid)
        if not src.name:
            v.addWidget(dim("Choose the device this sound plays into."))

        device.activated.connect(lambda _i, s=src, d=device: self._device_chosen(s, d))
        on.toggled.connect(lambda value, s=src: self._enabled(s, value))
        remove.clicked.connect(lambda _=False, s=src: self._remove(s))
        return box

    def _channels(self, src: ExtraSource) -> int:
        fifo = self.state.engine.extra_fifos.get(src.id)
        if fifo is not None:
            return fifo.channels
        pool = self.state.loopbacks if src.kind == "loopback" else self.state.inputs
        info = next((d for d in pool if d.name == src.name), None)
        if info is not None:
            return max(1, min(int(info.inputs), 8))
        return max([r.channel + 1 for r in src.routes] + [2])

    # ------------------------------------------------------------ changes
    def add_source(self, kind: str) -> None:
        p = self.state.project
        label = PRESETS[kind][0]
        src = ExtraSource(label=label)
        # a sensible first device: a virtual one that is not the PC sound
        for text, k, name in self._choices(src):
            if k == "loopback" and is_virtual(name):
                src.kind, src.name = k, name
                break
        p.extra_sources.append(src)
        self.state.touch_streams()
        self.load()

    def _device_chosen(self, src: ExtraSource, combo: QComboBox) -> None:
        kind, name = combo.currentData()
        if not name:
            return
        src.kind, src.name = kind, name
        self.state.touch_streams()
        self._refresh_soon()

    def _enabled(self, src: ExtraSource, on: bool) -> None:
        if self._loading:
            return
        src.enabled = on
        self.state.touch_streams()

    def _remove(self, src: ExtraSource) -> None:
        self.state.project.extra_sources = [s for s in self.state.project.extra_sources if s is not src]
        self.state.touch_streams()
        self._refresh_soon()

    def _make_71(self, src: ExtraSource) -> None:
        settings = self.state.settings
        keep, settings.auto_surround = settings.auto_surround, True
        problem = self.state.ensure_surround(src.name.replace(" [Loopback]", ""))
        settings.auto_surround = keep
        self.state.scan_devices()
        if problem:
            self.state.notice.emit(problem)
        self._refresh_soon()

    def _game_bass(self, on: bool) -> None:
        if self._loading:
            return
        self.state.project.shaker_game_on = on
        self.game_level.setEnabled(on)
        self.state.touch_routing()

    def _game_level(self, value: float) -> None:
        if self._loading:
            return
        self.state.project.shaker_game_db = float(value)
        self.state.touch_routing()

    def _meters(self) -> None:
        if not self.isVisible():
            return
        peaks = self.state.engine.extra_peaks if self.state.runner.running else {}
        for src_id, rows in self.rows.items():
            levels = peaks.get(src_id)
            for row in rows:
                value = float(levels[row.channel]) if levels is not None and row.channel < len(levels) \
                    else 0.0
                row.meter.setValue(int(min(1.0, value * 1.4) * 100))

