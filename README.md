# SpeakerWeave

One sound source in, as many sound outputs as you like out, arranged as one surround system.

Every channel of every output (the left speaker of the left TV, the right speaker of the middle
monitor, a subwoofer on a sound card and so on) is treated as its own speaker. You give each one
a role (front left, side right, rear left, subwoofer ...), place it on a map of your room, and
shape its sound.

## What it can do

* Modes from 2.0 up to 7.1 (2.0, 2.1, 3.0, 3.1, 4.0, 4.1, 5.0, 5.1, 6.0, 6.1, 7.0, 7.1)
* 4.0, 4.1, 5.0 and 5.1 with the surround pair at your sides (SL SR) or behind you (RL RR)
* Custom: tick any combination of positions, with up to four subwoofers
* Any channel of any output can play any role. Several speakers may share a role
* Room map: drag screens, loose speakers and your own seat to where they really are
* Drag the rim of a single speaker to move it along one direction, with an optional Mirror
  mode that moves its partner on the other side to match
* Roles can be filled in for you from the positions on the map
* Screens with no speakers of their own: mark the output as "separate speakers plugged into
  its aux, headphone or line out" and place those speakers freely
* Frequency limits per speaker (for example a subwoofer that only plays 10 to 75 Hz), with
  ready made speaker types from tweeters to bass shakers
* A built in library of common TVs, monitors, speaker systems, studio monitors, headsets and
  sound cards. Recognised outputs get a matching preset as soon as you tick them
* Test sounds on a single speaker: right click it on the map, or select it and press Space.
  Add up to five sounds of your own (WAV, MP3, M4A, WMA, FLAC and more)
* Solo a speaker and every other one shows as muted on the map. Muted speakers hand their part
  to the speakers still playing, and a soloed speaker plays the whole sound
* Sweeps that glide a sound round the room (360°) or across the front speakers
* Now playing: the song or video playing on the PC (Spotify, Apple Music, YouTube and more)
  under the map with play, pause and skip, and a popup that closes itself after 5 seconds
* Microphones on the room map, placed where they really are, glowing with what they hear
* A Performance page with SpeakerWeave's share of the processor and memory, how hard the
  sound work runs, delay, dropouts and a two minute chart
* Colour themes: six presets, or your own colours, also straight from Adobe Color
* Plays by itself as soon as it opens, and makes itself the Windows sound output while it
  plays. Stop it and Windows gets its old output back
* Sets the virtual sound device to 7.1 by itself, so games send real surround. Music and
  other stereo sound is spread over every speaker until surround arrives
* Units with more than two channels (a Logitech Z906, a 5.1 sound card) show as a ring of
  their own speakers with the subwoofer beside it. Every speaker can be attached to its unit
  or loose, and switching back and forth keeps the loose places
* Level meters like a mixer: one block for the PC sound and one per output, with a bar for
  every channel
* An Errors page that lists anything keeping the sound from your speakers or spoiling the
  surround, each with a button that fixes it. The Errors button flashes red for an error and
  lights yellow for a new warning, and a note at startup sums up what is wrong
* Bass shakers (ButtKicker and other tactile transducers) as a speaker role, limited to the
  low frequencies and fed by the game's bass, by effects, or both
* Extra sound sources played on top of the game sound, such as SimHub's ShakeIt effects
  (tyres, impacts, gear shifts) or a spotter app, each channel sent to the speakers you pick
* A SimHub plugin: SpeakerWeave loads the speaker setup you chose for each game, and SimHub
  buttons and dashboards can control SpeakerWeave
* A tour of the whole window the first time it opens
* Controls: keys, game controller, racing wheel and button box buttons, and Stream Deck links
  for volume, mute, modes, setups and more, working while a game is in front
* Settings: start with Windows, start hidden in the tray, keep running in the tray
* A list of the Bluetooth devices paired with the PC
* Parametric equaliser per speaker, up to 16 bands, with a live response graph
* Volume, delay, mute, solo and polarity per speaker, plus volume and delay per output
* Bass from every channel can also be sent to the subwoofer
* Stereo sources can be spread over all speakers, surround sources are folded down to
  whatever speakers you have, so no channel is ever lost
* Keeps outputs with different clocks in step with each other
* RGB lights per speaker through OpenRGB: steady, pulsing with the sound, level meter, rainbow
* Your setup is saved automatically, and can be saved under a name and opened again

## Installing (Windows 10 or 11)

**With the installer.** Run `SpeakerWeave-Setup-Beta-v1.0.exe` (or the newest one on the
[Releases page](https://github.com/MrSmart173/Speakerweave/releases)), choose where to install, and
start SpeakerWeave from the Start menu. Nothing else is needed. The app looks for newer
versions by itself when it opens and every six hours. When one is out, a note appears by the
**Errors** button and the Errors page lists it under **Notices**, with what's new and a
button that installs it. **Setup > Check for updates** looks right away.

**From this folder, for development.**

1. Install Python 3.12 or newer from https://www.python.org/downloads/ and tick
   **Add python.exe to PATH** on the first page of the installer.
2. Double click **Install.bat**. It downloads the libraries into this folder only.
3. Start the app with **SpeakerWeave.bat**.

If the app does not open, start **SpeakerWeave (show messages).bat** instead. It shows the
error text. Errors are also written to `error log.txt` in
`%LOCALAPPDATA%\SpeakerWeave`.

To build the installer yourself, see `RELEASING.md`.

## First steps: map your speakers

The first time SpeakerWeave opens, a short tour shows where everything is. Take it again any
time from **Setup > Take the tour**.

You can do all of this before setting up anything else, using the built in test signal.

1. In the list on the left, tick every sound output you want to use (your three TVs, a
   sound card and so on). Each one appears on the room map.
2. Pick the **Mode** at the top (for example 5.1), or press **Positions** to tick exactly
   the speaker positions your room has (see below).
3. Drag the screens and the **You** marker to where they are in your room. Scroll over a
   screen to turn it. The faint ring around you shows the ideal spot for each role.
4. Press **Set roles**, or click each speaker and choose its **Role** by hand.
5. Leave **Listen to** on **Test signal** and press **Start**. A noise walks from channel to
   channel, and the speaker that should be playing gets a white ring on the map. If the wrong
   speaker makes the noise, change its role. **Identify** (or a double click on the map)
   plays a noise on one speaker only.

### Hiding outputs you don't use

Right click an output in the list and choose **Hide this output**. It moves into **Hidden by
user**, a folder at the bottom of the list, and leaves the map, every saved setup and the
Errors page alone. Its place on the map and its settings are kept. Right click it there and
choose **Show this output again** to bring it back as it was.

When a hidden output is plugged in again, the folder flashes and a note says the device has
been found again: **Activate device** brings it back ticked, **Ignore** leaves it hidden and
asks again next time, and **Ignore and don't show again** never asks about it again.

### Side or rear surround, and custom positions

4.0, 4.1, 5.0 and 5.1 appear twice in the Mode list: once with the surround pair beside you
(**side pair SL SR**) and once behind you (**rear pair RL RR**). Switching between the two
moves the speakers of that pair along, so you do not have to set their roles again. A 5.1
source played on a rear pair setup sends its surround channels to the rear speakers.

For anything else, choose **Custom...** at the bottom of the Mode list or press **Positions**.
Tick any combination of front left, centre, front right, side left, side right, rear left,
rear centre and rear right, and choose 0 to 4 subwoofers. A choice that matches a standard
mode becomes that mode, everything else is shown as Custom with the usual numbering (for
example **Custom 4.2** for four speakers and two subwoofers). Sound meant for a position you
do not have is folded into the nearest positions you do have, so nothing goes missing.
Every subwoofer plays the same bass, and each one keeps its own delay and equaliser.

### Moving single speakers and Mirror

Hover over the rim of a speaker on the map and four small arrows appear. Drag the left or
right rim to move only that speaker sideways, or the top or bottom rim to move it only
forward and back. For a screen with built in speakers this stretches and turns the screen
while its other end stays where it is.

Press **Mirror** under the map and the partner speaker follows: the opposite way sideways,
the same way front to back. So a sideways drag changes the spacing evenly on both sides,
and a front to back drag moves both ends together.

The numbers under **Position in the room** follow while you drag, on the Output tab for a
whole screen and on the Speaker tab for a single speaker. You can also type exact values
there.

Your example from the request, three TVs in a row, looks like this in mode 6.0:

| Output | Left channel | Right channel |
| --- | --- | --- |
| Left TV | Rear left | Side left |
| Middle TV | Front left | Front right |
| Right TV | Side right | Rear right |

## Playing the sound of your PC through it

SpeakerWeave needs one place to listen to: a virtual sound device that Windows plays into,
and that makes no sound by itself.

1. Install the free **VB CABLE** driver (the SpeakerWeave installer offers it, or get it from
   https://vb-audio.com/Cable/) and restart the PC.
2. Open SpeakerWeave and tick your outputs. That is all.

When SpeakerWeave opens it renames VB CABLE's output (CABLE Input) to **SpeakerWeave Virtual
Speaker output**, so Windows' lists say what it is for (Windows adds "VB-Audio Virtual Cable"
in brackets itself). It listens to it, sets it to 7.1 so games send real surround channels,
makes it the Windows sound output and starts the sound. Everything Windows plays
then arrives in SpeakerWeave and is spread over your speakers. Press **Stop**, or quit, and
Windows goes back to the output it used before.

While only the two front channels carry sound (music, most videos), SpeakerWeave spreads them
over every speaker. As soon as a game sends surround, each channel goes to its own speaker.
The **Errors** page shows which of the two is happening right now.

If a game or app lets you choose its sound output, choose **SpeakerWeave Virtual Speaker
output**. Uninstalling SpeakerWeave gives the device its own name back, and **Call the virtual
device "SpeakerWeave Virtual Speaker output"** on the Settings page switches the renaming off.

## Now playing

When music or a video plays on the PC (Spotify, Apple Music, YouTube in a browser, or any app
that Windows' own media controls show), its title, artist and picture appear in a strip under
the map, with previous, play or pause, and next. When a new song or video starts, a small
popup shows it in the corner of the screen. It closes itself after 5 seconds (it waits while
the mouse is on it), or straight away with its X. Both can be switched off on the Settings
page under **Now playing**.

Each step can be switched off on the **Settings** page under **Windows sound output**, and
**Listen to** at the top can be set by hand. You can listen to a normal output device instead
of a virtual one, but then that device still plays the original sound itself and cannot be
used as part of the setup. A recording device (line in, a capture card, a microphone) can be
the source as well.

## Units with more than two channels

A unit with more than two channels, such as a Logitech Z906, a 5.1 or 7.1 sound card or an
AV receiver, shows on the map as a ring of its own speakers in their surround places, with
its subwoofer off to the left. When you tick it, the mode follows its channels (5.1 for six,
7.1 for eight). Drag the ring to move the whole unit, and set how big it is with **Size
across** on the Output tab.

Select a unit and press **Speakers attached** at the top right of the map (or right click it) to
switch to **Speakers loose**. Every speaker can then be dragged on its own. Press it again
and the speakers snap back to the unit, while the unit stays where it is. Loosen them once
more and they return to the places you gave them before. This works the same for a screen or
soundbar with its two speakers.

Some outputs tell Windows they are 7.1 (or 5.1) when they are not: the Logitech G560,
gaming headsets whose software turns on virtual surround (Logitech G HUB, Corsair iCUE, Razer
Synapse), and PC soundbars such as the Creative Katana V2. When SpeakerWeave recognises one
by its name, it shows what is really there: a headset's two sides, or two speakers and a
subwoofer, in front of you. The mode stays as it was and the other channels are left silent.
To use every channel Windows offers anyway, set **Speaker model** on the Output tab to
**Not chosen**. A TV, receiver or sound card keeps every channel: when those offer 5.1 or
7.1, the speakers are really there.

## Level meters

**Levels** under the map shows meters like the mixer in OBS: the first block is the PC sound
coming in, and every ticked output has its own block with a bar for each channel, labelled
L and R, or FL, FR, C, SUB and so on for surround. Green is comfortable, yellow is loud, red
is close to clipping. The thin line above each bar holds the latest peak for a moment.

## Errors

The **Errors** button at the top shows a number when something is wrong. While there is an
error it flashes red (it stays steady while the Errors page is open). A new warning lights it
yellow for a second, then it goes back to your colours. When SpeakerWeave opens with
something wrong, a note under the button sums it up, with **Go to Errors** or **Ignore**. The page lists
everything that keeps the sound from your speakers (no virtual device, Windows playing
somewhere else, an output unplugged, a device refusing to open) and everything that spoils
the surround (the virtual device set to stereo, missing speaker positions), each with a
button that fixes it where SpeakerWeave can. **Run a full sound check** sends a silent test
tone through the whole chain, from Windows to every speaker, and reports where it stops.

## Bass shakers and effects

Give a ButtKicker or any other tactile transducer the role **Bass shaker** (Speaker tab, or
right click it on the map). It is limited to 10 to 80 Hz, plays no part in the speaker mode,
and keeps its role when you change modes. Picking a ButtKicker or Dayton model on the Output
tab does this for you.

The **Effects** tab sets what the shakers feel: the game's bass (with its own level), the
effects sent to them, or both.

### Sending effects and other sounds to chosen speakers

Games mix all their sounds into one before Windows gets them, so tyres or the spotter cannot
be pulled back out of the game sound. What can be sent to chosen speakers is sound that
arrives separately:

* **SimHub's ShakeIt effects.** SimHub makes them from the game's data (tyre slip, road
  texture, impacts, gear shifts, engine). In SimHub, open **ShakeIt Bass shakers**, choose a
  second virtual device as its output (for example VB CABLE A, or VoiceMeeter), and give each
  effect group its own channel.
* **A spotter, voice chat or music app.** In Windows, open **Settings > Sound > Volume
  mixer** and set that app's output to a virtual device.

On the **Effects** tab press **Add a source**, choose the device it plays into, and send each
of its channels to any speakers and shakers, with its own name and level. **Give it 8
channels** sets a virtual device to 7.1, so ShakeIt can use eight separate channels. All of
it plays on top of the game sound, so a speaker can play the game, the spotter and the tyres
at the same time.

## SimHub

SpeakerWeave comes with a plugin for SimHub (https://www.simhubdash.com):

1. Open the **Effects** tab and press **Install the SimHub plugin**. Close SimHub first, and
   say yes when Windows asks to allow the change (SimHub lives in Program Files).
2. Start SimHub and say yes when it asks to enable the SpeakerWeave plugin.

The Effects tab then shows **Connected**. Every game SimHub has seen gets a line under
**Speaker setup for each game**: choose a saved setup for it, or set your speakers up for
that game and press **Use current**. When SimHub sees the game start, SpeakerWeave loads
that setup with its speakers, volumes and effects. **No game running** sets the setup for
when you leave the game. Changes you make while a game runs are kept in that game's setup.

In SimHub, **Controls and events** lists SpeakerWeave's actions (start or stop, volume,
mute, modes, bass, setup slots) for wheel and button box buttons, and dashboards can show
SpeakerWeave's state through properties such as `SpeakerWeavePlugin.VolumeDb`,
`SpeakerWeavePlugin.Muted` and `SpeakerWeavePlugin.Mode`.

The plugin only sends something when the game changes and asks for SpeakerWeave's state
every two seconds, so it costs SimHub nothing noticeable. It talks to SpeakerWeave on this
PC only, with the secret code from SpeakerWeave's settings.

## Screens whose sound comes out of an aux jack

Windows sees a TV or monitor as one sound output, whether the sound leaves through its own
speakers or through its headphone or aux jack. So:

1. Tick the screen in the list like any other output.
2. Click it on the map, open the **Output** tab and set **Where the sound comes out** to
   **Separate speakers plugged into its aux, headphone or line out**.
3. The two speakers come loose from the screen on the map. Drag each one to where it stands.

If a monitor has neither speakers nor an audio jack, Windows usually does not list it as a
sound output at all, and then there is nothing for the app to send sound to.

## Performance

The **Performance** page shows how much of the PC SpeakerWeave uses: its share of the
processor and of the memory, how much of each block's time the sound work takes (above 70%
the sound can start to break up), the delay SpeakerWeave adds, dropouts, and how busy the PC
is as a whole. A chart shows the last two minutes (point at it to read a moment), and a list
shows how every output is keeping up.

## Microphones

Every microphone of the PC is listed under **Microphones** at the bottom of the list on the
left. Tick one and it appears on the room map in front of you: drag it to where it really is
around your setup. It glows with what it hears, and clicking it shows how far it is from you
and in which direction. Right click it to rename it, untick it, or take it off the map. Only
the microphones you tick are opened, and only to show their level: nothing is recorded.

## Hearing one speaker

Right click a speaker on the map and choose a short noise or a sweep from low to high, or
select it and press Space, or use **Test sound**. This works even while the sound is
stopped: SpeakerWeave starts it for the test and stops it again. The sweep is the easiest
way to hear where a speaker's frequency limits are.

**Test sound** also has two sweeps that use every speaker:

* **Sweep round the room (360°)**: a sound goes round you clockwise from straight ahead,
  twice, gliding from speaker to speaker
* **Sweep from left to right (front speakers)**: the sound glides across the speakers in
  front of you and back, twice

A sweep should move smoothly. A jump, a gap or a speaker that stands out points at its place
on the map, its volume or its delay. The PC sound waits while a sweep plays.

### Mute and solo

**Mute** takes a speaker out of the system: what it would have played moves to the nearest
speakers that are still playing, so nothing goes missing from the music. **Solo** plays the
whole sound on the soloed speakers only (one soloed speaker gets everything, no louder than
one channel), which is the quickest way to hear what a single speaker adds.

### Your own test sounds

On the **Settings** page, under **Your own test sounds**, choose up to five sound files: a
voice saying "left", a favourite piece of music, anything. WAV, MP3, M4A, WMA, FLAC and other
files Windows can play are accepted. SpeakerWeave keeps its own copy (up to 30 seconds, quiet
parts at the start and end trimmed), so the original file can be moved or deleted. Your
sounds then appear next to the noise and the sweep wherever you can play a test sound.

## Speaker types and the speaker library

On the **Speaker** tab, **Speaker type** fills in a sensible frequency range for that kind
of speaker: subwoofers, bass shakers, floor standing, 8, 6.5, 5 and 3 inch monitors,
soundbars, TV speakers, small desktop and portable speakers, tiny monitor speakers,
midrange drivers and tweeters. They are starting points, fine tune them by ear.

SpeakerWeave also recognises many outputs by the name Windows gives them (TVs, monitors,
Logitech, Creative, Razer and SteelSeries speaker systems, headsets, AV receivers, soundbars
and audio interfaces). When you tick one, its preset is filled in. Speakers on an ordinary
audio jack cannot be seen by Windows, so pick their model on the **Output** tab under
**Speaker model** (Yamaha HS, KRK Rokit, JBL 3 Series, PreSonus Eris, Edifier, Audioengine,
Kanto, Mackie, M-Audio, ButtKicker and more, or simply the woofer size).

## Controls

The **Controls** page (top right) gives actions a key or a button:

* **Keys** work everywhere, also while a game is in front.
* **Controller, wheel or button box** buttons and hat switches, read while a game is in front.
* **Stream Deck**: give a Stream Deck key a keyboard shortcut, or switch on links and use the
  Website action with "GET request in background". Touch Portal, SimHub and similar tools
  can use the same links.

Actions: start or stop the sound, volume up and down, mute, next and previous mode, bass to
the subwoofer, fill every speaker, test signal, lights, show or hide the window, load setup
slots 1 to 4, and mute or unmute each output.

## Settings

The **Settings** page has: start with Windows, start hidden in the system tray, start the
sound as soon as SpeakerWeave opens (on from the start), keep running in the tray when the
window is closed, watch for sound outputs
being plugged in, fill in presets for recognised outputs, level meters on the map, colours,
your own test sounds, update checks and the About section.

### Making SpeakerWeave the Windows sound output

The Windows volume works as you would expect: the volume keys of a keyboard, the volume
wheel of a mouse or headset and the Windows volume slider turn your speakers up and down,
and muting Windows mutes them. **Follow the Windows volume and mute** switches this off.

**Make SpeakerWeave the main sound output of Windows** is on from the start. While the sound
plays, Windows plays into the device SpeakerWeave listens to (SpeakerWeave Virtual Speaker
output). If
Listen to is still on the test signal, a virtual sound device is picked for you. With
**Start SpeakerWeave when Windows starts** on as well (the installer offers it), this happens
each time the PC boots. When the sound stops or SpeakerWeave quits, Windows goes back to the
output it used before, unless you switch that off or picked another output yourself in the
meantime. **Set the virtual device to 7.1** (also on from the start) is what makes games send
surround.

### Colours

Under **Look**, pick one of six themes: Midnight (the default), Ember, Forest, Neon, Amber
and Daylight (a light one). They were picked with the colour harmony rules of Adobe Color.
**Your own colours** lets you set the background, panels, lines, text and accent yourself.
To use a theme from Adobe Color (color.adobe.com), copy its five colour codes and paste them
in, or load a theme saved as an .ase file. SpeakerWeave arranges them so text stays readable,
and you can change each colour afterwards.

## Bluetooth

**Bluetooth devices** under the output list shows what is paired with the PC and opens the
Windows Bluetooth settings for pairing and connecting. Connected Bluetooth speakers and
headphones appear in the output list like any other output. Bluetooth adds a noticeable
delay, so add Extra delay to the other outputs to line them up.

## Frequency limits and subwoofers

Select a speaker and look at **Frequency range**:

* **Nothing below** cuts everything under the given frequency
* **Nothing above** cuts everything over the given frequency
* The slope sets how sharply the cut happens

Giving a speaker the role **Subwoofer (LFE)** switches both limits on at 10 and 75 Hz for
you. Change the numbers, or drag the two orange lines in the graph, to taste. The
**Small speaker** button does the opposite and keeps deep bass away from a tiny speaker.

On the **Sound** tab, **Send the bass of every channel to the subwoofer as well** makes the
subwoofer useful for stereo music too, not only for the dedicated bass channel of films
and games.

**Nothing below** hands a speaker's lowest notes to the subwoofer. While no subwoofer is
playing, those notes would simply be lost and the sound turns thin, so the limit waits until
there is one (the Speaker tab says so). **No subwoofer playing: every speaker keeps its lows**
on the Sound tab switches this off.

## Equaliser

Each speaker has its own. Drag a dot up or down to boost or cut, left or right to change
the frequency, and scroll over it to make it wider or narrower. Exact numbers can be typed
below the graph. Double click empty space for a new band, double click a dot to reset it.
**Copy** and **Paste** carry the equaliser and frequency range from one speaker to another.

## Timing

Every speaker plays a little late, and each by a different amount: Bluetooth and TVs add
their own lag, and sound takes about 3 ms to travel each metre. The tools under the map line
them up so every speaker's sound reaches your seat together.

* **Easy sync** walks you through it by ear. Two speakers at a time tick together. The click
  seems to come from the speaker that plays first, so add delay to that one, a little at a
  time, until you hear a single click from between the two. Then the next pair, until every
  speaker has been matched (subwoofers come last, with a low thump instead of a click). At
  the end, the speaker that needed the least delay is set to 0 ms and the same amount comes
  off all the others, so everything plays as early as possible. **Cancel** puts every delay
  back as it was.
* **Metronome** ticks on your speakers: every speaker together (one crisp click means they
  are in time), one speaker after another round the room (the clicks should be perfectly
  even), or only the selected one. Change the tempo in its menu. The PC sound waits while
  it ticks.
* **Line up delays** delays the nearer speakers, from the distances on the map, so all of
  them reach your seat at the same moment. Good as a first step before Easy sync.
* TVs process sound for a while before playing it, and every model takes a different time.
  The app cannot measure that. If one screen is ahead of the others (you hear an echo or
  a doubled sound), select it, open the **Output** tab and raise **Extra delay** until the
  echo closes up. Game mode on the TV usually shortens its lag.
* The **Safety buffer** on the Sound tab is extra delay the app adds on purpose. It starts at
  0 ms, the least delay possible: SpeakerWeave then keeps only the room your sound cards
  need to play cleanly (about 20 to 25 ms for most), and adds a few milliseconds by itself if
  one runs dry. All outputs keep the same delay, so they stay in line. The status line at the
  bottom shows the delay in use. Raise the buffer only if you still hear crackles.

## Lights

RGB hardware is driven through OpenRGB (free, https://openrgb.org), which supports most
motherboard headers, LED controllers and RGB peripherals.

1. Open OpenRGB and check it can see and control your lights.
2. In OpenRGB go to **SDK Server** and press **Start Server**.
3. In SpeakerWeave open the **Lights** tab and press **Connect**.
4. Select a speaker. In its **Lights** section pick the light (or the zone of a controller)
   that belongs to it, an effect and a colour.

Speakers whose lights only connect to their own remote or their own app, and that OpenRGB
does not know, cannot be controlled.

## Uninstalling

**Settings > Uninstall > Uninstall SpeakerWeave** removes SpeakerWeave completely. First
Windows gets a normal sound output back (the one it used before SpeakerWeave, or one of your
speakers), so the PC is never left playing into the virtual device. Then SpeakerWeave closes
and its uninstaller removes the program, the shortcuts, the start with Windows entry and the
SpeakerWeave plugin in SimHub (close SimHub first). With **Also delete my settings, speaker
setups, game setups and test sounds** ticked, the folder holding them goes too. Setups you
saved somewhere else yourself are kept.

Uninstalling from Windows Settings, Apps does the same, and asks about your settings folder.
VB-CABLE stays installed, as other apps may use it too.

## If something does not work

Start with the **Errors** page: it names the problem and usually has a button that fixes it.

| What you see | What to try |
| --- | --- |
| An output is missing from the list | Press **Rescan**. Check that Windows lists it under sound outputs |
| "not connected right now" after Start | That output is off or unplugged. Untick it or switch it on |
| No sound at all | Open the **Errors** page and press the button on the first card |
| No sound, status says waiting for sound | Nothing is playing into the device you listen to. The Errors page shows where Windows plays |
| Only stereo arrives from a game | Press **Set it to 7.1** on the Errors page, then restart the game |
| SimHub says nothing about SpeakerWeave | Install the plugin from the Effects tab, restart SimHub and enable it |
| Crackles or dropouts | Raise the Safety buffer. Close heavy programs |
| Echo between two screens | Use Extra delay on the earlier one |
| The list has no "Everything this PC plays on" entries | Run Install.bat again, the PyAudioWPatch library is missing |
| A setup cannot be saved where you chose | Windows' Controlled folder access protects Documents and OneDrive. SpeakerWeave saves it in its own Setups folder instead and says where |
| The sound is thin or tinny | A speaker's **Nothing below** cut is on with no subwoofer playing. Keep **No subwoofer playing: every speaker keeps its lows** ticked on the Sound tab |
| Mute or solo sounds odd | Speakers on different outputs can be out of step. Use **Easy sync** under the map |

## What has been tested

The mixing, filters, equaliser, delay, clock correction, room geometry and the whole window
are covered by automatic tests (`Run tests.bat`), including a run against simulated sound
cards whose clocks drift apart. The Windows specific parts (real WASAPI devices, listening
in on an output, OpenRGB hardware) follow the documented interfaces of the libraries but
were written without access to your hardware, so expect to report a rough edge or two.

## Files

* `speakerweave/model.py` setups, roles, modes, room geometry
* `speakerweave/mixer.py` which incoming channel goes to which role
* `speakerweave/dsp.py` filters, equaliser, delay
* `speakerweave/engine.py` the mixing engine and the clock correction
* `speakerweave/backend.py` talking to the sound cards
* `speakerweave/rgb.py` lights
* `speakerweave/updates.py` looking for and fetching newer versions
* `speakerweave/sounds.py` your own test sounds
* `speakerweave/windefault.py` and `default_output.py` the Windows default sound output, and
  setting the virtual device to 7.1
* `speakerweave/soundcheck.py` the checks behind the Errors page
* `speakerweave/cable.py` the name of the virtual device in Windows
* `speakerweave/media.py` what is playing on the PC, and its play, pause and skip
* `speakerweave/mics.py` microphone levels for the room map
* `speakerweave/perf.py` processor and memory use for the Performance page
* `speakerweave/remote.py` the links for Stream Deck and the SimHub plugin
* `speakerweave/simhub.py` finding SimHub and installing the plugin
* `speakerweave/uninstall.py` removing SpeakerWeave from the PC
* `speakerweave/release.py` publisher name and update address
* `speakerweave/ui/` the window
* `packaging/` the recipes that build SpeakerWeave.exe and its installer
* `packaging/simhub/` the SimHub plugin (C#, built by `build_plugin.bat` with the compiler
  that comes with Windows)
* `tests/` automatic tests
