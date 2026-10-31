"""Panels and workspaces, the way Premiere Pro does them, the Studio and Classic looks, and
the level meters' pin."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QEnterEvent
from PySide6.QtWidgets import QApplication, QTabBar

from test_hidden_outputs import pump, window
from speakerweave.settings import AppSettings
from speakerweave.ui import theme, workspace as ws_module
from speakerweave.ui.workspace import BUILT_IN, layout_keys


def front(win, key):
    return win.workspaces.in_front(key)


def fresh(win, name="Setup"):
    s = win.workspaces.settings
    s.workspace_layouts, s.workspace_saved, s.workspace_custom = {}, {}, []
    win.workspaces.switch(name)
    win.workspaces.reset()
    pump(QApplication.instance(), 0.2)


def test_every_workspace_lays_out_its_panels():
    app, state, win = window([{"name": "Speakers", "outputs": 2}])
    try:
        state.save_settings = lambda: None
        ws = win.workspaces
        for name, tree in BUILT_IN.items():
            fresh(win, name)
            assert ws.current == name and win.workspace_bar.buttons[name].isChecked()
            wanted = set(layout_keys(tree)) & set(ws.panels)
            assert {k for k, p in ws.panels.items() if not p.isHidden()} == wanted, name
            for key in wanted:                       # nothing is squashed out of sight
                panel = ws.panel(key)
                assert panel.width() > 60 and panel.height() > 40, (name, key)
        fresh(win, "Setup")
        # Speaker, Output, Sound, Lights and Effects are tabs of one group: one header, the tabs
        assert front(win, "speaker") and not front(win, "output")
        speaker = ws.panel("speaker")
        assert speaker.titleBarWidget() is speaker.blank
        assert ws.panel("room").titleBarWidget() is ws.panel("room").header
        found = ws._tab_of(speaker)
        assert found is not None
        bar, index = found
        assert [bar.tabText(i) for i in range(bar.count())] == ["Speaker", "Output", "Sound", "Lights",
                                                                "Effects"]
        assert bar.tabButton(index, QTabBar.RightSide) is not None    # the panel menu, in front only
        assert all(bar.tabButton(i, QTabBar.RightSide) is None for i in range(bar.count()) if i != index)
    finally:
        win.state.runner.stop()
        win.close()


def test_pages_open_as_panels_beside_the_room_and_close_again():
    app, state, win = window([{"name": "Speakers", "outputs": 2}])
    try:
        state.save_settings = lambda: None
        fresh(win)
        ws = win.workspaces
        assert not ws.is_open("settings")
        win.show_page(2)
        pump(app, 0.1)
        assert front(win, "settings") and win.pages.currentIndex() == 2
        assert ws.panel("settings") in win.dock_host.tabifiedDockWidgets(ws.panel("room"))
        assert not front(win, "room")
        win.show_page(0)
        pump(app, 0.1)
        assert front(win, "room") and ws.is_open("settings")      # still there, as a tab
        # Fun and Errors on the top bar say whether their panel is in front
        win.show_page(5)
        pump(app, 0.1)
        assert win.fun_btn.isChecked() and not win.errors_btn.isChecked()
        win.errors_btn.click()
        pump(app, 0.1)
        assert win.errors_btn.isChecked() and not win.fun_btn.isChecked() and front(win, "errors")
        # the panel menu closes it, a menu entry opens it again
        menu = ws.panel_menu(ws.panel("errors"))
        texts = [a.text() for a in menu.actions() if a.text()]
        assert texts == ["Close panel", "Undock panel", "Close other panels in group", "Maximise panel"]
        next(a for a in menu.actions() if a.text() == "Close panel").trigger()
        pump(app, 0.1)
        assert not ws.is_open("errors") and not win.errors_btn.isChecked()
        ws.toggle("errors", True)
        pump(app, 0.1)
        assert front(win, "errors")
        # undocking floats it, docking puts it back
        ws.undock(ws.panel("errors"))
        pump(app, 0.1)
        assert ws.panel("errors").isFloating() and ws.panel("errors").titleBarWidget() is ws.panel("errors").header
        ws.panel("errors").setFloating(False)
        pump(app, 0.1)
        assert not ws.panel("errors").isFloating()
    finally:
        win.state.runner.stop()
        win.close()


def test_maximise_a_panel_and_back():
    app, state, win = window([{"name": "Speakers", "outputs": 2}])
    try:
        state.save_settings = lambda: None
        fresh(win)
        ws = win.workspaces
        room = ws.panel("room")
        before = room.width()
        ws.toggle_maximised(room)
        pump(app, 0.2)
        assert ws.maximised is room
        assert [k for k, p in ws.panels.items() if not p.isHidden()] == ["room"]
        assert room.width() > before + 200
        # the layout kept for the workspace is the one before maximising
        ws.remember()
        ws.toggle_maximised()
        pump(app, 0.2)
        assert ws.maximised is None and ws.is_open("outputs") and ws.is_open("speaker")
        assert abs(room.width() - before) < 40
    finally:
        win.state.runner.stop()
        win.close()


def test_workspaces_are_remembered_saved_renamed_and_deleted():
    app, state, win = window([{"name": "Speakers", "outputs": 2}])
    try:
        saved = []
        fresh(win)
        ws = win.workspaces
        ws._save = lambda: saved.append(1)
        s = ws.settings
        ws.close_panel("outputs")
        pump(app, 0.1)
        ws.switch("Play")                                   # the change to Setup is kept
        assert not ws.is_open("outputs") and front(win, "fun")
        ws.switch("Setup")
        pump(app, 0.1)
        assert not ws.is_open("outputs")
        ws.reset()                                          # back as it was saved
        pump(app, 0.1)
        assert ws.is_open("outputs")

        ws.close_panel("now")
        assert ws.save_as("  My   desk ")
        assert ws.current == "My desk" and s.workspace_custom == ["My desk"]
        assert "My desk" in win.workspace_bar.buttons
        assert not ws.save_as("Setup") and not ws.save_as("my desk".replace("my", "My")) and not ws.save_as(" ")
        ws.open("now")
        ws.reset()                                          # its saved layout has no Now playing
        pump(app, 0.1)
        assert not ws.is_open("now")
        assert ws.rename("My desk", "Racing")
        assert ws.current == "Racing" and "Racing" in s.workspace_saved and "My desk" not in s.workspace_saved
        assert not ws.rename("Setup", "Mine") and not ws.delete("Setup")
        assert ws.delete("Racing")
        assert ws.current == "Setup" and s.workspace_custom == [] and "Racing" not in s.workspace_layouts
        assert saved

        # Save changes to a built in workspace, then back to the original
        ws.close_panel("now")
        ws.save_changes()
        ws.open("now")
        ws.reset()
        assert not ws.is_open("now")
        ws.original()
        assert ws.is_open("now") and "Setup" not in s.workspace_saved

        # the menus
        from PySide6.QtWidgets import QMenu
        menu = QMenu()
        ws.fill_workspace_menu(menu, win)
        texts = [a.text() for a in menu.actions() if a.text()]
        assert texts[:4] == ["Setup", "Tune", "Play", "Classic"]
        assert "Save as new workspace..." in texts and "Reset to saved layout" in texts
        menu.clear()
        ws.fill_panel_menu(menu)
        assert [a.text() for a in menu.actions()][:3] == ["Outputs", "Room", "Now playing"]
        assert next(a for a in menu.actions() if a.text() == "Room").isChecked()
    finally:
        win.state.runner.stop()
        win.close()


def test_the_layout_comes_back_after_a_restart():
    app, state, win = window([{"name": "Speakers", "outputs": 2}])
    try:
        fresh(win, "Tune")
        win.workspaces.close_panel("outputs")
        pump(app, 0.1)
        path = win.workspaces.settings.path
        assert path.endswith("workspaces.json")
    finally:
        win.state.runner.stop()
        win.close()                                  # keeps the layout in workspaces.json
    with open(path, encoding="utf-8") as fh:
        kept = json.load(fh)
    assert kept["workspace"] == "Tune" and "Tune" in kept["layouts"]
    app, state2, win2 = window([{"name": "Speakers", "outputs": 2}])
    try:
        pump(app, 0.2)
        assert win2.workspaces.current == "Tune"
        assert not win2.workspaces.is_open("outputs") and win2.workspaces.is_open("speaker")
        # a layout from an older SpeakerWeave is not used: the workspace is laid out afresh
        win2.workspaces.settings.workspace_layouts = {"Tune": "bm90IGEgbGF5b3V0"}
        win2.workspaces.start()
        pump(app, 0.2)
        assert win2.workspaces.is_open("outputs")
        fresh(win2)
    finally:
        win2.state.runner.stop()
        win2.close()


def test_double_clicking_a_tab_maximises_and_the_tab_menu_works():
    app, state, win = window([{"name": "Speakers", "outputs": 2}])
    try:
        state.save_settings = lambda: None
        fresh(win)
        ws = win.workspaces
        bar, index = ws._tab_of(ws.panel("sound"))
        assert ws._panel_of(bar, index) is ws.panel("sound")
        pos = bar.tabRect(index).center()
        event = QEvent(QEvent.MouseButtonDblClick)
        from PySide6.QtGui import QMouseEvent
        event = QMouseEvent(QEvent.MouseButtonDblClick, QPointF(pos), QPointF(bar.mapToGlobal(pos)),
                            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(bar, event)
        pump(app, 0.2)
        assert ws.maximised is ws.panel("sound")
        ws.restore_maximised()
        pump(app, 0.2)
        assert ws.maximised is None and ws.is_open("room")
    finally:
        win.state.runner.stop()
        win.close()


def test_the_level_meters_pin_and_slide_up_on_a_hover():
    app, state, win = window([{"name": "Speakers", "outputs": 2}])
    try:
        state.save_settings = lambda: None
        drawer = win.levels_drawer
        assert state.settings.levels_pinned and drawer.pinned
        assert drawer.sheet.isVisible() and not drawer.strip.isVisible()
        assert win.levels.isVisible()
        drawer.pin.click()                                       # unpinned: a thin strip stays
        pump(app, 0.1)
        assert not state.settings.levels_pinned and not win.pin_action.isChecked()
        assert drawer.strip.isVisible() and not drawer.sheet.isVisible()
        assert drawer.strip.height() == drawer.STRIP_HEIGHT
        # resting the mouse on the strip for half a second slides them up
        assert drawer.HOVER_MS == 500
        QApplication.sendEvent(drawer.strip, QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
        assert drawer.hover_timer.isActive() and drawer.hover_timer.interval() == 500
        QApplication.sendEvent(drawer.strip, QEvent(QEvent.Leave))
        assert not drawer.hover_timer.isActive()                 # moved on before half a second
        drawer.slide_up()
        pump(app, 0.4)
        assert drawer.is_open and drawer.sheet.isVisible()
        sheet = drawer.sheet.geometry()
        strip_bottom = drawer.strip.mapTo(drawer.over, drawer.strip.rect().bottomLeft()).y()
        assert sheet.height() > 150 and abs(sheet.bottom() - strip_bottom) <= 2   # over the panels
        drawer._mouse_on = lambda widget: False                  # the mouse went elsewhere
        pump(app, 0.9)
        assert not drawer.is_open and not drawer.sheet.isVisible()
        del drawer._mouse_on
        win.pin_action.trigger()                                 # pinned again from the Window menu
        pump(app, 0.1)
        assert drawer.pinned and state.settings.levels_pinned and drawer.sheet.isVisible()
        win._levels_toggled(False)                               # Window > Levels hides them
        assert not drawer.isVisible() and not state.settings.show_levels
        win._levels_toggled(True)
        assert drawer.isVisible()
    finally:
        win.state.runner.stop()
        win.close()


def test_studio_is_the_new_look_and_classic_is_one_click_away(tmp_path):
    old = AppSettings()
    data = json.loads(json.dumps(old.__dict__))
    data.update(version=2, theme="midnight")
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data))
    moved = AppSettings.load(str(path))
    assert moved.theme == "studio" and moved.look == "studio" and moved.version >= 3
    data.update(version=2, theme="forest")
    path.write_text(json.dumps(data))
    assert AppSettings.load(str(path)).theme == "forest"        # a colour chosen on purpose stays
    data.update(version=3, theme="midnight", look="classic")
    path.write_text(json.dumps(data))
    kept = AppSettings.load(str(path))
    assert kept.theme == "midnight" and kept.look == "classic"
    from speakerweave.ui.workspace import WorkspaceStore
    spaces = tmp_path / "workspaces.json"
    spaces.write_text(json.dumps({"workspace": "A", "custom": ["A", "A", 5, "", "Setup"],
                                  "layouts": {"A": "x", "B": 7}, "saved": []}))
    store = WorkspaceStore.load(str(spaces))
    assert store.workspace == "A" and store.workspace_custom == ["A"]
    assert store.workspace_layouts == {"A": "x"} and store.workspace_saved == {}
    spaces.write_text("not json")
    assert WorkspaceStore.load(str(spaces)).workspace == "Setup"

    app, state, win = window([{"name": "Speakers", "outputs": 2}])
    try:
        state.save_settings = lambda: None
        fresh(win)
        win.use_look("classic")
        pump(app, 0.2)
        s = state.settings
        assert s.look == "classic" and s.theme == "midnight" and theme.LOOK == "classic"
        assert win.workspaces.current == "Classic" and "font-size: 13px" in theme.STYLE
        assert win.settings_page.look_box.currentData() == "classic"
        win.use_look("studio")
        pump(app, 0.2)
        assert s.look == "studio" and s.theme == "studio" and theme.LOOK == "studio"
        assert win.workspaces.current == "Setup" and "font-size: 12px" in theme.STYLE
        # every preset reads well in both looks
        for key, (_name, _note, colors) in theme.PRESETS.items():
            for look in theme.LOOKS:
                theme.use(colors, look)
                assert "QMainWindow > QTabBar" in theme.STYLE
        theme.apply(app, theme.PRESETS[theme.DEFAULT_THEME][2], theme.DEFAULT_LOOK)
    finally:
        win.state.runner.stop()
        win.close()


def test_the_window_menus():
    app, state, win = window([{"name": "Speakers", "outputs": 2}])
    try:
        bar = win.menuBar()
        titles = [a.text().replace("&", "") for a in bar.actions()]
        assert titles == ["File", "Sound", "Window", "Help"]
        assert not hasattr(win, "setup_btn") and not hasattr(win, "nav")
        assert ws_module.TITLES["tones"] == "Tone generator"
    finally:
        win.state.runner.stop()
        win.close()
