"""The Errors button lights up yellow for a second when a warning appears, flashes red while
there are errors, and SpeakerWeave opens with a summary of any problems."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from speakerweave import soundcheck
from speakerweave.ui import theme
from speakerweave.ui.errors_page import badge_flash_style, badge_style


def test_a_warning_lights_it_yellow_for_a_second_then_it_is_the_theme_again():
    from test_hidden_outputs import pump, window
    app, state, win = window([{"name": "Speakers", "outputs": 2}])
    try:
        win._errors_counted(0, 1, 0)
        assert win.errors_btn.styleSheet() == badge_flash_style("warning")
        assert win._warn_timer.isActive() and win._warn_timer.interval() == 1000
        win._warn_timer.timeout.emit()
        assert win.errors_btn.styleSheet() == badge_style(0, 1, 0) == ""     # the theme's colours
        win._errors_counted(0, 1, 0)                                      # the same warning: no light
        assert win.errors_btn.styleSheet() == ""
    finally:
        win.close()
        state.stop()
        pump(app, 0.1)


def test_errors_flash_red_until_they_are_gone():
    from test_hidden_outputs import pump, window
    app, state, win = window([{"name": "Speakers", "outputs": 2}])
    try:
        win._errors_counted(2, 0, 0)
        assert win._badge_timer.isActive()
        styles = set()
        for _ in range(4):
            styles.add(win.errors_btn.styleSheet())
            win._badge_timer.timeout.emit()
        assert styles == {badge_flash_style("error"), badge_style(2, 0, 0)}   # on, off, on, off
        assert theme.BAD in badge_flash_style("error")
        win.show_page(3)                                                  # on the Errors page: steady
        for _ in range(3):
            win._badge_timer.timeout.emit()
            assert win.errors_btn.styleSheet() == badge_style(2, 0, 0)
        win.show_page(0)
        win._errors_counted(0, 0, 0)                                      # fixed
        assert not win._badge_timer.isActive() and win.errors_btn.styleSheet() == ""
    finally:
        win.close()
        state.stop()
        pump(app, 0.1)


def test_it_opens_with_a_summary_of_the_problems(monkeypatch):
    from test_hidden_outputs import pump, window
    app, state, win = window([{"name": "Speakers", "outputs": 2}])
    try:
        found = [soundcheck.Finding("error", "Windows is not playing into the virtual device", ""),
                 soundcheck.Finding("warning", "No centre speaker", ""),
                 soundcheck.Finding("warning", "VG258 keeps being interrupted", ""),
                 soundcheck.Finding("warning", "The laptop is far quieter", "")]
        monkeypatch.setattr(win.errors_page, "refresh", lambda: None)
        win.errors_page.last_found = found
        win._startup_problems()
        note = win._problems_note
        assert note is not None and note.isVisible()
        from PySide6.QtWidgets import QLabel
        labels = [l.text() for l in note.findChildren(QLabel)]
        assert labels[0] == "1 error and 3 warnings found"
        assert any("not playing into" in t for t in labels) and "and 1 more" in labels
        shot = os.environ.get("SPEAKERWEAVE_SHOT")
        if shot:
            win.grab().save(shot)
        note.ignore_btn.click()                                           # Ignore: just goes
        assert win._problems_note is None and win.pages.currentIndex() == 0
        win._startup_problems()
        win._problems_note.go_btn.click()                                 # or to the Errors page
        assert win.pages.currentIndex() == 3
        win.errors_page.last_found = []
        win.show_page(0)
        win._startup_problems()                                           # nothing wrong: no note
        assert win._problems_note is None
    finally:
        win.close()
        state.stop()
        pump(app, 0.1)
