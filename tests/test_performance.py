"""The Performance page: SpeakerWeave's own processor and memory use, and how the sound
keeps up."""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from speakerweave.perf import ProcessStats


def test_the_readings_cover_processor_memory_and_threads():
    stats = ProcessStats()
    first = stats.sample()
    assert "cpu_pc" not in first                       # nothing to compare with yet
    sum(i * i for i in range(300000))
    time.sleep(0.3)
    s = stats.sample()
    assert 0.0 <= s["cpu_pc"] <= 100.0 and s["cpu_core"] >= s["cpu_pc"]
    assert s["in_use"] > 1_000_000 and s["pc_total"] > s["in_use"]
    assert s["threads"] >= 1 and s["cores"] >= 1


def test_the_page_shows_the_numbers_and_the_last_two_minutes():
    from test_hidden_outputs import pump, window
    app, state, win = window([{"name": "Speakers", "outputs": 2}])
    try:
        dev = state.project.add_device("Speakers", 2)
        runner = state.runner
        runner.running = True
        runner.load, runner.load_peak = 0.18, 0.31
        runner.status = lambda: {dev.id: (14.0, 2.5, 3)}
        runner.delay_ms = lambda: 21.0
        win.show_page(4)
        page = win.performance_page
        for _ in range(3):
            page.stats._last = (page.stats._last[0] - 1.0,) + page.stats._last[1:]   # a second on
            page.tick()
        pump(app, 0.1)
        assert page.load.value.text() == "18%" and "31%" in page.load.note.text()
        assert page.delay.value.text() == "21 ms" and page.dropouts.value.text() == "3"
        assert page.cpu.value.text().endswith("%") and page.memory.value.text().endswith("MB")
        assert len(page.chart.data["cpu"]) == 4 and page.chart.data["load"][-1] == 18.0
        texts = [page.outputs.itemAt(i).widget().text() for i in range(page.outputs.count())]
        assert "Speakers" in texts and "+2 ppm" in texts or "+3 ppm" in texts
        shot = os.environ.get("SPEAKERWEAVE_SHOT")
        if shot:
            page.chart._hover = 1
            win.grab().save(shot)
        runner.running = False
        page.tick()
        assert page.load.value.text() == "Off"
    finally:
        state.runner.running = False
        win.close()
        state.stop()
        pump(app, 0.1)
