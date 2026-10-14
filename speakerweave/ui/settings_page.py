"""The Settings page: how the app starts, closes, looks, updates and watches
devices, the user's own test sounds, the About section and uninstalling."""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox, QFileDialog,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)

from .. import __version__, autostart, sounds, updates, windefault
from ..settings import AppSettings
from . import theme
from .panels import dim, scrolled
from .state import config_dir
from .uninstall_dialog import start_uninstall

ADOBE_COLOR = "https://color.adobe.com/create/color-wheel"


def about_text() -> str:
    return (f"SpeakerWeave {__version__}\n\n"
            f"Written by Eli Smart, just as a fun project, because I really wanted to play music "
            f"through lots of speaker outputs at once.\n\n"
            f"One sound source in, many sound outputs out, arranged as one surround system.\n\n"
            f"Lights are driven through OpenRGB. To play the sound of this PC it listens to a "
            f"virtual sound device such as VB-CABLE by VB-Audio. VB-CABLE is a donationware, all "
            f"participations are welcome (vb-audio.com/Cable).")


def swatch_icon(colors: dict, width: int = 70, height: int = 14) -> QIcon:
    """Five little blocks showing a theme's colours."""
    pix = QPixmap(width, height)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    step = width / len(theme.THEME_KEYS)
    for i, key in enumerate(theme.THEME_KEYS):
        p.fillRect(int(i * step), 0, int(step + 1), height, QColor(colors[key]))
    p.end()
    return QIcon(pix)


class SettingsPage(QWidget):
    def __init__(self, state, window):
        super().__init__()
        self.state = state
        self.window = window
        self._loading = False

        inner = QWidget()
        outer_row = QHBoxLayout(inner)
        outer_row.setContentsMargins(16, 16, 16, 16)
        column = QWidget()
        column.setMaximumWidth(760)
        outer_row.addWidget(column, 1)
        outer_row.addStretch(0)
        col = QVBoxLayout(column)
        col.setSpacing(8)
        page = QVBoxLayout(self)
        page.setContentsMargins(0, 0, 0, 0)
        page.addWidget(scrolled(inner))

        title = QLabel("Settings")
        title.setObjectName("title")
        col.addWidget(title)

        box = QGroupBox("Starting")
        v = QVBoxLayout(box)
        self.start_windows = QCheckBox("Start SpeakerWeave when Windows starts")
        self.start_tray = QCheckBox("Start hidden, with only the icon in the system tray")
        self.start_sound = QCheckBox("Start the sound as soon as SpeakerWeave opens")
        for w in (self.start_windows, self.start_tray, self.start_sound):
            v.addWidget(w)
        self.windows_hint = dim("")
        v.addWidget(self.windows_hint)
        col.addWidget(box)

        box = QGroupBox("Windows sound output")
        v = QVBoxLayout(box)
        self.default_output = QCheckBox("Make SpeakerWeave the main sound output of Windows")
        v.addWidget(self.default_output)
        v.addWidget(dim("While SpeakerWeave plays, Windows plays into the device SpeakerWeave listens "
                        "to (for example CABLE Input), so everything the PC plays comes out of your "
                        "speakers. With the sound starting when SpeakerWeave opens, and SpeakerWeave "
                        "starting with Windows, this happens every time the PC starts. If Listen to "
                        "is on the test signal, a virtual sound device is picked for you."))
        self.restore_output = QCheckBox("When the sound stops or SpeakerWeave quits, switch Windows "
                                        "back to the output it used before")
        v.addWidget(self.restore_output)
        self.auto_surround = QCheckBox("Set the virtual device to 7.1, so games send real surround "
                                       "sound")
        self.auto_surround.setToolTip("Stereo music and video is still spread over every speaker")
        v.addWidget(self.auto_surround)
        self.follow_volume = QCheckBox("Follow the Windows volume and mute (volume keys, mouse wheel, "
                                       "headset buttons)")
        self.follow_volume.setToolTip("The volume Windows shows for the device SpeakerWeave listens to "
                                      "sets how loud your speakers play, on top of SpeakerWeave's own "
                                      "volume. Switch it off if a volume change is heard twice.")
        v.addWidget(self.follow_volume)
        self.output_state = dim("")
        v.addWidget(self.output_state)
        row = QHBoxLayout()
        self.output_now = QPushButton("Set it now")
        self.output_now.setToolTip("Starts the sound and makes the device SpeakerWeave listens to the "
                                   "Windows default output")
        self.boot_btn = QPushButton("Also start SpeakerWeave with Windows")
        row.addWidget(self.output_now)
        row.addWidget(self.boot_btn)
        row.addStretch(1)
        v.addLayout(row)
        col.addWidget(box)

        box = QGroupBox("Closing")
        v = QVBoxLayout(box)
        self.close_tray = QCheckBox("Closing the window keeps SpeakerWeave running in the system tray")
        v.addWidget(self.close_tray)
        v.addWidget(dim("Your speakers only play while SpeakerWeave runs. With this on, the close "
                        "button hides the window and the sound carries on. Quit from the tray icon."))
        col.addWidget(box)

        box = QGroupBox("Sound outputs")
        v = QVBoxLayout(box)
        self.watch = QCheckBox("Notice when sound outputs are plugged in or removed")
        self.library = QCheckBox("Fill in matching presets when a recognised output is added")
        v.addWidget(self.watch)
        v.addWidget(self.library)
        v.addWidget(dim("SpeakerWeave knows many common TVs, monitors, speaker systems, headsets and "
                        "sound cards by the name Windows gives them. Speakers on an ordinary audio "
                        "jack can be picked on the Output tab."))
        col.addWidget(box)

        box = QGroupBox("Room map")
        v = QVBoxLayout(box)
        self.meters = QCheckBox("Show how loud each speaker is playing on the map")
        v.addWidget(self.meters)
        col.addWidget(box)

        col.addWidget(self._build_look())
        col.addWidget(self._build_sounds())

        box = QGroupBox("Updates")
        v = QVBoxLayout(box)
        self.updates_box = QCheckBox("Look for a newer version when SpeakerWeave opens")
        v.addWidget(self.updates_box)
        row = QHBoxLayout()
        self.version = QLabel(f"You have version {__version__}.")
        self.check_now = QPushButton("Check now")
        row.addWidget(self.version)
        row.addStretch(1)
        row.addWidget(self.check_now)
        v.addLayout(row)
        if not updates.configured():
            v.addWidget(dim("This copy has no update address yet (see RELEASING.md)."))
        col.addWidget(box)

        box = QGroupBox("Your data")
        v = QVBoxLayout(box)
        v.addWidget(dim("Your speaker setup, these settings and the error log are kept in one folder."))
        row = QHBoxLayout()
        self.open_folder = QPushButton("Open that folder")
        self.reset = QPushButton("Reset these settings")
        row.addWidget(self.open_folder)
        row.addWidget(self.reset)
        row.addStretch(1)
        v.addLayout(row)
        col.addWidget(box)

        box = QGroupBox("About")
        v = QVBoxLayout(box)
        about = QLabel(about_text())
        about.setWordWrap(True)
        about.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(about)
        col.addWidget(box)

        box = QGroupBox("Uninstall")
        v = QVBoxLayout(box)
        v.addWidget(dim("Removes SpeakerWeave from this PC: the program, its shortcuts, its start with "
                        "Windows entry and its SimHub plugin, and if you choose, your settings and "
                        "setups too. Windows gets a normal sound output back first."))
        row = QHBoxLayout()
        self.uninstall_btn = QPushButton("Uninstall SpeakerWeave...")
        self.uninstall_btn.setObjectName("danger")
        row.addWidget(self.uninstall_btn)
        row.addStretch(1)
        v.addLayout(row)
        col.addWidget(box)
        col.addStretch(1)

        self.start_windows.toggled.connect(self._windows_toggled)
        self.start_tray.toggled.connect(lambda v: self._set("start_in_tray", v))
        self.start_sound.toggled.connect(lambda v: self._set("start_sound", v))
        self.close_tray.toggled.connect(lambda v: self._set("close_to_tray", v))
        self.watch.toggled.connect(lambda v: self._set("watch_devices", v))
        self.library.toggled.connect(lambda v: self._set("apply_library", v))
        self.meters.toggled.connect(self._meters_toggled)
        self.updates_box.toggled.connect(lambda v: self._set("check_updates", v))
        self.check_now.clicked.connect(lambda: window.updater.check(manual=True))
        self.open_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(config_dir())))
        self.reset.clicked.connect(self._reset)
        self.uninstall_btn.clicked.connect(lambda: start_uninstall(self.window))
        self.default_output.toggled.connect(self._default_output_toggled)
        self.restore_output.toggled.connect(lambda v: self._set("restore_output", v))
        self.auto_surround.toggled.connect(lambda v: self._set("auto_surround", v))
        self.follow_volume.toggled.connect(self._follow_volume_toggled)
        self.output_now.clicked.connect(lambda: self._make_default(show=True))
        self.boot_btn.clicked.connect(lambda: self.start_windows.setChecked(True))
        self.load()

    # ------------------------------------------------------------ look
    def _build_look(self) -> QGroupBox:
        box = QGroupBox("Look")
        v = QVBoxLayout(box)
        row = QHBoxLayout()
        row.addWidget(QLabel("Colours"))
        self.theme_box = QComboBox()
        for key, (name, note, colors) in theme.PRESETS.items():
            self.theme_box.addItem(swatch_icon(colors), f"{name}: {note}", key)
        self.theme_box.addItem("Your own colours", theme.CUSTOM)
        self.theme_box.setIconSize(self.theme_box.iconSize().expandedTo(swatch_icon(
            theme.PRESETS[theme.DEFAULT_THEME][2]).availableSizes()[0]))
        row.addWidget(self.theme_box, 1)
        v.addLayout(row)
        v.addWidget(dim("The presets were picked with the colour harmony rules of Adobe Color. "
                        "Choose Your own colours to make your own, or to bring in a theme from "
                        "Adobe Color."))

        self.custom_box = QWidget()
        c = QVBoxLayout(self.custom_box)
        c.setContentsMargins(0, 6, 0, 0)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        self.color_btns = {}
        for i, key in enumerate(theme.THEME_KEYS):
            button = QPushButton()
            button.setMinimumWidth(130)
            button.clicked.connect(lambda _=False, k=key: self._pick_color(k))
            grid.addWidget(QLabel(theme.THEME_LABELS[key]), i // 3, (i % 3) * 2)
            grid.addWidget(button, i // 3, (i % 3) * 2 + 1)
            self.color_btns[key] = button
        grid.setColumnStretch(6, 1)
        c.addLayout(grid)
        c.addWidget(dim("From Adobe Color: open a theme, copy its five colour codes (the HEX "
                        "values) and paste them here, or load a theme saved as an .ase file."))
        row = QHBoxLayout()
        self.paste = QLineEdit()
        self.paste.setPlaceholderText("#264653  #2A9D8F  #E9C46A  #F4A261  #E76F51")
        self.light_look = QComboBox()
        self.light_look.addItem("Dark look", False)
        self.light_look.addItem("Light look", True)
        self.use_paste = QPushButton("Use these")
        row.addWidget(self.paste, 1)
        row.addWidget(self.light_look)
        row.addWidget(self.use_paste)
        c.addLayout(row)
        row = QHBoxLayout()
        self.load_ase = QPushButton("Load .ase file")
        self.open_adobe = QPushButton("Open Adobe Color")
        row.addWidget(self.load_ase)
        row.addWidget(self.open_adobe)
        row.addStretch(1)
        c.addLayout(row)
        self.contrast_note = dim("")
        c.addWidget(self.contrast_note)
        v.addWidget(self.custom_box)

        self.theme_box.activated.connect(self._theme_chosen)
        self.use_paste.clicked.connect(self._use_paste)
        self.paste.returnPressed.connect(self._use_paste)
        self.load_ase.clicked.connect(self._load_ase)
        self.open_adobe.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(ADOBE_COLOR)))
        return box

    def _load_look(self) -> None:
        s = self.state.settings
        index = self.theme_box.findData(s.theme)
        self.theme_box.setCurrentIndex(index if index >= 0 else 0)
        custom = s.theme == theme.CUSTOM
        self.custom_box.setVisible(custom)
        colors = theme.colors_for(s)
        if s.custom_colors:
            self.theme_box.setItemIcon(self.theme_box.findData(theme.CUSTOM),
                                       swatch_icon(theme.clean_colors(s.custom_colors)))
        for key, button in self.color_btns.items():
            button.setText(colors[key].upper())
            text = "#0b1220" if theme.luminance(colors[key]) > 0.3 else "#ffffff"
            button.setStyleSheet(f"background: {colors[key]}; color: {text}; "
                                 f"border: 1px solid {theme.BORDER}; font-weight: 600;")
        ratio = theme.contrast(colors["text"], colors["panel"])
        self.contrast_note.setText("" if ratio >= 4.5 else
                                   f"Text on the panels may be hard to read (contrast {ratio:.1f} "
                                   f"to 1, 4.5 or more reads comfortably).")
        self.contrast_note.setVisible(ratio < 4.5)

    def apply_theme(self) -> None:
        app = QApplication.instance()
        theme.apply(app, theme.colors_for(self.state.settings))
        self.window.theme_changed()
        self._load_look()

    def _theme_chosen(self, _i: int = 0) -> None:
        s = self.state.settings
        key = self.theme_box.currentData()
        if key == theme.CUSTOM and not s.custom_colors:
            s.custom_colors = dict(theme.colors_for(s))      # start from the look in use
        s.theme = key
        self.state.save_settings()
        self.apply_theme()

    def _set_custom(self, colors: dict) -> None:
        s = self.state.settings
        s.custom_colors = theme.clean_colors(colors)
        s.theme = theme.CUSTOM
        self.state.save_settings()
        self.apply_theme()

    def _pick_color(self, key: str) -> None:
        colors = theme.colors_for(self.state.settings)
        chosen = QColorDialog.getColor(QColor(colors[key]), self, theme.THEME_LABELS[key])
        if chosen.isValid():
            colors[key] = chosen.name()
            self._set_custom(colors)

    def _use_paste(self) -> None:
        codes = theme.parse_hex_list(self.paste.text())
        if not codes:
            QMessageBox.information(self, "Colours", "No colour codes found. Paste codes such as "
                                    "#264653 #2A9D8F #E9C46A #F4A261 #E76F51.")
            return
        self._set_custom(theme.colors_from_swatches(codes, self.light_look.currentData()))

    def _load_ase(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Adobe swatch file", "",
                                              "Adobe swatches (*.ase);;All files (*)")
        if not path:
            return
        try:
            codes = theme.read_ase(path)
            if not codes:
                raise ValueError("There are no colours in this file.")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Colours", f"This file could not be read.\n\n{exc}")
            return
        self.paste.setText("  ".join(code.upper() for code in codes))
        self._set_custom(theme.colors_from_swatches(codes, self.light_look.currentData()))

    # ------------------------------------------------------------ own test sounds
    def _build_sounds(self) -> QGroupBox:
        box = QGroupBox("Your own test sounds")
        v = QVBoxLayout(box)
        v.addWidget(dim(f"Add up to {sounds.MAX_SOUNDS} sounds of your own, such as a voice saying "
                        f"\"left\" or a piece of music. They appear next to the noise and the sweep "
                        f"wherever you can play a test sound. Up to {sounds.MAX_SECONDS:.0f} seconds "
                        f"each. WAV, MP3, M4A, WMA, FLAC and other files Windows can play."))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        self.sound_rows = []
        for slot in range(sounds.MAX_SOUNDS):
            name = QLabel("")
            choose = QPushButton("Choose file")
            play = QPushButton("Play")
            play.setToolTip("Plays it on the speaker selected on the room map")
            remove = QPushButton("Remove")
            choose.clicked.connect(lambda _=False, i=slot: self._choose_sound(i))
            play.clicked.connect(lambda _=False, i=slot: self._play_sound(i))
            remove.clicked.connect(lambda _=False, i=slot: self._remove_sound(i))
            grid.addWidget(QLabel(f"{slot + 1}"), slot, 0)
            grid.addWidget(name, slot, 1)
            grid.addWidget(choose, slot, 2)
            grid.addWidget(play, slot, 3)
            grid.addWidget(remove, slot, 4)
            self.sound_rows.append((name, choose, play, remove))
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)
        return box

    def _load_sounds(self) -> None:
        for slot, (name, choose, play, remove) in enumerate(self.sound_rows):
            entry = self.state.settings.test_sounds[slot]
            if entry:
                name.setText(f"{entry['name']}   ({entry.get('seconds', 0):.1f} s)")
                name.setObjectName("")
            else:
                name.setText("Empty")
                name.setObjectName("dim")
            name.setStyleSheet("")                    # pick up the new object name
            choose.setText("Replace" if entry else "Choose file")
            play.setEnabled(bool(entry))
            remove.setEnabled(bool(entry))

    def _choose_sound(self, slot: int) -> None:
        path, _ = QFileDialog.getOpenFileName(self, f"Test sound {slot + 1}", "", sounds.FILE_FILTER)
        if not path:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            entry, cut = sounds.add(path, slot, config_dir())
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Test sound", f"This file could not be used.\n\n{exc}")
            return
        QApplication.restoreOverrideCursor()
        self.state.settings.test_sounds[slot] = entry
        self.state.save_settings()
        self._load_sounds()
        if cut:
            QMessageBox.information(self, "Test sound", f"Only the first {sounds.MAX_SECONDS:.0f} "
                                    f"seconds of this file are used.")

    def _play_sound(self, slot: int) -> None:
        if not self.state.sel_spk:
            QMessageBox.information(self, "Test sound", "Select a speaker on the room map first, "
                                    "then press Play again.")
            return
        self.state.identify(self.state.sel_spk, f"custom{slot + 1}")

    def _remove_sound(self, slot: int) -> None:
        sounds.remove(self.state.settings.test_sounds[slot], config_dir())
        self.state.settings.test_sounds[slot] = {}
        self.state.save_settings()
        self._load_sounds()

    # ------------------------------------------------------------ Windows sound output
    def refresh_output(self) -> None:
        """Shows which output Windows plays into right now."""
        was, self._loading = self._loading, True
        self._load_output()
        self._loading = was

    def showEvent(self, ev) -> None:
        self.refresh_output()
        super().showEvent(ev)

    def _load_output(self) -> None:
        s = self.state.settings
        self.default_output.setChecked(s.default_output)
        self.restore_output.setChecked(s.restore_output)
        self.auto_surround.setChecked(s.auto_surround)
        self.follow_volume.setChecked(s.follow_windows_volume)
        self.auto_surround.setEnabled(s.default_output)
        self.restore_output.setEnabled(s.default_output)
        self.output_now.setEnabled(s.default_output and windefault.supported())
        boots = autostart.supported() and autostart.is_enabled()
        self.boot_btn.setVisible(s.default_output and autostart.supported() and not boots)
        notes = []
        if windefault.supported():
            try:
                _, name = windefault.default_output()
                if name:
                    notes.append(f"Windows plays into {name} right now.")
            except Exception:
                pass
        else:
            notes.append("This works in the Windows app.")
        if s.default_output and autostart.supported() and not boots:
            notes.append("To do this each time the PC starts, SpeakerWeave has to start with Windows.")
        self.output_state.setText(" ".join(notes))
        self.output_state.setVisible(bool(notes))

    def _make_default(self, show: bool) -> None:
        if self.state.runner.running:
            problem = self.state.make_default_output()
        else:
            # Windows only plays into SpeakerWeave while its sound runs, so start it
            self.state.start()
            problem = " ".join(self.state.last_errors)
        self._load_output()
        if problem and show:
            QMessageBox.information(self, "Windows sound output", problem)

    def _default_output_toggled(self, on: bool) -> None:
        if self._loading:
            return
        self._set("default_output", on)
        if on and self.state.runner.running:
            self._make_default(show=True)
        elif not on:
            self.state.restore_default_output()
        self._load_output()

    def load(self) -> None:
        s = self.state.settings
        self._loading = True
        supported = autostart.supported()
        self.start_windows.setEnabled(supported)
        self.start_windows.setChecked(supported and autostart.is_enabled())
        self.windows_hint.setText("" if supported else
                                  "Starting with Windows works in the installed app.")
        self.windows_hint.setVisible(not supported)
        self.start_tray.setChecked(s.start_in_tray)
        self.start_sound.setChecked(s.start_sound)
        self.close_tray.setChecked(s.close_to_tray)
        self.watch.setChecked(s.watch_devices)
        self.library.setChecked(s.apply_library)
        self.meters.setChecked(s.show_meters)
        self.updates_box.setChecked(s.check_updates)
        self._load_look()
        self._load_sounds()
        self._load_output()
        self._loading = False

    def _set(self, field: str, value) -> None:
        if self._loading:
            return
        setattr(self.state.settings, field, value)
        self.state.save_settings()

    def _follow_volume_toggled(self, on: bool) -> None:
        self._set("follow_windows_volume", on)
        self.state.follow_windows_volume()

    def _windows_toggled(self, on: bool) -> None:
        if self._loading:
            return
        try:
            autostart.set_enabled(on)
            self._set("start_with_windows", on)
        except Exception as exc:
            QMessageBox.warning(self, "SpeakerWeave", f"Could not change this.\n\n{exc}")
            self.load()
        self._loading = True
        self._load_output()
        self._loading = False

    def _meters_toggled(self, on: bool) -> None:
        self._set("show_meters", on)
        self.window.map.update()

    def _reset(self) -> None:
        answer = QMessageBox.question(self, "Reset settings",
                                      "Put every setting on this page back to how it started? "
                                      "Your speakers and controls are kept.")
        if answer != QMessageBox.Yes:
            return
        old = self.state.settings
        fresh = AppSettings()
        fresh.bindings, fresh.setup_slots = old.bindings, old.setup_slots
        fresh.remote_enabled, fresh.remote_port, fresh.remote_token = \
            old.remote_enabled, old.remote_port, old.remote_token
        fresh.test_sounds = old.test_sounds
        fresh.managed_output, fresh.previous_outputs = old.managed_output, old.previous_outputs
        self.state.settings = fresh
        if autostart.supported() and autostart.is_enabled():
            try:
                autostart.set_enabled(False)
            except Exception:
                pass
        self.state.save_settings()
        self.load()
        self.apply_theme()
        self.window.map.update()
