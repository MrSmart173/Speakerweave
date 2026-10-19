"""The Fun page: switching effects on and off, timed runs, amounts that are remembered, and
keys, controller buttons and Stream Deck links for every effect."""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from speakerweave import fun
from speakerweave.controls import all_actions, set_binding
from speakerweave.settings import AppSettings
from test_hidden_outputs import pump, window


def card(win, key):
    return next(c for c in win.fun_page.cards if c.effect.key == key)


def test_cards_switch_effects_and_the_engine_hears_about_it():
    app, state, win = window([{"name": "Speakers", "outputs": 2}])
    try:
        win.show_page(5)
        assert win.pages.currentWidget() is win.fun_page and win.fun_btn.isChecked()
        assert len(win.fun_page.cards) == len(fun.EFFECTS)
        robot = card(win, "robot")
        robot.switch.click()
        assert "robot" in state.fun_on and state.engine.fun_active == {"robot": 45.0}
        assert robot.switch.text() == "On" and win.fun_btn.text() == "Fun (1)"
        assert "Robot" in win.fun_page.status.text() or "stopped" in win.fun_page.status.text()
        robot.slider.setValue(robot.slider.value() + 10)                  # more buzz
        assert state.engine.fun_active["robot"] == 55.0
        assert state.settings.fun["robot"]["amount"] == 55.0
        robot.switch.click()
        assert "robot" not in state.fun_on and state.engine.fun_active == {}
        assert win.fun_btn.text() == "Fun"

        shot = os.environ.get("SPEAKERWEAVE_SHOT")
        if shot:
            card(win, "bass").switch.click()
            state.fun_for("echo", 8)
            win.resize(1500, 900)
            pump(app, 0.3)
            win.grab().save(shot)
            state.stop_fun()
    finally:
        win.close()
        state.stop()
        pump(app, 0.1)


def test_play_for_switches_itself_off_and_counts_down():
    app, state, win = window([{"name": "Speakers", "outputs": 2}])
    try:
        echo = card(win, "echo")
        echo.seconds.setValue(1)
        assert state.settings.fun["echo"]["seconds"] == 1
        echo.play.click()
        assert "echo" in state.fun_on and 0 < state.fun_left("echo") <= 1.0
        pump(app, 0.3)
        assert echo.left.text().endswith("s left")
        pump(app, 1.0)
        assert "echo" not in state.fun_on and echo.left.text() == ""
        # pressing it again while it plays starts the time again; the switch keeps it on for good
        state.fun_for("echo", 5)
        state.fun_for("echo", 5)
        assert len(state._fun_timers) == 1
        state.toggle_fun("echo")
        assert state.fun_on["echo"] == 0.0 and not state._fun_timers   # on until switched off
        win.fun_page.stop_btn.click()
        assert not state.fun_on
    finally:
        win.close()
        state.stop()
        pump(app, 0.1)


def test_keys_and_links_reach_every_effect():
    app, state, win = window([{"name": "Speakers", "outputs": 2}])
    try:
        keys = {a.key for a in all_actions(state.project)}
        for effect in fun.EFFECTS:
            assert f"fun:{effect.key}" in keys and f"fun_for:{effect.key}" in keys
        assert "fun_stop" in keys
        win.actions.run("fun:pitch")
        assert "pitch" in state.fun_on
        win.actions.run("fun:pitch")
        assert "pitch" not in state.fun_on
        win.actions.run("fun_for:spin")
        assert state.fun_left("spin") > 0
        win.actions.run("fun_stop")
        assert not state.fun_on
        # a key given on the Controls page shows on the card
        set_binding(state.settings.bindings, "fun:bass", {"kind": "key", "vk": 120, "mods": 0,
                                                          "qt": "F9", "text": "F9"})
        win.controls_page._bindings_changed()
        button, clear = card(win, "bass").key_buttons["fun:bass"]
        assert button.text() == "F9" and clear.isVisibleTo(card(win, "bass"))
        clear.click()
        assert button.text() == "Set key"
    finally:
        win.close()
        state.stop()
        pump(app, 0.1)


def test_amounts_and_times_are_remembered_and_cleaned(tmp_path):
    s = AppSettings()
    s.fun = {"bass": {"amount": 99, "seconds": 0}, "nonsense": {"amount": 1},
             "echo": {"amount": "x", "seconds": 30}}
    path = str(tmp_path / "settings.json")
    s.save(path)
    again = AppSettings.load(path)
    assert again.fun["bass"] == {"amount": 18.0, "seconds": 1.0}        # kept within the slider
    assert "nonsense" not in again.fun
    assert again.fun["echo"] == {"amount": 0.35, "seconds": 30.0}


def test_effects_start_off_every_time():
    app, state, win = window([{"name": "Speakers", "outputs": 2}])
    try:
        assert state.fun_on == {} and state.engine.fun_active == {}
        assert time.monotonic() > 0
    finally:
        win.close()
        state.stop()
        pump(app, 0.1)
