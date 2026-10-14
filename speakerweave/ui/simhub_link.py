"""Follows the game SimHub reports through the SpeakerWeave plugin, and loads the
speaker setup chosen for that game."""
from __future__ import annotations

import os
import re

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from .. import __version__
from ..model import Project
from ..simhub import game_title
from .state import config_dir

GAME_SETTLE_MS = 3000           # a game must be reported this long before its setup loads
NO_GAME_SETTLE_MS = 8000        # and no game this long, so menus and restarts do not flip setups
SIMHUB_GONE_S = 20.0            # SimHub silent this long counts as no game


def game_dir() -> str:
    path = os.path.join(config_dir(), "Game setups")
    os.makedirs(path, exist_ok=True)
    return path


def _inside(path: str, folder: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(folder)]) == os.path.abspath(folder)
    except ValueError:
        return False


class SimHubLink(QObject):
    reported = Signal(str, str, str)    # game, car, track. May be emitted from any thread.
    changed = Signal()

    def __init__(self, window, state):
        super().__init__(window if isinstance(window, QObject) else None)
        self.window, self.state = window, state
        self.game = ""                  # the game whose setup is in use ("" = none)
        self.car = ""
        self.track = ""
        self.active_file = ""           # the setup file loaded for that game
        self._loaded = None             # the setup as loaded from it, to notice other setups loaded since
        self.message = ""
        self._pending = None
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.timeout.connect(self._apply)
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._heartbeat)
        self._tick.start(1000)
        self.reported.connect(self._on_report)

    # ------------------------------------------------------------ status for SimHub
    def status(self) -> dict:
        p, state = self.state.project, self.state
        return {"app": "SpeakerWeave", "version": __version__, "running": bool(state.runner.running),
                "muted": bool(p.muted), "volume_db": round(float(p.master_db), 1), "mode": p.mode_text(),
                "setup": os.path.splitext(os.path.basename(self.current_file()))[0],
                "game": game_title(self.game) if self.game else ""}

    def _heartbeat(self) -> None:
        remote = self.window.remote
        if not remote.running:
            return
        remote.status = self.status()
        if (self.game or self._pending) and not remote.simhub_connected(SIMHUB_GONE_S):
            self._on_report("", "", "")
        self.changed.emit()

    # ------------------------------------------------------------ reports
    @Slot(str, str, str)
    def _on_report(self, game: str, car: str, track: str) -> None:
        if not self.state.settings.simhub_link:
            return
        if game:
            self.car, self.track = car or self.car, track or self.track
            seen = self.state.settings.games_seen
            if game not in seen:
                seen.insert(0, game)
                del seen[40:]
                self.state.save_settings()
                self.changed.emit()
        if game == (self._pending if self._pending is not None else self.game):
            return
        if game == self.game:
            self._pending = None
            self._settle.stop()
            return
        self._pending = game
        self._settle.start(GAME_SETTLE_MS if game else NO_GAME_SETTLE_MS)

    def _apply(self) -> None:
        if self._pending is None:
            return
        game, self._pending = self._pending, None
        self.game = game
        if not game:
            self.car = self.track = ""
        target = self.state.settings.game_setups.get(game, "")
        if target:
            self.load(target, game)
        self.changed.emit()

    # ------------------------------------------------------------ setups
    def current_file(self) -> str:
        """The game setup file in use, "" when a different setup was loaded since."""
        return self.active_file if self.active_file and self.state.project is self._loaded else ""

    def load(self, path: str, game: str) -> bool:
        current = self.current_file()
        if current and os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(current)):
            return True
        if not os.path.isfile(path):
            self.message = f"The setup for {game_title(game)} is missing: {path}"
            self.state.notice.emit(self.message)
            return False
        try:
            project = Project.load(path)
        except Exception as exc:
            self.message = f"The setup for {game_title(game)} could not be loaded ({exc})"
            self.state.notice.emit(self.message)
            return False
        self.keep_changes()
        self.state.replace_project(project)
        self.window._load_top()
        self.active_file, self._loaded = path, project
        self.message = ""
        name = os.path.splitext(os.path.basename(path))[0]
        self.state.notice.emit(f"{game_title(game)}: loaded the setup {name}")
        return True

    def keep_changes(self) -> None:
        """Changes made while a game setup was in use stay in that game's setup file."""
        if getattr(self.state, "saving_blocked", False):
            return
        if self.state.saving_blocked:       # SpeakerWeave's data is being removed
            return
        current = self.current_file()
        if current and _inside(current, game_dir()):
            try:
                self.state.project.save(current)
            except Exception:
                pass

    def save_current_for(self, game: str) -> str:
        """Saves the speaker setup as it is now as the setup of this game."""
        safe = re.sub(r'[\\/:*?"<>|]+', " ", game_title(game)).strip() or "Game"
        path = os.path.join(game_dir(), f"{safe}.json")
        self.state.project.save(path)
        self.state.settings.game_setups[game] = path
        self.state.save_settings()
        if game == self.game:
            self.active_file, self._loaded = path, self.state.project
        self.changed.emit()
        return path

    def choose(self, game: str, path: str) -> None:
        settings = self.state.settings
        if path:
            settings.game_setups[game] = path
        else:
            settings.game_setups.pop(game, None)
        self.state.save_settings()
        if game == self.game and path:
            self.load(path, game)
        self.changed.emit()
