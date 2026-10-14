"""The first run tour: it starts once, spotlights every part, and can be skipped."""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from fake_audio import FakeSoundDevice
from speakerweave import backend
from speakerweave.ui import state as state_module
from speakerweave.ui import theme

_SCRATCH = tempfile.mkdtemp()
state_module.config_dir = lambda: _SCRATCH


def pump(app, seconds=0.0):
    end = time.monotonic() + seconds
    app.processEvents()
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def window():
    from speakerweave.ui.state import AppState
    from speakerweave.ui.window import MainWindow
    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    backend._sd = lambda: FakeSoundDevice([{"name": "Speakers", "outputs": 2},
                                           {"name": "Line in", "inputs": 2, "silent": True}])
    state = AppState("")
    state.settings.default_output = False
    state.settings.start_sound = False
    state.settings.simhub_link = False
    state.settings.check_updates = False
    win = MainWindow(state)
    win.resize(1400, 900)
    win.show()
    return app, state, win


def test_the_tour_opens_once_and_spotlights_every_part():
    app, state, win = window()
    assert not state.settings.tour_done
    pump(app, 1.3)                                   # the window settles, then the tour opens
    tour = win._tour
    assert tour is not None and tour.isVisible() and tour.geometry() == win.rect()
    seen_titles = []
    while True:
        pump(app, 0.2)
        step = tour.steps[tour.index]
        seen_titles.append(step.title)
        card = tour.card.geometry()
        assert win.rect().contains(card), step.title             # the card always fits
        if step.target is not None:
            assert not tour._hole.isNull(), f"nothing spotlit at {step.title}"
            assert not card.intersects(tour._hole) or tour._hole.height() > win.height() * 0.6, step.title
        else:
            assert tour._hole.isNull()
        if tour.index == len(tour.steps) - 1:
            assert tour.next_btn.text() == "Finish" and not tour.skip_btn.isVisible()
            QTest.mouseClick(tour.next_btn, Qt.LeftButton)
            break
        QTest.mouseClick(tour.next_btn, Qt.LeftButton)
    pump(app, 0.1)
    assert len(seen_titles) == len(tour.steps) >= 15
    assert "Effects tab" in seen_titles and "Errors" in seen_titles
    assert win._tour is None and state.settings.tour_done
    assert win.pages.currentIndex() == 0

    # again from the Setup menu, then skipped with Escape halfway
    win.start_tour()
    tour = win._tour
    tour.go(5)
    QTest.keyClick(tour, Qt.Key_Left)
    assert tour.index == 4
    QTest.keyClick(tour, Qt.Key_Escape)
    pump(app, 0.1)
    assert win._tour is None
    win.state.runner.stop()
    win.close()


def test_the_card_never_covers_what_it_explains_on_a_small_window():
    app, state, win = window()
    state.settings.tour_done = True
    win.resize(1000, 700)
    pump(app, 0.3)
    win.start_tour()
    tour = win._tour
    for i in range(len(tour.steps)):
        tour.go(i)
        pump(app, 0.15)
        assert QRect(win.rect()).contains(tour.card.geometry())
    tour.close_tour(False)
    win.state.runner.stop()
    win.close()
