"""VB-CABLE's output is called "SpeakerWeave Virtual Speaker output" in Windows, and
everything that named it CABLE Input still finds it."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from speakerweave import cable, default_output, speaker_library, windefault
from speakerweave.backend import DeviceInfo
from speakerweave.model import Project

OLD = "CABLE Input (VB-Audio Virtual Cable)"
NEW = "SpeakerWeave Virtual Speaker output (VB-Audio Virtual Cable)"


def test_both_names_are_the_cable_and_translate_into_each_other():
    assert cable.is_cable_input(OLD) and cable.is_cable_input(NEW + " [Loopback]")
    assert not cable.is_cable_input("CABLE-A Input (VB-Audio Cable A)")
    assert not cable.is_cable_input("Speakers (Realtek(R) Audio)")
    assert cable.other_name(OLD + " [Loopback]") == NEW + " [Loopback]"
    assert cable.other_name(NEW) == OLD
    assert cable.other_name("Speakers") == ""
    entry = speaker_library.recognise(NEW)
    assert entry is not None and entry.category == "virtual"         # never taken for a speaker


class FakeWindows:
    def __init__(self, short):
        self.short = short
        self.renamed = []

    def install(self, monkeypatch):
        monkeypatch.setattr(windefault, "supported", lambda: True)
        monkeypatch.setattr(windefault, "list_outputs",
                            lambda: [("{spk}", "Speakers (Realtek(R) Audio)"),
                                     ("{cab}", f"{self.short} (VB-Audio Virtual Cable)")])
        monkeypatch.setattr(windefault, "short_name", lambda dev_id: self.short if dev_id == "{cab}" else "x")

        def rename(dev_id, name):
            self.renamed.append((dev_id, name))
            self.short = name
        monkeypatch.setattr(windefault, "rename", rename)


def test_it_is_renamed_once_and_back_on_uninstall(monkeypatch):
    win = FakeWindows("CABLE Input")
    win.install(monkeypatch)
    assert cable.brand() and win.renamed == [("{cab}", cable.NEW_NAME)]
    assert not cable.brand()                                          # already done
    assert cable.unbrand() and win.short == "CABLE Input"


def test_a_name_of_your_own_is_left_alone(monkeypatch):
    win = FakeWindows("CABLE Input")
    win.install(monkeypatch)
    win.short = "Game audio"
    monkeypatch.setattr(windefault, "list_outputs",
                        lambda: [("{cab}", "CABLE Input (VB-Audio Virtual Cable)")])
    assert not cable.brand() and not win.renamed


def test_the_cable_is_chosen_before_other_virtual_devices():
    p = Project()
    loopbacks = ["VoiceMeeter Input (VB-Audio VoiceMeeter VAIO) [Loopback]", NEW + " [Loopback]"]
    device, loopback, problem = default_output.plan(p, loopbacks)
    assert device == NEW and loopback == NEW + " [Loopback]" and not problem


def test_listen_to_follows_the_rename():
    from test_hidden_outputs import pump, window
    app, state, win = window([{"name": "Speakers", "outputs": 2}])
    try:
        state.project.input_kind, state.project.input_name = "loopback", OLD + " [Loopback]"
        state.loopbacks = [DeviceInfo(NEW + " [Loopback]", 9, 8, 0, 48000.0, True)]
        state._follow_renamed_input()
        assert state.project.input_name == NEW + " [Loopback]"
        assert state.windows_volume_device() in ("", NEW)
    finally:
        win.close()
        state.stop()
        pump(app, 0.1)


def test_a_setup_with_the_old_name_still_finds_the_cable(monkeypatch):
    from speakerweave import soundcheck
    from speakerweave.settings import AppSettings
    assert cable.pick(OLD + " [Loopback]", ["Speakers [Loopback]", NEW + " [Loopback]"]) == NEW + " [Loopback]"
    assert cable.pick(OLD + " [Loopback]", [NEW]) == ""             # a loopback is never an output
    assert cable.pick("Speakers [Loopback]", [NEW + " [Loopback]"]) == ""
    p = Project(input_kind="loopback", input_name=OLD + " [Loopback]")
    p.add_device("Speakers", 2)
    report = soundcheck.Report()
    soundcheck.check_setup(p, [DeviceInfo("Speakers", 1, 0, 2, 48000.0, True)],
                           [DeviceInfo(NEW + " [Loopback]", 9, 8, 0, 48000.0, True)], report, NEW)
    assert not any("not available" in f.title or "not playing into" in f.title for f in report.findings)

    win = FakeWindows(cable.NEW_NAME)
    win.install(monkeypatch)
    chosen = []
    monkeypatch.setattr(windefault, "defaults", lambda: {0: "{spk}", 1: "{spk}", 2: "{spk}"})
    monkeypatch.setattr(windefault, "set_default", lambda dev_id, roles=None: chosen.append(dev_id))
    changed, problem = default_output.apply(AppSettings(), OLD)
    assert changed and not problem and chosen == ["{cab}"]


def test_the_list_is_read_again_while_windows_is_still_renaming(monkeypatch):
    """Straight after the rename Windows can leave the cable out of the lists for a moment.
    The setup must still end up listening to it under its new name."""
    from test_hidden_outputs import pump, window
    from speakerweave import backend
    app, state, win = window([{"name": "Speakers", "outputs": 2}])
    try:
        state.project.input_kind, state.project.input_name = "loopback", OLD + " [Loopback]"
        FakeWindows(cable.NEW_NAME).install(monkeypatch)
        monkeypatch.setattr(windefault, "default_output", lambda: ("{cab}", NEW))
        reads = []

        def list_loopbacks():
            reads.append(1)
            return [] if len(reads) < 3 else [DeviceInfo(NEW + " [Loopback]", 9, 8, 0, 48000.0, True)]
        monkeypatch.setattr(backend, "list_loopbacks", list_loopbacks)
        state.scan_devices()
        assert len(reads) == 3
        assert state.project.input_name == NEW + " [Loopback]"
    finally:
        win.close()
        state.stop()
        pump(app, 0.1)


def test_rescan_starts_the_sound_again_after_it_failed(monkeypatch):
    from test_hidden_outputs import pump, window
    app, state, win = window([{"name": "Speakers", "outputs": 2}])
    try:
        state.last_errors = ["Input: 'CABLE Input (VB-Audio Virtual Cable) [Loopback]' was not found"]
        findings = win.errors_page.findings()
        card = next(f for f in findings if f.title == "Input")
        assert card.action == "rescan" and "Press Rescan" in card.fix
        started = []
        monkeypatch.setattr(state, "start", lambda *a, **k: started.append(1))
        win.errors_page.do_action("rescan")
        assert started == [1]
    finally:
        win.close()
        state.stop()
        pump(app, 0.1)
