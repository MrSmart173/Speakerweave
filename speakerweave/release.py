"""Facts about how this app is published. Edit these before building an installer.

UPDATE_REPO   the GitHub project whose Releases page holds your installers, written
              as "owner/name", for example "elismart/speakerweave". The app asks
              GitHub for the newest release there and offers it to the user.
UPDATE_FEED   alternative to UPDATE_REPO: the https address of a small JSON file on
              your own website, shaped like
              {"version": "1.2.0", "url": "https://.../SpeakerWeave-Setup-1.2.0.exe",
               "sha256": "...", "notes": "What changed", "page": "https://..."}
Leave both empty and the app simply says that updates are not set up.
"""

APP_NAME = "SpeakerWeave"
PUBLISHER = "Eli Smart"             # shown in the installer and in Windows "Apps"
WEBSITE = "https://github.com/MrSmart173/Speakerweave"   # optional, shown in the installer

UPDATE_REPO = "MrSmart173/Speakerweave"
UPDATE_FEED = ""

# Shown before the version number: "Beta v1.0". Set it to "" once SpeakerWeave leaves
# beta. The number itself is __version__ in speakerweave/__init__.py, and every GitHub
# release is tagged with it, for example v1.0.0, so the update check can compare them.
STAGE = "Beta"


def version_name(version: str = "") -> str:
    """How a version is shown to people: "1.0.0" becomes "Beta v1.0", "1.2.1" "Beta v1.2.1"."""
    from . import __version__
    parts = (version or __version__).strip().lstrip("vV").split(".")
    while len(parts) > 2 and parts[-1] == "0":
        parts.pop()
    short = "v" + ".".join(parts)
    return f"{STAGE} {short}" if STAGE else short
