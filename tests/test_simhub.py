"""The link with SimHub: the plugin's links, and a speaker setup per game."""
import json
import os
import socket
import sys
import tempfile
import urllib.error
import urllib.request
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from speakerweave import simhub
from speakerweave.remote import RemoteServer


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_game_names_read_well():
    assert simhub.game_title("IRacing") == "iRacing"
    assert simhub.game_title("AssettoCorsaCompetizione") == "Assetto Corsa Competizione"
    assert simhub.game_title("DR2") == "DiRT Rally 2.0"
    assert simhub.game_title("F12024") == "F1 2024"
    assert simhub.game_title("SomeNewGame") == "Some New Game"
    assert simhub.game_title("") == "No game running"


def test_the_plugin_links_answer_with_state_and_take_the_game():
    games, actions = [], []
    server = RemoteServer(free_port(), "abc123", actions.append, lambda *g: games.append(g))
    assert server.start()
    try:
        server.status = {"running": True, "volume_db": -6.0, "mode": "5.1"}
        base = f"http://127.0.0.1:{server.port}/abc123/"
        assert not server.simhub_connected()
        with urllib.request.urlopen(base + "status") as r:          # a Stream Deck asking
            assert json.loads(r.read())["mode"] == "5.1"
        assert not server.simhub_connected() and games == []
        with urllib.request.urlopen(base + "status?client=simhub&name=IRacing&car=Porsche&track=Spa") as r:
            assert json.loads(r.read())["volume_db"] == -6.0
        assert server.simhub_connected() and games == [("IRacing", "Porsche", "Spa")]
        urllib.request.urlopen(base + "game?name=").read()
        assert games[-1] == ("", "", "")
        urllib.request.urlopen(base + "volume_up").read()
        assert actions == ["volume_up"]
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{server.port}/wrong/status")
            assert False, "a wrong code must be refused"
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
    finally:
        server.stop()


def test_the_plugin_goes_into_simhub_and_is_found_again(monkeypatch):
    folder = tempfile.mkdtemp()
    open(os.path.join(folder, simhub.SIMHUB_EXE), "wb").close()
    monkeypatch.setenv("SIMHUB_INSTALL_PATH", folder + os.sep)
    source = os.path.join(tempfile.mkdtemp(), simhub.PLUGIN_FILE)
    with open(source, "wb") as fh:
        fh.write(b"plugin 1")
    assert simhub.find_folder() == os.path.normpath(folder)
    assert simhub.plugin_state(folder, source) == "missing"
    assert simhub.plugin_state(folder, "") == "no plugin"
    done, asked, _ = simhub.install(folder, source)
    assert done and not asked
    assert simhub.plugin_state(folder, source) == "current"
    with open(source, "wb") as fh:
        fh.write(b"plugin 2")
    assert simhub.plugin_state(folder, source) == "old"
    monkeypatch.setenv("SIMHUB_INSTALL_PATH", tempfile.mkdtemp())
    monkeypatch.setattr(simhub, "_registry_folders", lambda: [])
    monkeypatch.setenv("ProgramFiles(x86)", tempfile.mkdtemp())
    monkeypatch.setenv("ProgramFiles", tempfile.mkdtemp())
    assert simhub.find_folder() == "" and simhub.plugin_state() == "no simhub"


def _app_state():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from speakerweave.ui import state as state_module
    from speakerweave.ui import theme
    folder = tempfile.mkdtemp()
    state_module.config_dir = lambda: folder
    from speakerweave.ui import simhub_link
    simhub_link.config_dir = lambda: folder
    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    from fake_audio import FakeSoundDevice
    from speakerweave import backend
    backend._sd = lambda: FakeSoundDevice([{"name": "Card", "outputs": 2}])
    from speakerweave.ui.state import AppState
    state = AppState("")
    state.settings.default_output = False
    return state, folder


def test_each_game_gets_its_own_speaker_setup():
    from speakerweave.model import Project
    from speakerweave.ui.simhub_link import SimHubLink, game_dir
    state, folder = _app_state()
    window = SimpleNamespace(remote=RemoteServer(free_port(), "x", lambda a: None), _load_top=lambda: None)
    link = SimHubLink(window, state)
    desk = os.path.join(folder, "Desk.json")
    Project(master_db=-20.0).save(desk)
    state.settings.game_setups[""] = desk

    link._on_report("IRacing", "Porsche", "Spa")
    assert link._pending == "IRacing" and link.game == ""         # waits until it settles
    link._on_report("", "", "")
    assert link._pending is None                                 # it went away again: nothing to do
    link._on_report("IRacing", "Porsche", "Spa")
    link._apply()
    assert link.game == "IRacing" and "IRacing" in state.settings.games_seen
    assert link.active_file == ""                                # no setup chosen for it yet

    state.project.master_db = -3.0
    path = link.save_current_for("IRacing")
    assert path.startswith(game_dir()) and path.endswith("iRacing.json")
    assert link.current_file() == path and link.status()["setup"] == "iRacing"
    state.project.master_db = -1.0                               # changed during the race

    link._on_report("", "", "")
    link._apply()                                                # back on the desktop
    assert state.project.master_db == -20.0 and link.current_file() == desk
    assert Project.load(path).master_db == -1.0                  # the race change was kept

    link._on_report("IRacing", "", "")
    link._apply()
    assert state.project.master_db == -1.0 and link.status()["game"] == "iRacing"
    state.replace_project(Project(master_db=-9.0))               # someone loads another setup
    assert link.current_file() == ""
    link.keep_changes()
    assert Project.load(path).master_db == -1.0                  # that one is not saved over it

    state.settings.game_setups["IRacing"] = os.path.join(folder, "gone.json")
    link._on_report("", "", "")
    link._apply()
    link._on_report("IRacing", "", "")
    link._apply()
    assert "missing" in link.message


def test_effects_tab_shows_simhub_and_the_games():
    from PySide6.QtWidgets import QApplication
    from speakerweave.ui.extras import ExtrasPanel
    from speakerweave.ui.simhub_link import SimHubLink
    state, folder = _app_state()
    remote = RemoteServer(free_port(), "x", lambda a: None)
    window = SimpleNamespace(remote=remote, _load_top=lambda: None, apply_remote=lambda: None)
    link = SimHubLink(window, state)
    panel = ExtrasPanel(state, link)
    box = panel.simhub_box
    assert box.on.isChecked() and box.status.text()
    rows = box.games.rowCount()
    state.settings.games_seen = ["AssettoCorsa"]
    box.refresh()
    labels = [box.games.itemAt(i).widget().text() for i in range(box.games.count())
              if hasattr(box.games.itemAt(i).widget(), "text")]
    assert "Assetto Corsa" in labels and "No game running" in labels
    assert box.games.rowCount() >= rows
    box.on.setChecked(False)
    assert not state.settings.simhub_link and box.status.text() == "Off"
    link._tick.stop()
    panel.deleteLater()
    link.deleteLater()
    QApplication.processEvents()
