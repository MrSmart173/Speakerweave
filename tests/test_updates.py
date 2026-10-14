"""The update checker, tested without touching the internet."""
import hashlib
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from speakerweave import release, updates
from speakerweave.updates import (ReleaseInfo, UpdateError, download, fetch_latest, is_newer,
                                  parse_feed, parse_github_release, version_tuple)


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def opener_for(payload: bytes, seen=None):
    def opener(request, timeout=0):
        if seen is not None:
            seen.append(request.full_url)
        return FakeResponse(payload)
    return opener


def raises(fn, text=""):
    try:
        fn()
    except UpdateError as exc:
        assert text in str(exc), str(exc)
        return True
    raise AssertionError("expected an UpdateError")


def test_versions_compare_as_numbers_not_text():
    assert version_tuple("v1.10.2") == (1, 10, 2) and version_tuple("1.2") == (1, 2)
    assert version_tuple("nonsense") == ()
    assert is_newer("1.10.0", "1.9.3") and is_newer("v2.0", "1.99.99") and is_newer("1.2.1", "1.2")
    assert not is_newer("1.2.0", "1.2") and not is_newer("1.1.9", "1.2.0") and not is_newer("", "1.0")


def test_github_release_is_understood():
    data = {"tag_name": "v1.3.0", "body": "Faster start", "html_url": "https://github.com/a/b/releases/v1.3.0",
            "assets": [
                {"name": "notes.txt", "browser_download_url": "https://x/notes.txt"},
                {"name": "portable.exe", "browser_download_url": "https://x/portable.exe"},
                {"name": "SpeakerWeave-Setup-1.3.0.exe", "browser_download_url": "https://x/setup.exe",
                 "digest": "sha256:ABCDEF"}]}
    info = parse_github_release(data)
    assert info.version == "v1.3.0" and info.url == "https://x/setup.exe"
    assert info.sha256 == "abcdef" and info.filename == "SpeakerWeave-Setup-1.3.0.exe"
    assert info.notes == "Faster start" and info.page.endswith("v1.3.0")
    assert parse_github_release({"tag_name": "v1.3.0", "assets": []}).url == ""


def test_own_feed_is_understood():
    info = parse_feed({"version": "2.0.0", "url": "https://me.example/dl/Setup-2.0.0.exe?x=1",
                       "sha256": " AA11 ", "notes": "Big one"})
    assert info.version == "2.0.0" and info.filename == "Setup-2.0.0.exe" and info.sha256 == "aa11"


def test_checking_uses_the_configured_place_and_insists_on_https():
    old = (release.UPDATE_REPO, release.UPDATE_FEED)
    try:
        release.UPDATE_REPO, release.UPDATE_FEED = "", ""
        assert not updates.configured()
        raises(fetch_latest, "not set up")
        release.UPDATE_REPO = "someone/speakerweave"
        seen = []
        payload = b'{"tag_name": "v99.0.0", "assets": []}'
        info = fetch_latest(opener_for(payload, seen))
        assert seen == ["https://api.github.com/repos/someone/speakerweave/releases/latest"]
        assert info.version == "v99.0.0" and is_newer(info.version)
        release.UPDATE_REPO, release.UPDATE_FEED = "", "http://plain.example/latest.json"
        raises(lambda: fetch_latest(opener_for(payload)), "https")
        release.UPDATE_FEED = "https://me.example/latest.json"
        raises(lambda: fetch_latest(opener_for(b"[1, 2]")), "unexpected")
        raises(lambda: fetch_latest(opener_for(b'{"version": "soon"}')), "version")
        raises(lambda: fetch_latest(opener_for(b"not json")), "reach")
    finally:
        release.UPDATE_REPO, release.UPDATE_FEED = old


def test_download_checks_the_file_before_keeping_it():
    payload = os.urandom(700_000)
    good = hashlib.sha256(payload).hexdigest()
    folder = tempfile.mkdtemp()
    steps = []
    info = ReleaseInfo("1.3.0", "https://x/SpeakerWeave-Setup-1.3.0.exe", good.upper(),
                       filename="SpeakerWeave-Setup-1.3.0.exe")
    path = download(info, folder, progress=lambda done, total: steps.append((done, total)),
                    opener=opener_for(payload))
    assert os.path.basename(path) == "SpeakerWeave-Setup-1.3.0.exe"
    assert open(path, "rb").read() == payload
    assert steps[-1] == (len(payload), len(payload)) and len(steps) >= 2

    bad = ReleaseInfo("1.3.0", "https://x/setup.exe", "0" * 64, filename="evil.exe")
    raises(lambda: download(bad, folder, opener=opener_for(payload)), "checksum")
    assert not os.path.exists(os.path.join(folder, "evil.exe"))
    assert not os.path.exists(os.path.join(folder, "evil.exe.part"))

    raises(lambda: download(ReleaseInfo("1.3.0", ""), folder), "no installer")
    raises(lambda: download(ReleaseInfo("1.3.0", "http://x/setup.exe"), folder), "https")
    odd = ReleaseInfo("1.3.0", "https://x/y", filename="..\\\\..\\\\run me.bat")
    path = download(odd, folder, opener=opener_for(b"abc"))
    assert os.path.dirname(path) == folder and path.endswith(".exe")     # stays in the folder


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok   ", name)
