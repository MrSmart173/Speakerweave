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
