"""The main window."""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QPoint, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QFileDialog, QHBoxLayout,
                               QLabel, QMainWindow, QMenu, QMessageBox, QPushButton, QSlider,
                               QSpinBox, QSplitter, QStackedWidget, QSystemTrayIcon, QTabWidget,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QWidgetAction)

from .. import backend, paths, speaker_library, updates, windefault
from ..controls import actions_for_pad, key_bindings
from ..gamepads import GamepadWatcher
from ..model import (CUSTOM, OFF, SURROUND_SWITCHABLE, Project, ROLE_COLORS, ROLE_NAMES,
                     auto_align_delays, auto_assign_roles, face_listener, is_shape, mode_choices,
                     mode_label, standard_mode_for)
from .. import hidden
from ..release import version_name
from ..remote import RemoteServer
from .simhub_link import SimHubLink
from .tour import Tour, window_steps
from ..rgb import level_to_unit
from . import theme
from .actions import ActionRunner
from .bluetooth_dialog import BluetoothDialog
from .controls_page import ControlsPage
from .hotkeys import GlobalHotkeys
from .panels import DevicePanel, LightsPanel, SoundPanel, SpeakerPanel, dim, fill_sound_menu, tag
from .positions_dialog import PositionsDialog
from .roommap import RoomMap
from .errors_page import ErrorsPage, badge_style, badge_text
from .easy_sync import start_easy_sync
from .extras import ExtrasPanel
from .found_again import ACTIVATE, IGNORE_ALWAYS, FoundAgainNote, UpdateNote
from .levels import LevelsBar
from .settings_page import SettingsPage, about_text
from .updater import UpdateController

ROLE_KEY = Qt.UserRole


def chip(color: str) -> QIcon:
    pix = QPixmap(12, 12)
    pix.fill(QColor(color))
    return QIcon(pix)


class MainWindow(QMainWindow):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.setWindowTitle(f"SpeakerWeave {version_name()}")
        self.setWindowIcon(theme.app_icon())
        self.resize(1500, 900)
        self._tree_loading = False
        self._tree_pending = False
        self._clip_until: dict[str, float] = {}
        self._last_blocks = -1
        self._last_block_time = 0.0
        self._quitting = False
        self._hidden_open = False           # the "Hidden by user" folder is opened
        self._hidden_head = None
        self._found_queue: list = []        # hidden outputs plugged in again, to be announced
        self._found_note = None
        self._flash_on = False
        self._output_count = None

        # things that can trigger actions: keys, controllers, Stream Deck links
        self.actions = ActionRunner(self, state)
        self.pads = GamepadWatcher()
        self.remote = RemoteServer(state.settings.remote_port, state.settings.remote_token,
                                   self.actions.requested.emit)
        self.simhub = SimHubLink(self, state)
        self.remote.on_game = self.simhub.reported.emit

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 6)
        root.setSpacing(8)
        root.addLayout(self._build_top())
        self.banner = QLabel("")
        self.banner.setObjectName("banner")
        self.banner.setWordWrap(True)
        self.banner.hide()
        root.addWidget(self.banner)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._build_left())
        split.addWidget(self._build_centre())
        self.tabs = QTabWidget()
        self.speaker_panel = SpeakerPanel(state)
        self.device_panel = DevicePanel(state)
        self.sound_panel = SoundPanel(state)
        self.lights_panel = LightsPanel(state)
        self.tabs.addTab(self.speaker_panel, "Speaker")
        self.tabs.addTab(self.device_panel, "Output")
        self.tabs.addTab(self.sound_panel, "Sound")
        self.tabs.addTab(self.lights_panel, "Lights")
        self.extras_panel = ExtrasPanel(state, self.simhub)
        self.tabs.addTab(self.extras_panel, "Effects")
        self.tabs.setTabToolTip(4, "SimHub, bass shakers, and extra sounds such as SimHub effects")
        self.tabs.setMinimumWidth(470)
        split.addWidget(self.tabs)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([280, 720, 500])
        self.controls_page = ControlsPage(state, self)
        self.settings_page = SettingsPage(state, self)
        self.errors_page = ErrorsPage(state, self)
        room_page = QWidget()
        room = QVBoxLayout(room_page)
        room.setContentsMargins(0, 0, 0, 0)
        room.setSpacing(6)
        room.addWidget(split, 1)
        self.levels = LevelsBar(state)
        self.levels.setVisible(state.settings.show_levels)
        room.addWidget(self.levels)
        self.pages = QStackedWidget()
        self.pages.addWidget(room_page)
        self.pages.addWidget(self.controls_page)
        self.pages.addWidget(self.settings_page)
        self.pages.addWidget(self.errors_page)
        self.errors_page.countChanged.connect(self._errors_counted)
        root.addWidget(self.pages, 1)
        self.run_label = QLabel("Stopped")
        self.run_label.setObjectName("dim")
        self.statusBar().addPermanentWidget(self.run_label)

        state.structureChanged.connect(self._structure_changed)
        state.selectionChanged.connect(self._selection_changed)
        state.runningChanged.connect(self._running_changed)
        state.problems.connect(self._show_problems)
        state.notice.connect(lambda text: self.statusBar().showMessage(text, 6000))
        state.devicesScanned.connect(self._devices_scanned)
        state.inputChanged.connect(self._load_inputs)
        state.masterChanged.connect(self._load_master)
        state.metronomeChanged.connect(self._metronome_changed)
        state.windowsVolumeChanged.connect(self._windows_volume_changed)
        state.structureChanged.connect(state.refresh_metronome)
        state.selectionChanged.connect(state.refresh_metronome)
        self.updater = UpdateController(self, state)
        self.updater.available.connect(self.errors_page.refresh_soon)
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(self.UPDATE_CHECK_MS)
        self._update_timer.timeout.connect(self._check_updates_now)
        self._update_timer.start()
        self.hotkeys = GlobalHotkeys(self)
        self.hotkeys.triggered.connect(self.actions.run)
        self._build_tray()

        self._meter_timer = QTimer(self)
        self._meter_timer.timeout.connect(self._tick_meters)
        self._meter_timer.start(40)
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._tick_status)
        self._status_timer.start(500)
        self._pad_timer = QTimer(self)
        self._pad_timer.timeout.connect(self._poll_pads)
        self._watch_timer = QTimer(self)
        self._watch_timer.timeout.connect(self._watch_outputs)
        self._watch_timer.start(2000)
        self._flash_timer = QTimer(self)
        self._flash_timer.setInterval(450)
        self._flash_timer.timeout.connect(self._flash_hidden)

        self._load_top()
        self._rebuild_tree()
        theme.pad_number_boxes(self)
        self._fit_to_screen()
        QTimer.singleShot(0, self._startup)

    def _fit_to_screen(self) -> None:
        """Opens at a size that fits the screen. On a small or zoomed laptop
        screen the window opens maximised instead of reaching past the edges."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        room = screen.availableGeometry()
        need = self.minimumSizeHint()
        if need.width() > room.width() - 40 or need.height() > room.height() - 40 \
                or self.width() > room.width() or self.height() > room.height():
            self.resize(min(self.width(), room.width()), min(self.height(), room.height()))
            self.setWindowState(Qt.WindowMaximized)
        else:
            self.move(room.center().x() - self.width() // 2, room.center().y() - self.height() // 2)

    # ------------------------------------------------------------ building
    def _build_top(self):
        # everything here can shrink, so the window also fits a small or zoomed laptop screen
        row = QHBoxLayout()
        row.setSpacing(6)
        self.start_btn = QPushButton("Start")
        self.start_btn.setObjectName("primary")
        self.start_btn.setCheckable(True)
        self.start_btn.setMinimumWidth(84)
        row.addWidget(self.start_btn)

        row.addWidget(tag("Mode"))
        self.mode = QComboBox()
        for mode, rear in mode_choices():
            self.mode.addItem("Custom..." if mode == CUSTOM else mode_label(mode, rear),
                              mode + (" rear" if rear else ""))
        self.mode.setMaxVisibleItems(20)
        # the box stays compact, the open list is wide enough for the longest entry
        self.mode.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.mode.setMinimumContentsLength(12)
        self.mode.setMaximumWidth(360)
        self.mode.view().setMinimumWidth(self.mode.view().sizeHintForColumn(0) + 40)
        self.mode.setToolTip("Which speaker positions your room has. 4.0, 4.1, 5.0 and 5.1 come with "
                             "the surround pair beside you (side) or behind you (rear). Custom lets "
                             "you tick any combination.")
        row.addWidget(self.mode, 2)
        self.positions_btn = QPushButton("Positions")
        self.positions_btn.setToolTip("Tick any combination of speaker positions and subwoofers")
        row.addWidget(self.positions_btn)

        row.addWidget(tag("Listen to"))
        self.input = QComboBox()
        self.input.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.input.setMinimumContentsLength(12)
        self.input.setToolTip("The one sound source that is spread over all your speakers")
        row.addWidget(self.input, 4)
        self.rescan = QPushButton("Rescan")
        self.rescan.setToolTip("Look for sound devices again after plugging something in")
        row.addWidget(self.rescan)

        self.master = QSlider(Qt.Horizontal)
        self.master.setToolTip("Volume of all speakers together")
        self.master.setRange(-60, 12)
        self.master.setMinimumWidth(80)
        self.master.setMaximumWidth(150)
        row.addWidget(self.master, 1)
        self.master_text = QLabel("")
        self.master_text.setFixedWidth(50)
        row.addWidget(self.master_text)

        self.setup_btn = QPushButton("Setup")
        menu = QMenu(self.setup_btn)
        menu.addAction("New empty setup", self._new_setup)
        menu.addAction("Open a saved setup...", self._open_setup)
        menu.addAction("Save this setup as...", self._save_setup)
        menu.addSeparator()
        menu.addAction("Open the guide", self._open_guide)
        menu.addAction("Take the tour", self.start_tour)
        menu.addAction("Check for updates", lambda: self.updater.check(manual=True))
        menu.addAction("About SpeakerWeave", self._about)
        self.setup_btn.setMenu(menu)
        row.addWidget(self.setup_btn)

        row.addSpacing(6)
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        # page numbers: 0 room, 1 controls, 2 settings, 3 errors (shown second)
        for index, text in ((0, "Room"), (3, "Errors"), (1, "Controls"), (2, "Settings")):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setChecked(index == 0)
            self.nav.addButton(button, index)
            row.addWidget(button)
        self.errors_btn = self.nav.button(3)
        self.errors_btn.setToolTip("Anything that keeps the sound from reaching your speakers, and "
                                   "anything wrong with the surround setup")
        self.nav.idClicked.connect(self.show_page)

        self.start_btn.clicked.connect(self._toggle_running)
        self.mode.activated.connect(self._mode_changed)
        self.positions_btn.clicked.connect(self._open_positions)
        self.input.activated.connect(self._input_changed)
        self.rescan.clicked.connect(self.state.scan_devices)
        self.master.valueChanged.connect(self._master_changed)
        return row

    def _build_left(self):
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Sound outputs")
        title.setObjectName("title")
        col.addWidget(title)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.setMinimumWidth(210)
        col.addWidget(self.tree, 1)
        col.addWidget(dim("Tick an output to use it. Click a speaker to change its role and sound."))
        self.bluetooth_btn = QPushButton("Bluetooth devices")
        self.bluetooth_btn.setToolTip("See the Bluetooth devices paired with this PC, or open the "
                                      "Windows Bluetooth settings")
        col.addWidget(self.bluetooth_btn)
        self.bluetooth_btn.clicked.connect(lambda: BluetoothDialog(self).exec())
        self.tree.itemChanged.connect(self._tree_item_changed)
        self.tree.itemClicked.connect(self._tree_clicked)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.itemExpanded.connect(lambda item: self._folder_toggled(item, True))
        self.tree.itemCollapsed.connect(lambda item: self._folder_toggled(item, False))
        return box

    def _build_centre(self):
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        self.map = RoomMap(self.state)
        col.addWidget(self.map, 1)
        row = QHBoxLayout()
        self.assign_btn = QPushButton("Set roles")
        self.assign_btn.setToolTip("Gives every speaker the role that matches where it sits "
                                   "around you on the map")
        self.align_btn = QPushButton("Line up delays")
        self.align_btn.setToolTip("Works out the distances on the map and delays the nearer speakers, "
                                  "so the sound of all of them reaches you together")
        self.mirror_btn = QPushButton("Mirror")
        self.mirror_btn.setCheckable(True)
        self.mirror_btn.setToolTip("On: when you move one speaker, its partner on the other side "
                                   "moves the opposite way sideways and the same way front to back")
        self.sync_btn = QPushButton("Easy sync")
        self.sync_btn.setToolTip("Line up the timing of your speakers by ear, two at a time, so every "
                                 "speaker's sound reaches you together")
        self.sync_btn.clicked.connect(lambda: start_easy_sync(self))
        self.play_btn = QPushButton("Test sound")
        self.play_btn.setToolTip("Plays a sound on the selected speaker only. You can also right click "
                                 "a speaker on the map, or select it and press Space.")
        play_menu = QMenu(self.play_btn)
        play_menu.aboutToShow.connect(lambda: fill_sound_menu(play_menu, self.state, self._play_selected))
        fill_sound_menu(play_menu, self.state, self._play_selected)
        self.play_btn.setMenu(play_menu)
        self.metronome_btn = QPushButton("Metronome")
        self.metronome_btn.setCheckable(True)
        self.metronome_btn.setToolTip("Steady clicks on your speakers, to hear whether they play in time "
                                      "with each other. The PC sound waits while it ticks.")
        self.metronome_menu = QMenu(self.metronome_btn)
        self.metronome_menu.aboutToShow.connect(self._fill_metronome_menu)
        self.metronome_btn.setMenu(self.metronome_menu)
        self.levels_btn = QPushButton("Levels")
        self.levels_btn.setCheckable(True)
        self.levels_btn.setChecked(self.state.settings.show_levels)
        self.levels_btn.setToolTip("Show or hide the level meters of the PC sound and every output")
        # the buttons and the lines under them sit centred under the room map. A little
        # less padding than other buttons keeps the row narrow enough for laptop screens.
        for button in (self.assign_btn, self.sync_btn, self.align_btn, self.mirror_btn, self.play_btn,
                       self.metronome_btn, self.levels_btn):
            button.setObjectName("mapRow")
        row.addStretch(1)
        row.addWidget(self.assign_btn)
        row.addWidget(self.sync_btn)
        row.addWidget(self.align_btn)
        row.addWidget(self.mirror_btn)
        row.addWidget(self.play_btn)
        row.addWidget(self.metronome_btn)
        row.addWidget(self.levels_btn)
        row.addStretch(1)
        col.addLayout(row)
        self.test_text = dim("")
        self.test_text.setAlignment(Qt.AlignCenter)
        self.test_text.setVisible(False)
        col.addWidget(self.test_text)
        self.coverage = dim("")
        self.coverage.setAlignment(Qt.AlignCenter)
        col.addWidget(self.coverage)
        self.assign_btn.clicked.connect(self._auto_assign)
        self.align_btn.clicked.connect(self._auto_align)
        self.mirror_btn.toggled.connect(self._mirror_toggled)
        self.levels_btn.toggled.connect(self._levels_toggled)
        return box

    # ------------------------------------------------------------ metronome
    METRONOME_MODES = (("together", "Every speaker together"),
                       ("turns", "One speaker after another"),
                       ("selected", "Selected speaker only"))

    def _fill_metronome_menu(self) -> None:
        menu, state = self.metronome_menu, self.state
        menu.clear()
        on = state.engine.metronome_on
        if on:
            menu.addAction("Stop the metronome", state.stop_metronome)
            menu.addSeparator()
        for mode, text in self.METRONOME_MODES:
            action = menu.addAction(text, lambda m=mode: state.start_metronome(mode=m))
            action.setCheckable(True)
            action.setChecked(on and state.settings.metronome_mode == mode)
        menu.addSeparator()
        tempo = QWidget()
        row = QHBoxLayout(tempo)
        row.setContentsMargins(18, 4, 12, 4)
        row.addWidget(QLabel("Tempo"))
        self.metronome_bpm = QSpinBox()
        self.metronome_bpm.setRange(30, 240)
        self.metronome_bpm.setSingleStep(10)
        self.metronome_bpm.setSuffix(" BPM")
        self.metronome_bpm.setValue(state.settings.metronome_bpm)
        self.metronome_bpm.valueChanged.connect(self._metronome_tempo)
        row.addWidget(self.metronome_bpm)
        holder = QWidgetAction(menu)
        holder.setDefaultWidget(tempo)
        menu.addAction(holder)

    def _metronome_tempo(self, bpm: int) -> None:
        state = self.state
        state.settings.metronome_bpm = int(bpm)
        if state.engine.metronome_on:
            state.start_metronome()
        else:
            state.save_settings()

    def _metronome_changed(self) -> None:
        on = self.state.engine.metronome_on
        self.metronome_btn.blockSignals(True)
        self.metronome_btn.setChecked(on)
        self.metronome_btn.blockSignals(False)
        self.metronome_btn.setToolTip(f"Ticking at {self.state.settings.metronome_bpm} BPM. Open it to stop it or change it." if on else
                                      "Steady clicks on your speakers, to hear whether they play in time "
                                      "with each other. The PC sound waits while it ticks.")

    def metronome_text(self) -> str:
        """What to listen for, under the map while it ticks."""
        s = self.state.settings
        if self.state._clicks_fixed:
            return "Easy sync: the two speakers in its window are clicking."
        if s.metronome_mode == "turns":
            return ("Metronome: the click walks round your speakers from front left (the higher click), "
                    "then the subwoofers. In time, the clicks are perfectly even. One that comes early or "
                    "late belongs to a speaker that needs more or less Delay on the Speaker tab.")
        if s.metronome_mode == "selected":
            dev, spk = self.state.project.find_speaker(self.state.sel_spk)
            name = f"{spk.name} of {dev.title}" if spk is not None else "the selected speaker"
            return f"Metronome: only {name} clicks."
        return ("Metronome: every speaker clicks at once. In time, each click sounds like one, from the "
                "middle. A doubled or smeared click means a speaker is early or late: select it and "
                "change its Delay on the Speaker tab.")

    def _levels_toggled(self, on: bool) -> None:
        self.levels.setVisible(on)
        if self.state.settings.show_levels != on:
            self.state.settings.show_levels = on
            self.state.save_settings()

    # ------------------------------------------------------------ startup
    def _startup(self) -> None:
        state = self.state
        state.scan_devices()
        self._output_count = backend.output_count_hint()
        if state.project.rgb_enabled:
            state.rgb.connect()
            self.lights_panel.refresh_status()
        # the sound simply runs while SpeakerWeave is open (and Windows plays into it)
        if state.settings.start_sound and any(d.enabled for d in state.project.devices):
            state.start()
        else:
            problem = state.prepare_source()[1]
            if problem:
                self.statusBar().showMessage(problem, 12000)
        self.settings_page.refresh_output()
        if state.settings.check_updates and updates.configured():
            QTimer.singleShot(4000, lambda: self.updater.check(manual=False))
        self.apply_hotkeys()
        self.apply_remote()
        self.apply_pads()
        self.controls_page.load()
        if not state.settings.tour_done:
            QTimer.singleShot(800, self._first_tour)

    # ------------------------------------------------------------ tour
    def _first_tour(self) -> None:
        if self.isVisible() and not self.isMinimized():
            self.start_tour()
        else:
            self._tour_waiting = True           # opened in the tray: wait until the window shows

    def start_tour(self) -> None:
        if getattr(self, "_tour", None) is not None:
            return
        self._tour_waiting = False
        if not self.isVisible() or self.isMinimized():
            self.bring_to_front()
        self._tour = Tour(self, window_steps(self))
        self._tour.finished.connect(self._tour_finished)

    def _tour_finished(self, _completed: bool) -> None:
        self._tour = None
        self.show_page(0)
        self.tabs.setCurrentWidget(self.speaker_panel)
        if not self.state.settings.tour_done:
            self.state.settings.tour_done = True
            self.state.save_settings()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._found_queue and self._found_note is None:
            QTimer.singleShot(400, self._show_found_note)
        waiting = getattr(self, "_update_waiting", None)
        if waiting is not None:
            self._update_waiting = None
            QTimer.singleShot(700, lambda: self.show_update_note(waiting))
        if getattr(self, "_tour_waiting", False):
            self._tour_waiting = False
            QTimer.singleShot(600, self.start_tour)

    # ------------------------------------------------------------ pages, tray, controls
    def show_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        note = getattr(self, "_update_note", None)
        if index == 3 and note is not None:         # the notice is right there now
            note.hide()
            note.deleteLater()
            self._update_note = None
        button = self.nav.button(index)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def _build_tray(self) -> None:
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(theme.app_icon(), self)
        self.tray.setToolTip("SpeakerWeave")
        menu = QMenu()
        menu.addAction("Show SpeakerWeave", self.bring_to_front)
        self.tray_sound = menu.addAction("Start the sound", lambda: self.actions.run("toggle_sound"))
        self.tray_mute = menu.addAction("Mute", lambda: self.actions.run("mute"))
        menu.addSeparator()
        menu.addAction("Quit SpeakerWeave", self.quit_app)
        self.tray.setContextMenu(menu)
        self._tray_menu = menu
        self.tray.activated.connect(self._tray_clicked)
        self.tray.show()

    def _tray_clicked(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.toggle_visible()

    def bring_to_front(self) -> None:
        # back from the tray or the taskbar, keeping a maximised window maximised
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.show()
        self.raise_()
        self.activateWindow()

    def toggle_visible(self) -> None:
        if self.isVisible() and not self.isMinimized():
            if self.tray is not None:
                self.hide()
            else:
                self.showMinimized()
        else:
            self.bring_to_front()

    def quit_app(self) -> None:
        self._quitting = True
        self.close()
        QApplication.quit()

    def apply_hotkeys(self) -> list:
        return self.hotkeys.apply(key_bindings(self.state.settings.bindings))

    def apply_remote(self) -> None:
        s = self.state.settings
        self.remote.stop()
        self.remote.port, self.remote.token = int(s.remote_port), s.remote_token
        if s.remote_enabled or s.simhub_link:
            self.remote.start()

    def apply_pads(self) -> None:
        if self.state.settings.controllers_enabled:
            if self.pads.start():
                self._pad_timer.start(20)
        else:
            self._pad_timer.stop()
            self.pads.stop()

    def _poll_pads(self) -> None:
        if self.controls_page.capturing:
            return                      # the capture dialog reads the buttons itself
        bindings = self.state.settings.bindings
        for event in self.pads.poll():
            for action in actions_for_pad(bindings, event.guid, event.input):
                self.actions.run(action)

    def _watch_outputs(self) -> None:
        """Notices sound outputs being plugged in or removed."""
        if not self.state.settings.watch_devices:
            return
        count = backend.output_count_hint()
        if count is None or count == self._output_count:
            return
        self._output_count = count
        if self.state.runner.running:
            # the sound keeps playing: Windows' own list tells whether a hidden output is back
            if windefault.supported():
                try:
                    self._check_hidden_found([name for _id, name in windefault.list_outputs()])
                except Exception:
                    pass
            self.state.notice.emit("Sound outputs were plugged in or removed. Press Rescan to see them "
                                   "(the sound pauses for a moment).")
            return
        before = set(self.state.new_outputs)
        self.state.scan_devices()
        added = sorted(self.state.new_outputs - before)
        if added:
            parts = []
            for name in added:
                entry = speaker_library.recognise(name)
                parts.append(f"{name} (recognised as {entry.name})" if entry and entry.category not in
                             ("interface", "virtual") else name)
            self.state.notice.emit("New sound output: " + "; ".join(parts) + ". Tick it to use it.")

    def _play_selected(self, kind: str) -> None:
        if self.state.sel_spk:
            self.state.identify(self.state.sel_spk, kind)
        else:
            self.state.notice.emit("Select a speaker on the map first.")

    def _load_master(self) -> None:
        p = self.state.project
        self.master.blockSignals(True)
        self.master.setValue(round(p.master_db))
        self.master.blockSignals(False)
        windows = self.state.windows_volume_text()
        if p.muted:
            text = "Muted"
        elif windows == "Windows muted":
            text = "Windows mute"
        else:
            text = f"{p.master_db:+.0f} dB"
        self.master_text.setText(text)
        tip = "SpeakerWeave's own volume, for every speaker."
        if self.state.windows_volume_device():
            tip += (f" Your speakers also follow the Windows volume of "
                    f"{self.state.windows_volume_device()}" + (f", now {windows}." if windows else ", now full."))
        self.master.setToolTip(tip)
        self.master_text.setToolTip(tip)
        if self.tray is not None:
            self.tray_mute.setText("Unmute" if p.muted else "Mute")

    def _windows_volume_changed(self) -> None:
        self._load_master()
        text = self.state.windows_volume_text()
        if text != getattr(self, "_last_windows_text", ""):
            if self.state.winvol.following:
                self.statusBar().showMessage((text or "Windows 100%").replace("Windows", "Windows volume")
                                             + ", your speakers follow it", 2500)
            self._last_windows_text = text

    def _load_top(self) -> None:
        self._show_mode()
        self._load_master()
        self._load_top_light()
        self._load_inputs()

    def _load_inputs(self) -> None:
        p = self.state.project
        self.input.clear()
        found = -1
        for text, kind, name in self.state.input_choices():
            self.input.addItem(text, (kind, name))
            if (kind, name) == (p.input_kind, p.input_name) or (kind == "test" == p.input_kind):
                found = self.input.count() - 1
        if found < 0:
            self.input.addItem(f"Not connected: {p.input_name}", (p.input_kind, p.input_name))
            found = self.input.count() - 1
        self.input.setCurrentIndex(found)

    def _devices_scanned(self) -> None:
        self._follow_channel_changes()
        self._load_inputs()
        self._rebuild_tree()
        if not self.state.scan_error:
            self._check_hidden_found([o.name for o in self.state.outputs])
        if self.state.scan_error:
            self._show_problems([self.state.scan_error])

    def _follow_channel_changes(self) -> None:
        """An output now offers more channels than the setup has speakers for it
        (for example its Windows setting went from stereo to 5.1): the new
        speakers are added, and a surround system gets its surround shape."""
        state = self.state
        offered = {o.name: o.outputs for o in state.outputs}
        changed = []
        for dev in state.project.devices:
            n = offered.get(dev.name, 0)
            if n > dev.channels and state.project.set_device_channels(dev, n):
                changed.append(dev)
                if state.project.fit_mode_to(dev):
                    self._show_mode()
        if changed:
            names = ", ".join(f"{d.title} ({d.channels} channels)" for d in changed)
            state.notice.emit(f"More speakers found: {names}. They were added to the map.")
            QTimer.singleShot(0, state.touch_streams)

    # ------------------------------------------------------------ top bar actions
    def _toggle_running(self) -> None:
        if self.state.runner.running:
            self.state.stop()
        else:
            if not any(d.enabled for d in self.state.project.devices):
                self._show_problems(["Tick at least one sound output in the list on the left first."])
                self._running_changed()
                return
            self.state.start()

    def _running_changed(self) -> None:
        running = self.state.runner.running
        self.start_btn.setChecked(running)
        self.start_btn.setText("Stop" if running else "Start")
        if self.tray is not None:
            self.tray_sound.setText("Stop the sound" if running else "Start the sound")
            self.tray.setToolTip("SpeakerWeave: " + ("playing" if running else "stopped"))

    def _show_problems(self, problems: list) -> None:
        # outputs that are simply switched off are listed on the Errors page only
        serious = [p for p in problems if "not connected right now" not in p]
        if serious:
            serious.append("Open the Errors page for what to do.")
        self.banner.setText("\n".join(serious))
        self.banner.setVisible(bool(serious))

    def _errors_counted(self, errors: int, warnings: int, notices: int = 0) -> None:
        self.errors_btn.setText(badge_text(errors, warnings, notices))
        self.errors_btn.setStyleSheet(badge_style(errors, warnings, notices))

    # ------------------------------------------------------------ updates
    UPDATE_CHECK_MS = 6 * 60 * 60 * 1000    # SpeakerWeave may run in the tray for days

    def _check_updates_now(self) -> None:
        if self.state.settings.check_updates and updates.configured():
            self.updater.check(manual=False)

    def show_update_note(self, info) -> None:
        """A newer version was found in the background. The Errors page lists it as a
        notice. The note by the Errors button shows once per version, until Later."""
        version = info.version.lstrip("vV")
        if self.state.settings.update_note_seen == version:
            return
        if not self.isVisible() or self.isMinimized():
            if self.tray is not None:
                self.tray.showMessage(f"SpeakerWeave {version} is available",
                                      "Open SpeakerWeave to download and install it.",
                                      QSystemTrayIcon.Information, 8000)
            self._update_waiting = info          # shown when the window opens
            return
        if getattr(self, "_update_note", None) is not None:
            return
        note = UpdateNote(self, version_name(info.version), bool(info.url) and paths.is_built())
        note.chosen.connect(lambda what, i=info: self._update_choice(i, what))
        note.place_under(self.errors_btn)
        self._update_note = note

    def _update_choice(self, info, what: str) -> None:
        self._update_note = None
        if what == "install":
            self.updater.install(info)
        elif what == "details":
            self.show_page(3)
        else:
            self.state.settings.update_note_seen = info.version.lstrip("vV")
            self.state.save_settings()

    def _show_mode(self) -> None:
        """Selects the current mode in the list. The Custom entry shows what it holds."""
        p = self.state.project
        custom_index = self.mode.count() - 1
        self.mode.setItemText(custom_index, p.mode_text() if p.mode == CUSTOM else "Custom...")
        self.mode.setToolTip(f"{p.mode_text()}\n\nWhich speaker positions your room has. 4.0, 4.1, "
                             f"5.0 and 5.1 come with the surround pair beside you (side) or behind "
                             f"you (rear). Custom lets you tick any combination.")
        self.mode.view().setMinimumWidth(self.mode.view().sizeHintForColumn(0) + 40)
        if p.mode == CUSTOM:
            index = custom_index
        else:
            rear = p.surround_rear and p.mode in SURROUND_SWITCHABLE
            index = self.mode.findData(p.mode + (" rear" if rear else ""))
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(max(0, index))
        self.mode.blockSignals(False)

    def _open_positions(self) -> None:
        dialog = PositionsDialog(self, self.state.project)
        if dialog.exec() == PositionsDialog.Accepted:
            self.apply_positions(dialog.roles())
        else:
            self._show_mode()

    def apply_positions(self, roles: list) -> None:
        p = self.state.project
        match = standard_mode_for(roles)
        if match:
            p.set_mode(match[0], rear=match[1])
        else:
            p.set_mode(CUSTOM, custom=roles)
        self.state.touch_routing()
        self._show_mode()
        self.state.notice.emit(f"Speaker positions: {p.mode_text()}")

    def _mode_changed(self, _i: int) -> None:
        mode, _, rear = self.mode.currentData().partition(" ")
        rear = rear == "rear"
        if mode == CUSTOM:
            self._open_positions()
            return
        self.state.project.set_mode(mode, rear=rear)
        self.state.touch_routing()
        for _dev, spk in self.state.project.all_speakers():
            self.state.engine.update_speaker(spk.id)

    def _input_changed(self, _i: int) -> None:
        kind, name = self.input.currentData()
        p = self.state.project
        p.input_kind, p.input_name = kind, name
        self.state.touch_streams()        # a running sound restarts and points Windows at it

    def _master_changed(self, value: int) -> None:
        self.state.set_master(float(value))

    def _new_setup(self) -> None:
        answer = QMessageBox.question(self, "New setup", "Start again with an empty setup?")
        if answer == QMessageBox.Yes:
            self.state.replace_project(Project())
            self._load_top()

    def _open_setup(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open a setup", "", "SpeakerWeave setup (*.json)")
        if not path:
            return
        try:
            project = Project.load(path)
        except Exception as exc:
            QMessageBox.warning(self, "Open a setup", f"That file could not be read.\n\n{exc}")
            return
        self.state.replace_project(project)
        self._load_top()

    def _save_setup(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save this setup", "My speakers.json",
                                              "SpeakerWeave setup (*.json)")
        if not path:
            return
        try:
            self.state.project.save(path)
            self.statusBar().showMessage(f"Saved to {path}", 5000)
        except Exception as exc:
            QMessageBox.warning(self, "Save this setup", f"Could not save.\n\n{exc}")

    def _open_guide(self) -> None:
        for name in ("Guide.html", "README.md"):
            guide = paths.resource(name)
            if os.path.exists(guide):
                QDesktopServices.openUrl(QUrl.fromLocalFile(guide))
                return

    def _about(self) -> None:
        QMessageBox.about(self, "About SpeakerWeave", about_text())

    # ------------------------------------------------------------ map actions
    def _mirror_toggled(self, on: bool) -> None:
        if self.state.project.mirror != on:
            self.state.project.mirror = on
            self.state.touch_layout()       # the panels show what Mirror will do

    def _auto_assign(self) -> None:
        changed = auto_assign_roles(self.state.project)
        self.state.touch_routing()
        self.statusBar().showMessage(
            f"Roles set from the map ({changed} changed). Speakers labelled subwoofer were kept.", 6000)

    def _auto_align(self) -> None:
        auto_align_delays(self.state.project)
        self.state.touch_routing()
        self.statusBar().showMessage(
            "Delays set from the distances on the map. Use Extra delay on the Output tab "
            "for the lag inside each TV.", 8000)

    # ------------------------------------------------------------ device tree
    def _structure_changed(self) -> None:
        self._load_top_light()
        if not self._tree_pending:
            self._tree_pending = True
            QTimer.singleShot(0, self._rebuild_tree)

    def _load_top_light(self) -> None:
        p = self.state.project
        self._show_mode()
        if self.mirror_btn.isChecked() != p.mirror:
            self.mirror_btn.setChecked(p.mirror)

    def theme_changed(self) -> None:
        """A new colour theme was applied: redraw everything painted by hand."""
        self._rebuild_tree()
        self.map.update()
        for page in (self.speaker_panel, self.device_panel, self.sound_panel, self.lights_panel):
            page.update()
            for child in page.findChildren(QWidget):
                child.update()

    def _rebuild_tree(self) -> None:
        self._tree_pending = False
        self._tree_loading = True
        state = self.state
        proj = state.project
        self.tree.clear()
        connected = {o.name: o for o in state.outputs}
        used = set()
        for dev in proj.devices:
            used.add(dev.name)
            text = dev.title
            if state.outputs and dev.name not in connected:
                text += "   (not connected)"
            item = QTreeWidgetItem([text])
            item.setData(0, ROLE_KEY, ("dev", dev.id, ""))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if dev.enabled else Qt.Unchecked)
            item.setToolTip(0, dev.name)
            self.tree.addTopLevelItem(item)
            for spk in dev.speakers:
                child = QTreeWidgetItem([f"{spk.name}:  {ROLE_NAMES.get(spk.role, spk.role)}"])
                child.setIcon(0, chip(ROLE_COLORS.get(spk.role, theme.DIM)))
                child.setData(0, ROLE_KEY, ("spk", dev.id, spk.id))
                if spk.role == OFF or spk.mute:
                    child.setForeground(0, QColor(theme.DIM))
                item.addChild(child)
            item.setExpanded(True)
        hidden_names = state.settings.hidden_outputs
        spare = [o for o in state.outputs if o.name not in used and o.name not in hidden_names]
        if spare:
            head = QTreeWidgetItem(["Other outputs on this PC"])
            head.setFlags(Qt.ItemIsEnabled)
            head.setForeground(0, QColor(theme.DIM))
            self.tree.addTopLevelItem(head)
            for out in spare:
                entry = speaker_library.recognise(out.name)
                text = out.name
                tip = f"{out.outputs} channels"
                if out.name in state.new_outputs:
                    text = "NEW  " + text
                    tip += ". Plugged in since SpeakerWeave started"
                if entry is not None and entry.category == "virtual":
                    tip += ". A virtual sound device: choose it under Listen to instead"
                elif entry is not None and entry.category not in ("interface",):
                    tip += f". Recognised as {entry.name}, its preset is filled in when you tick it"
                item = QTreeWidgetItem([text])
                item.setData(0, ROLE_KEY, ("new", out.name, out.outputs))
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Unchecked)
                item.setToolTip(0, tip)
                if entry is not None and entry.category == "virtual":
                    item.setForeground(0, QColor(theme.DIM))
                head.addChild(item)
            head.setExpanded(True)
        self._hidden_head = None
        if hidden_names:
            self._add_hidden_folder(hidden_names, [o.name for o in state.outputs])
        self._tree_loading = False
        self._highlight_selection()

    def _tree_item_changed(self, item, _column) -> None:
        if self._tree_loading:
            return
        data = item.data(0, ROLE_KEY)
        if not data:
            return
        state = self.state
        if data[0] == "new" and item.checkState(0) == Qt.Checked:
            self._add_output(data[1], int(data[2]))
        elif data[0] == "dev":
            dev = state.project.find_device(data[1])
            if dev is not None:
                dev.enabled = item.checkState(0) == Qt.Checked
                state.touch_streams()

    def _add_output(self, name: str, channels: int):
        """An output of this PC joins the setup, ticked, with its preset when it is known."""
        state = self.state
        entry = speaker_library.recognise(name)
        if entry is not None and entry.category == "virtual":
            state.notice.emit(f"{name} is a virtual sound device, not a speaker. Choose it "
                              f"under Listen to instead.")
            QTimer.singleShot(0, self._rebuild_tree)
            return None
        dev = state.project.add_device(name, channels)
        short = speaker_library.friendly_name(dev.name)
        if short != dev.name:
            dev.label = short
        if is_shape(dev):
            # a surround system: its shape goes round you, and the mode grows to use it
            if state.project.fit_mode_to(dev):
                self._show_mode()
                state.notice.emit(f"{dev.title} has {dev.channels} channels, so the mode is now "
                                  f"{state.project.mode_text()}.")
        elif state.project.auto_face:
            face_listener(state.project, dev)
        if entry is not None and state.settings.apply_library:
            speaker_library.apply_model(dev, entry)
            if entry.category not in ("interface",):
                state.notice.emit(f"Recognised {dev.name} as {entry.name}. Its preset was filled "
                                  f"in, change it on the Output tab.")
        state.new_outputs.discard(dev.name)
        state.touch_streams()
        state.select(dev.id, "")
        return dev

    def _tree_clicked(self, item, _column) -> None:
        data = item.data(0, ROLE_KEY)
        if not data:
            return
        if data[0] == "dev":
            self.state.select(data[1], "")
        elif data[0] == "spk":
            self.state.select(data[1], data[2])

    def _highlight_selection(self) -> None:
        state = self.state
        self.tree.blockSignals(True)
        target = None
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            data = top.data(0, ROLE_KEY)
            if not data or data[0] != "dev" or data[1] != state.sel_dev:
                continue
            target = top
            for j in range(top.childCount()):
                if top.child(j).data(0, ROLE_KEY)[2] == state.sel_spk and state.sel_spk:
                    target = top.child(j)
        self.tree.setCurrentItem(target)
        self.tree.blockSignals(False)

    # ------------------------------------------------------------ hidden outputs
    HIDDEN_FOLDER = "Hidden by user"

    def _add_hidden_folder(self, entries: dict, present: list) -> None:
        head = QTreeWidgetItem([f"{self.HIDDEN_FOLDER} ({len(entries)})"])
        head.setData(0, ROLE_KEY, ("hiddenfolder", "", ""))
        head.setFlags(Qt.ItemIsEnabled)
        head.setForeground(0, QColor(theme.DIM))
        head.setToolTip(0, "Outputs you hid. Right click one to show it again.")
        self.tree.addTopLevelItem(head)
        for name in sorted(entries, key=str.lower):
            saved = entries[name].get("device") or {}
            text = saved.get("label") or speaker_library.friendly_name(name) or name
            if name in self._found_queue:
                text = "FOUND  " + text
            elif not hidden.connected(name, present):
                text += "   (not connected)"
            item = QTreeWidgetItem([text])
            item.setData(0, ROLE_KEY, ("hidden", name, ""))
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            item.setForeground(0, QColor(theme.TEXT if name in self._found_queue else theme.DIM))
            item.setToolTip(0, f"{name}\nHidden by you. Right click to show it again.")
            head.addChild(item)
        head.setExpanded(self._hidden_open or bool(self._found_queue))
        self._hidden_head = head
        self._apply_flash()

    def _folder_toggled(self, item, opened: bool) -> None:
        data = item.data(0, ROLE_KEY)
        if data and data[0] == "hiddenfolder" and not self._tree_loading:
            self._hidden_open = opened

    def _tree_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        data = item.data(0, ROLE_KEY) if item is not None else None
        if not data:
            return
        menu = QMenu(self)
        if data[0] in ("dev", "new"):
            name = data[1] if data[0] == "new" else getattr(self.state.project.find_device(data[1]), "name", "")
            if not name:
                return
            menu.addAction("Hide this output", lambda: self.hide_output(name))
        elif data[0] == "hidden":
            name = data[1]
            menu.addAction("Show this output again", lambda: self.unhide_output(name))
            menu.addAction("Activate device", lambda: self.unhide_output(name, activate=True))
        else:
            return
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def hide_output(self, name: str) -> None:
        """Moves an output into "Hidden by user" at the bottom of the list."""
        state = self.state
        dev = next((d for d in state.project.devices if d.name == name), None)
        title = dev.title if dev is not None else name
        if dev is not None and state.sel_dev == dev.id:
            state.select("", "")
        hidden.hide(state.settings, state.project, name, [o.name for o in state.outputs])
        state.save_settings()
        state.touch_streams()
        state.notice.emit(f"{title} is now under {self.HIDDEN_FOLDER} at the bottom of the list. "
                          f"Right click it there to show it again.")

    def unhide_output(self, name: str, activate: bool = False):
        """Takes an output out of "Hidden by user". Activated, it is ticked so it plays."""
        state = self.state
        if activate and not hidden.connected(name, [o.name for o in state.outputs]):
            state.scan_devices()                # it was plugged in while the sound ran
        self._found_queue = [n for n in self._found_queue if n != name]
        dev = hidden.unhide(state.settings, state.project, name, activate)
        state.save_settings()
        if dev is None and activate:
            out = next((o for o in state.outputs if hidden.same_output(o.name, name)), None)
            if out is not None:
                dev = self._add_output(out.name, int(out.outputs))
        state.touch_streams()
        if dev is not None:
            state.select(dev.id, "")
        self._rebuild_tree()
        if not self._found_queue:
            self._flash_timer.stop()
        return dev

    def _check_hidden_found(self, present: list) -> None:
        """A hidden output was plugged in again: flash its folder and say so."""
        settings = self.state.settings
        if not settings.hidden_outputs:
            return
        before = {name: entry.get("seen") for name, entry in settings.hidden_outputs.items()}
        found = hidden.found_again(settings, present)
        if any(entry.get("seen") != before.get(name) for name, entry in settings.hidden_outputs.items()):
            self.state.save_settings()
        new = [name for name in found if name not in self._found_queue]
        if not new:
            return
        self._found_queue += new
        self._flash_timer.start()
        self._rebuild_tree()
        if not self.isVisible() or self.isMinimized():
            if self.tray is not None:
                self.tray.showMessage("SpeakerWeave: a hidden output is back",
                                      f"{new[0]} has been found again. Open SpeakerWeave to use it.",
                                      QSystemTrayIcon.Information, 6000)
            return                                  # the note waits until the window shows
        QTimer.singleShot(0, self._show_found_note)

    def _show_found_note(self) -> None:
        if self._found_note is not None or not self._found_queue:
            return
        if not self.isVisible() or self.isMinimized():
            return
        name = self._found_queue[0]
        self.show_page(0)
        self._rebuild_tree()
        head = self._hidden_head
        if head is None:
            self._found_queue.pop(0)
            return
        target = head
        for i in range(head.childCount()):
            if head.child(i).data(0, ROLE_KEY)[1] == name:
                target = head.child(i)
        self.tree.scrollToItem(target)
        rect = self.tree.visualItemRect(target)
        y = self.tree.viewport().mapTo(self, rect.center()).y()
        x = self.tree.mapTo(self, QPoint(self.tree.width(), 0)).x()
        saved = self.state.settings.hidden_outputs.get(name, {}).get("device") or {}
        title = saved.get("label") or speaker_library.friendly_name(name) or name
        note = FoundAgainNote(self, name, title)
        note.chosen.connect(self._found_choice)
        note.point_at(QPoint(x, y))
        self._found_note = note

    def _found_choice(self, name: str, what: str) -> None:
        self._found_note = None
        settings = self.state.settings
        self._found_queue = [n for n in self._found_queue if n != name]
        if what == ACTIVATE:
            dev = self.unhide_output(name, activate=True)
            if dev is not None:
                self.state.notice.emit(f"{dev.title} is back in the list and ticked.")
        elif what == IGNORE_ALWAYS:
            entry = settings.hidden_outputs.get(name)
            if entry is not None:
                entry["quiet"] = True
                self.state.save_settings()
        if not self._found_queue:
            self._flash_timer.stop()
            self._flash_on = False
        self._rebuild_tree()
        if self._found_queue:
            QTimer.singleShot(200, self._show_found_note)

    def _flash_hidden(self) -> None:
        self._flash_on = not self._flash_on and bool(self._found_queue)
        if not self._found_queue:
            self._flash_timer.stop()
        self._apply_flash()

    def _apply_flash(self) -> None:
        head = self._hidden_head
        if head is None:
            return
        try:
            if self._flash_on:
                color = QColor(theme.ACCENT)
                color.setAlpha(150)
                head.setBackground(0, color)
                head.setForeground(0, QColor(theme.TEXT))
            else:
                head.setBackground(0, QColor(0, 0, 0, 0))
                head.setForeground(0, QColor(theme.TEXT if self._found_queue else theme.DIM))
        except RuntimeError:                        # the list was just rebuilt
            self._hidden_head = None

    def _selection_changed(self) -> None:
        self._highlight_selection()
        # Speaker and Output follow what was clicked. Sound, Lights and Effects are not
        # about one speaker, so whoever is working there stays there.
        if self.tabs.currentWidget() not in (self.speaker_panel, self.device_panel):
            return
        if self.state.sel_spk:
            self.tabs.setCurrentWidget(self.speaker_panel)
        elif self.state.sel_dev:
            self.tabs.setCurrentWidget(self.device_panel)

    # ------------------------------------------------------------ timers
    def _tick_meters(self) -> None:
        state = self.state
        now = time.monotonic()
        if not state.runner.running:
            if self.map.levels or self.map.test_role:
                self.map.levels, self.map.clipped, self.map.test_role = {}, set(), ""
                self.test_text.setText("")
                self.test_text.setVisible(False)
                self.map.update()
            return
        eng = state.engine
        if eng.block_count != self._last_blocks:
            self._last_blocks, self._last_block_time = eng.block_count, now
        flowing = now - self._last_block_time < 0.3
        levels = {}
        for spk_id, chain in list(eng.chains.items()):
            levels[spk_id] = level_to_unit(chain.peak) if flowing else 0.0
            if chain.clipped:
                chain.clipped = False
                self._clip_until[spk_id] = now + 1.2
        self.map.levels = levels if state.settings.show_meters else {}
        self.map.clipped = {k for k, t in self._clip_until.items() if t > now}
        role = state.runner.test_role if state.project.input_kind == "test" else ""
        self.map.test_role = role
        if eng.metronome_on:
            text = self.metronome_text()
        else:
            text = f"Test signal now on: {ROLE_NAMES.get(role, role)}" if role else ""
        if self.test_text.text() != text:
            self.test_text.setText(text)
        self.test_text.setVisible(bool(text))
        self.map.update()

    def _tick_status(self) -> None:
        state = self.state
        self.sound_panel.refresh_status()
        if state.rgb.error and not state.rgb.connected:
            self.lights_panel.refresh_status()
        missing = state.project.roles_missing() if state.project.devices else []
        if missing:
            names = ", ".join(ROLE_NAMES[r] for r in missing)
            self.coverage.setText(f"No speaker set to: {names}. That sound is shared between "
                                  f"the nearest speakers.")
        else:
            self.coverage.setText("")
        if not state.runner.running:
            self.run_label.setText("Stopped")
            return
        outs = len(state.runner.fifos)
        speakers = sum(1 for d, s in state.project.all_speakers() if d.enabled and s.role != OFF)
        delay = state.runner.delay_ms()
        flowing = time.perf_counter() - state.runner._last_real < 0.5
        note = "" if flowing else "   Nothing is playing into the source right now."
        windows = state.windows_volume_text()
        windows = f"   {windows.replace('Windows', 'Windows volume')}." if windows else ""
        self.run_label.setText(
            f"Running: {outs} outputs, {speakers} speakers, about {delay:.0f} ms behind "
            f"the source plus each device's own lag.{windows}{note}   CPU {self._cpu_percent():.0f}%")

    def _cpu_percent(self) -> float:
        """How much of the whole processor SpeakerWeave uses, averaged since the last look."""
        now, used = time.perf_counter(), time.process_time()
        last = getattr(self, "_cpu_last", None)
        self._cpu_last = (now, used)
        if last is None or now - last[0] <= 0:
            return 0.0
        cores = os.cpu_count() or 1
        value = 100.0 * (used - last[1]) / (now - last[0]) / cores
        self._cpu_smooth = 0.7 * getattr(self, "_cpu_smooth", value) + 0.3 * value
        return max(0.0, self._cpu_smooth)

    def closeEvent(self, ev) -> None:
        s = self.state.settings
        if s.close_to_tray and self.tray is not None and not self._quitting:
            ev.ignore()
            self.hide()
            if not s.tray_hint_shown:
                self.tray.showMessage("SpeakerWeave is still running",
                                      "Your speakers keep playing. Quit from this tray icon.",
                                      QSystemTrayIcon.Information, 5000)
                s.tray_hint_shown = True
                self.state.save_settings()
            return
        self.hotkeys.clear()
        self.simhub.keep_changes()
        self.remote.stop()
        self.pads.stop()
        if self.tray is not None:
            self.tray.hide()
        self.state.shutdown()
        super().closeEvent(ev)
