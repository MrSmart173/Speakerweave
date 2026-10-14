# Releasing SpeakerWeave

How to turn the project into an installer other people can download, how updates reach
them, and how to get Windows to trust it.

## 1. One time preparation

Open `speakerweave/release.py` in Notepad and fill in:

* `PUBLISHER` : your name or business name. It is shown in the installer and in the
  Windows list of installed apps.
* `UPDATE_REPO` : where the app looks for newer versions (see section 3). Leave it empty
  until you have that place.

Then read `packaging/LICENSE_TEMPLATE.txt`. These are the licence terms people must
accept in the installer (no sharing or uploading the app elsewhere, no taking it apart,
no warranty, Queensland law). Your publisher name and the year are filled in at build
time. It is a starting point, not legal advice: have it checked before you sell the app.

## 2. Building the installer

Double click **Build installer.bat**. It does everything in one go:

1. turns the Python code into `SpeakerWeave.exe` (PyInstaller, downloaded automatically)
2. starts the finished .exe once in a hidden self test, and stops if anything is missing
3. wraps it into an installer with Inno Setup. The first time it offers to install
   Inno Setup for you (it is free)
4. writes the result to `dist\installer\SpeakerWeave-Setup-Beta-v1.0.exe` (named after the
   version, see below) together with a
   `.sha256` checksum file

The temporary build files go to `%LOCALAPPDATA%\SpeakerWeaveBuild`, outside this folder,
because a project inside OneDrive gets its files locked while they are being written.

Every build also puts the licence texts of all included components into a `licenses`
folder inside the app, with an overview in `THIRD PARTY NOTICES.txt`. Their licences
require this, so keep it in every release. The lights connection is our own code, so no
copyleft (GPL) library is included and your own code can stay closed.

What the installer does for the person installing:

* shows your licence terms, which must be accepted to continue
* asks whether to install for that user only (no admin rights needed) or for everyone
* lets them choose the install folder
* adds Start menu shortcuts and, if ticked, a desktop shortcut
* registers an uninstaller under Windows **Installed apps**
* when run over an older version, updates it in place and keeps their saved setup

## 3. Updates

The app can check for a newer version when it opens, and from **Setup > Check for
updates**. It needs one place on the internet to look. The simple free option is the
Releases page of a GitHub project:

1. Create a free account at https://github.com and a new **public** repository, for
   example `speakerweave`.
2. Put the name into `speakerweave/release.py`: `UPDATE_REPO = "yourname/speakerweave"`
3. Build the installer.
4. On GitHub open the repository, **Releases**, **Draft a new release**. As the tag type
   `v` plus the version number, for example `v1.0.0`, and as the title the version name,
   for example `SpeakerWeave Beta v1.0`. Write what changed in the description (the app
   shows this text to users). Attach the installer and its `.sha256` file. Publish.

Version numbers and names: the number lives in `speakerweave/__init__.py` (`1.0.0`) and is
what the update check compares, so tags always use it. People see the name made from it:
`STAGE` in `speakerweave/release.py` puts "Beta" in front, so `1.0.0` shows as "Beta v1.0"
in the window title, the About box, the installer and its file name. Set `STAGE = ""` when
SpeakerWeave leaves beta.

For every later version:

1. Raise the number in `speakerweave/__init__.py` (for example `1.0.0` to `1.1.0`).
2. Run **Build installer.bat**.
3. Publish a new GitHub release with the tag `v1.1.0`, the title `SpeakerWeave Beta v1.1` and
   the new installer attached.

Every installed copy then shows "SpeakerWeave Beta v1.1 is available", downloads the installer,
checks it against the checksum when GitHub lists one for the file, installs it over the old
version and starts again. A copy run from source (SpeakerWeave.bat) only offers a link to
the download page.

If you would rather host the files on your own website, set `UPDATE_FEED` instead. The
format is described at the top of `speakerweave/release.py`.

## 4. Including the virtual sound device (VB-CABLE)

Windows only shows an output device if a driver provides it, so the app needs a virtual
sound device to receive "everything this PC plays". VB-Audio allows the standard VB-CABLE
package to be shipped inside another app's installer, on these conditions (read their
page before publishing: https://vb-audio.com/Services/licensing.htm):

* users must be able to see that VB-CABLE is a VB-Audio product and donationware.
  The installer task and the About box of the app already say so
* a business that distributes it is asked to make a donation as a licence fee
* only the standard VB-CABLE may be bundled, not the A+B or C+D packs

To include it: download the driver pack from https://vb-audio.com/Cable/ and unzip it
into `third_party\VBCABLE` in this folder, so that
`third_party\VBCABLE\VBCABLE_Setup_x64.exe` exists. The next build notices it and adds a
ticked option "Install the VB-CABLE virtual sound device" to the installer. Without that
folder the installer is built without the option.

## 5. Getting Windows to trust it

An installer nobody has signed makes Windows show "Windows protected your PC" to everyone
who downloads it, and Smart App Control on Windows 11 can block it outright. There is no
form to submit an app for approval. Trust comes from a signature plus reputation that
builds as people install it. The routes, as of October 2026:

| Route | Cost | Open to you in Australia | Result |
| --- | --- | --- | --- |
| Microsoft Store, packaged as MSIX | free for individuals | yes | Microsoft signs it. No warnings at all |
| OV code signing certificate | about US$150 to 300 a year | yes | Your name shows as publisher. Warnings fade over some weeks as installs add up |
| SignPath Foundation | free | only if the project is open source | Same as an OV certificate |
| Azure Artifact Signing | about US$10 a month | no. Individuals only in the USA and Canada | Same as an OV certificate |
| EV certificate | US$400 and up a year | yes | No longer skips the warning (changed in 2024). Only needed for driver signing |
| No signature | free | yes | Warning on every new version |

### Route A: signing certificate (works with the installer as built today)

1. Buy an **OV code signing certificate** from a certificate authority such as Sectigo,
   DigiCert or SSL.com. As an individual you prove your identity with government ID. As a
   business you also prove the business exists.
2. The key arrives on a USB token (or in the provider's cloud). This is required since 2023.
3. Install the Windows SDK, which contains `signtool.exe`.
4. Open `packaging\build_settings.ini` and set `subject` to the exact name on the
   certificate, and `timestamp` to your provider's time stamp address.
5. Run **Build installer.bat** with the token plugged in. It signs `SpeakerWeave.exe` and
   the installer, and reports "Signed: yes".
6. Always sign every release with the same certificate. Reputation is tied to it.

Expect the warning to still appear for the first weeks. Microsoft describes it as needing
"several weeks and hundreds of clean installs" before it disappears.

### Route B: Microsoft Store

1. Register at https://storedeveloper.microsoft.com and choose **Individual developer
   (free)**. You verify with government ID and a selfie.
2. The app has to be packaged as MSIX, which is a different package from the installer in
   section 2. That packaging is not part of this project yet.
3. Microsoft tests the app, signs it, hosts it and delivers updates.

The catch for SpeakerWeave: a Store app cannot install a driver, so users would have to
install VB-CABLE themselves.

## 6. A driver of our own

What was found when looking into replacing VB-CABLE with our own driver:

* VB-CABLE is closed source. There is no code to build on, and its licence does not allow
  taking it apart. A driver of our own would start from Microsoft's open sample audio
  drivers (SimpleAudioSample or SysVAD in the windows-driver-samples project).
* It is written in C++ and built with Visual Studio and the Windows Driver Kit. It runs
  inside the Windows kernel, so a mistake means a blue screen, not an error message.
* Windows refuses to load a kernel driver unless Microsoft has signed it. For that you
  must join the Windows Hardware Developer Program, which is set up for registered
  businesses and requires an EV certificate (US$400 and up a year).
* Until then it can only be tested on a PC switched to test signing mode, which means
  turning Secure Boot off on that PC.

So it is possible, but it is a second project of its own with a business registration and
yearly costs behind it. The practical order is: ship with VB-CABLE now, and build our own
driver once the app has users and a business entity exists to sign it.

Sources:
* https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options
* https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation
* https://learn.microsoft.com/en-us/windows/apps/publish/whats-new-individual-developer
* https://learn.microsoft.com/en-us/windows-hardware/drivers/dashboard/code-signing-attestation
* https://learn.microsoft.com/en-us/windows-hardware/drivers/dashboard/hardware-program-register
* https://learn.microsoft.com/en-us/samples/microsoft/windows-driver-samples/simple-audio-sample-device-driver
* https://vb-audio.com/Services/licensing.htm
