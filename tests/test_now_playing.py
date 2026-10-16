"""What is playing on the PC: read from Windows' media controls, shown under the map and in
a popup that counts down from 5 and closes itself."""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from speakerweave import media
from speakerweave.media import MediaWatcher, NowPlaying, app_name

CAN = {"play": True, "pause": True, "next": True, "previous": True}


class FakeReader:
    """Stands in for Windows: a playlist, and the commands it was given."""

    def __init__(self):
        self.track = 0
        self.playing = True
        self.done = []
        self.songs = [("Spotify.exe", "Midnight City", "M83"), ("Spotify.exe", "Wait", "M83")]

    def read(self):
        app, title, artist = self.songs[self.track]
        return NowPlaying(app_id=app, title=title, artist=artist,
                          status="playing" if self.playing else "paused", can=dict(CAN))

    def art(self):
        return b""

    def command(self, what):
        self.done.append(what)
        if what == "next":
            self.track = (self.track + 1) % len(self.songs)
        elif what == "toggle":
            self.playing = not self.playing

    def reset(self):
        pass

    def close(self):
        pass


def test_app_names_are_friendly():
    assert app_name("Spotify.exe") == "Spotify"
    assert app_name("AppleInc.AppleMusicWin_nzyj5cx40ttqa!App") == "Apple Music"
    assert app_name("308046B0AF4A39CB") == "Firefox"
    assert app_name("MSEdge") == "Microsoft Edge" and app_name("Chrome") == "Google Chrome"
    assert app_name("C:\\Tools\\Thing.exe") == "Thing"


def test_the_watcher_reports_changes_and_runs_commands(monkeypatch):
    monkeypatch.setattr(media, "LOOK_EVERY_S", 0.02)
    seen = []
    reader = FakeReader()
    watcher = MediaWatcher(seen.append, reader=reader)
    watcher.start()
    try:
        time.sleep(0.15)
        assert len(seen) == 1 and seen[0].title == "Midnight City"   # no repeats while it stays
        watcher.command("next")
        watcher.command("toggle")
        end = time.monotonic() + 2.0
        while time.monotonic() < end and not (seen[-1].title == "Wait" and not seen[-1].playing):
            time.sleep(0.02)
        assert reader.done == ["next", "toggle"]
        assert seen[-1].title == "Wait" and seen[-1].status == "paused"
    finally:
        watcher.stop()


def test_the_strip_and_the_popup(monkeypatch):
    from test_hidden_outputs import pump, window
    from speakerweave.ui import now_playing as ui
    app, state, win = window([{"name": "Speakers", "outputs": 2}])
    try:
        np = win.now_playing
        song = NowPlaying(app_id="Spotify.exe", title="Midnight City", artist="M83",
                          status="playing", can=dict(CAN))
        np._changed(song)                         # already playing when SpeakerWeave opened
        assert not np.popup.isVisible() and win.now_bar.isVisibleTo(win)
        assert win.now_bar.title.text() == "Midnight City" and "M83" in win.now_bar.by.text()
        assert win.now_bar.controls.play.toolTip() == "Pause"

        nxt = NowPlaying(app_id="Spotify.exe", title="Wait", artist="M83", status="playing", can=dict(CAN))
        np._changed(nxt)                          # a new song: the popup comes up
        assert np.popup.isVisible() and np.popup.title.text() == "Wait"
        assert np.popup.countdown.text() == "Closes in 5"
        shot = os.environ.get("SPEAKERWEAVE_SHOT")
        if shot:
            np.popup.grab().save(shot)
            win.grab().save(shot.replace(".png", "_window.png"))
        np.popup._left_ms = 1200
        np.popup._tick()
        assert np.popup.countdown.text() == "Closes in 2"
        np.popup._hovered = True                  # the mouse on it: the countdown waits
        np.popup._tick()
        assert np.popup._left_ms == 1100 and np.popup.countdown.text() == "Paused"
        np.popup._hovered = False
        for _ in range(12):
            np.popup._tick()
        assert not np.popup.isVisible()           # closed by itself

        paused = NowPlaying(app_id="Spotify.exe", title="Wait", artist="M83", status="paused", can=dict(CAN))
        np._changed(paused)
        np._changed(nxt)                          # playing again after a pause: no second popup
        assert not np.popup.isVisible() and win.now_bar.by.text().startswith("M83")

        np._changed(NowPlaying(app_id="Spotify.exe", title="Outro", artist="M83", status="playing"))
        assert np.popup.isVisible()
        np.popup.close_btn.click()                # the X
        assert not np.popup.isVisible()
        sent = []
        monkeypatch.setattr(np.watcher, "command", sent.append)
        win.now_bar.controls.next.click()
        win.now_bar.controls.play.click()
        assert sent == ["next", "toggle"]

        state.settings.media_popup = False
        np._changed(NowPlaying(app_id="Chrome", title="A video", artist="A channel", status="playing"))
        assert not np.popup.isVisible() and win.now_bar.by.text() == "A channel \u00b7 Google Chrome"
        np._changed(None)                         # nothing playing: the strip goes
        assert not win.now_bar.isVisibleTo(win)
    finally:
        win.now_playing.popup.dismiss()
        win.close()
        state.stop()
        pump(app, 0.1)
