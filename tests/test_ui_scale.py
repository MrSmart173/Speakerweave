"""Interface size: Windows' own scaling, times a size of your own (100% to start with)."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from speakerweave.settings import AppSettings, UI_SCALES, clean_scale


def test_sizes_are_kept_to_the_ones_offered(tmp_path):
    assert AppSettings().ui_scale == 100
    assert clean_scale(130) == 125 and clean_scale("x") == 100 and clean_scale(10) == min(UI_SCALES)
    s = AppSettings()
    s.ui_scale = 999
    path = str(tmp_path / "settings.json")
    s.save(path)
    assert AppSettings.load(path).ui_scale == max(UI_SCALES)


def test_the_size_is_set_before_qt_starts(tmp_path, monkeypatch):
    from speakerweave import app
    from speakerweave.ui import state as state_module
    monkeypatch.setattr(state_module, "config_dir", lambda: str(tmp_path))
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
    assert app.apply_ui_scale() == 1.0 and "QT_SCALE_FACTOR" not in os.environ   # 100%: Windows only
    s = AppSettings()
    s.ui_scale = 125
    s.save(str(tmp_path / "settings.json"))
    assert app.apply_ui_scale() == 1.25 and os.environ["QT_SCALE_FACTOR"] == "1.25"
    os.environ.pop("QT_SCALE_FACTOR", None)
    program, args = app.restart_command()
    assert program == sys.executable and args == ["-m", "speakerweave"]


def test_choosing_a_size_saves_it_and_offers_a_restart(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from test_hidden_outputs import pump, window
    app, state, win = window([{"name": "Speakers", "outputs": 2}])
    try:
        asked = []
        monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: asked.append(a) or QMessageBox.No))
        restarted = []
        monkeypatch.setattr(win, "restart_app", lambda: restarted.append(1))
        page = win.settings_page
        assert page.scale_box.currentData() == 100 and "regular size" in page.scale_box.currentText()
        page.scale_box.setCurrentIndex(page.scale_box.findData(150))
        page._scale_chosen()
        assert state.settings.ui_scale == 150 and asked and not restarted
        monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
        page.scale_box.setCurrentIndex(page.scale_box.findData(100))
        page._scale_chosen()
        assert state.settings.ui_scale == 100 and restarted == [1]
    finally:
        monkeypatch.undo()
        win.close()
        state.stop()
        pump(app, 0.1)
