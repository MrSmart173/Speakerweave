"""Looks for a newer version of the app and fetches its installer.

Nothing in here touches the window, so it can be tested without one.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.request
from dataclasses import dataclass

from . import __version__, release

TIMEOUT = 10            # seconds
MAX_INSTALLER_BYTES = 1_500_000_000


class UpdateError(Exception):
    pass


@dataclass
class ReleaseInfo:
    version: str
    url: str = ""           # direct download of the installer, "" if the release has none
    sha256: str = ""        # expected checksum of the installer, "" if not published
    notes: str = ""
    page: str = ""          # web page of the release
    filename: str = ""


def version_tuple(text: str) -> tuple:
    """"v1.2.0" -> (1, 2, 0). Anything after the numbers is ignored."""
    match = re.match(r"\s*[vV]?(\d+(?:\.\d+)*)", text or "")
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(candidate: str, current: str = __version__) -> bool:
    a, b = version_tuple(candidate), version_tuple(current)
    if not a:
        return False
    size = max(len(a), len(b))
    return a + (0,) * (size - len(a)) > b + (0,) * (size - len(b))


def configured() -> bool:
    return bool(release.UPDATE_REPO.strip() or release.UPDATE_FEED.strip())


def source_url() -> str:
    if release.UPDATE_FEED.strip():
        return release.UPDATE_FEED.strip()
    if release.UPDATE_REPO.strip():
        return f"https://api.github.com/repos/{release.UPDATE_REPO.strip()}/releases/latest"
    return ""


def _require_https(url: str) -> str:
    if not url.lower().startswith("https://"):
        raise UpdateError("The update address is not a secure (https) address.")
    return url


def parse_github_release(data: dict) -> ReleaseInfo:
    """Reads the answer of GitHub's "latest release" request."""
    info = ReleaseInfo(version=str(data.get("tag_name") or data.get("name") or ""),
                       notes=str(data.get("body") or ""), page=str(data.get("html_url") or ""))
    assets = [a for a in data.get("assets") or [] if str(a.get("name", "")).lower().endswith(".exe")]
    assets.sort(key=lambda a: "setup" not in str(a.get("name", "")).lower())   # setup files first
    if assets:
        asset = assets[0]
        info.url = str(asset.get("browser_download_url") or "")
        info.filename = str(asset.get("name") or "")
        digest = str(asset.get("digest") or "")
        if digest.lower().startswith("sha256:"):
            info.sha256 = digest.split(":", 1)[1].strip().lower()
    return info


def parse_feed(data: dict) -> ReleaseInfo:
    """Reads your own JSON file (see release.py)."""
    url = str(data.get("url") or "")
    return ReleaseInfo(version=str(data.get("version") or ""), url=url,
                       sha256=str(data.get("sha256") or "").strip().lower(),
                       notes=str(data.get("notes") or ""), page=str(data.get("page") or ""),
                       filename=os.path.basename(url.split("?")[0]))


def fetch_latest(opener=urllib.request.urlopen) -> ReleaseInfo:
    """Asks the configured place for the newest release."""
    url = source_url()
    if not url:
        raise UpdateError("Updates are not set up for this copy of the app.")
    _require_https(url)
    request = urllib.request.Request(url, headers={
        "User-Agent": f"{release.APP_NAME}/{__version__}", "Accept": "application/vnd.github+json"})
    try:
        with opener(request, timeout=TIMEOUT) as response:
            data = json.loads(response.read(2_000_000).decode("utf-8"))
    except UpdateError:
        raise
    except Exception as exc:
        raise UpdateError(f"Could not reach the update server ({exc}).") from exc
    if not isinstance(data, dict):
        raise UpdateError("The update server sent something unexpected.")
    info = parse_feed(data) if release.UPDATE_FEED.strip() else parse_github_release(data)
    if not version_tuple(info.version):
        raise UpdateError("The update server did not name a version.")
    return info


def check() -> ReleaseInfo | None:
    """The newest release if it is newer than this copy, otherwise None."""
    info = fetch_latest()
    return info if is_newer(info.version) else None


def download(info: ReleaseInfo, folder: str = "", progress=None,
             opener=urllib.request.urlopen) -> str:
    """Saves the installer and returns its path. progress(done, total) is called
    as it goes (total is 0 when the server does not say). The file is checked
    against the published checksum when there is one."""
    if not info.url:
        raise UpdateError("This release has no installer attached.")
    _require_https(info.url)
    folder = folder or os.path.join(tempfile.gettempdir(), f"{release.APP_NAME} update")
    os.makedirs(folder, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9._ ()-]", "_", info.filename or "") or f"{release.APP_NAME}-Setup.exe"
    if not name.lower().endswith(".exe"):
        name += ".exe"
    path = os.path.join(folder, name)
    partial = path + ".part"
    digest = hashlib.sha256()
    request = urllib.request.Request(info.url, headers={"User-Agent": f"{release.APP_NAME}/{__version__}"})
    try:
        with opener(request, timeout=TIMEOUT) as response, open(partial, "wb") as out:
            total = int(response.headers.get("Content-Length") or 0) if hasattr(response, "headers") else 0
            done = 0
            while True:
                chunk = response.read(262144)
                if not chunk:
                    break
                done += len(chunk)
                if done > MAX_INSTALLER_BYTES:
                    raise UpdateError("The download is far larger than an installer should be.")
                out.write(chunk)
                digest.update(chunk)
                if progress:
                    progress(done, total)
    except UpdateError:
        _remove(partial)
        raise
    except Exception as exc:
        _remove(partial)
        raise UpdateError(f"The download did not finish ({exc}).") from exc
    if info.sha256 and digest.hexdigest().lower() != info.sha256.lower():
        _remove(partial)
        raise UpdateError("The downloaded file does not match its published checksum, "
                          "so it was thrown away.")
    os.replace(partial, path)
    return path


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def launch_installer(path: str) -> None:
    """Starts the installer in its short "updating" form. It closes the running
    app, installs over it and starts the new version."""
    arguments = "/SILENT /CLOSEAPPLICATIONS /NOCANCEL"
    if hasattr(os, "startfile"):
        os.startfile(path, "open", arguments)       # Windows asks for admin rights if needed
    else:
        raise UpdateError("Installers can only be started on Windows.")
