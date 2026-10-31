"""The licence terms the installer shows: filled in, and saying what they must."""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "packaging"))
sys.path.insert(0, os.path.dirname(HERE))


def test_the_terms_are_filled_in_and_cover_what_they_must(tmp_path):
    import build
    from speakerweave import release
    text = open(build.render_terms(str(tmp_path)), encoding="utf-8").read()
    assert not re.search(r"\{[A-Z]+\}", text)                    # every blank filled in
    assert release.PUBLISHER in text and release.WEBSITE in text
    flat = " ".join(text.split()).lower()
    for must in ("licensed, not sold", "you do not buy or own the software",
                 "one person, on one computer", "do not give refunds if you simply change your mind",
                 "australian consumer law", "entirely at your own risk",
                 "damage to speakers, subwoofers, amplifiers", "laws of queensland, australia"):
        assert must in flat, must
