"""
Background music: a few built-in themes, plus whatever you drop in ``music/``.

Two sources, one playlist.  The built-in themes are *synthesised* rather than
shipped as audio files: they are generated from a recipe with the standard
library, cached in the user directory, and therefore cost the repository nothing
and carry no licence.  Anything you put in a ``music`` folder is picked up
alongside them, so real tracks — including a favourite genre the built-ins do
not cover — join the same playlist and switch with the same controls.

The generator is deliberately simple: detuned drones, a slow chord progression,
a sparse pulse, a one-pole low pass and a feedback delay.  That is enough for
something that can sit under a turn-based game for half an hour without
becoming irritating, which is the whole job of background music.  It runs at
roughly seventy times real time, so a forty-eight second theme takes well under
a second to render — but it still happens on a worker thread, because a
half-second stall in the interface is a half-second stall.

Everything degrades to silence: no QtMultimedia, no audio device, or the
``offscreen`` platform (which is the test harness) all install a silent backend,
and nothing here raises.
"""

import math
import os
import struct
import sys
import tempfile
from array import array
import threading
import time
import wave

import Paths

#: Sample rate and length of the generated themes.  Mono keeps the cached files
#: small; the music sits under a game, not in front of it.
SAMPLE_RATE = 22050
TRACK_SECONDS = 48.0

#: Where generated themes are cached, relative to the user directory.  Kept
#: apart from the folders that get scanned: caching the built-in themes inside
#: ``music/`` made each of them appear a second time as "your own track".
_CACHE_DIR = "music_cache"

#: Folders scanned for the player's own tracks, in order.  The installation one
#: makes a mod or a shared copy work; the user one is the normal place.
MUSIC_DIRS = ("music",)

#: What counts as a track.  QtMultimedia decides what it can actually decode;
#: this is only a filter for what to offer.
AUDIO_SUFFIXES = (".wav", ".mp3", ".ogg", ".oga", ".opus", ".flac", ".m4a", ".aac")

#: A soft, slow progression in A minor: i - VI - III - VII, two bars each.
_PROGRESSION = (
    (220.00, 261.63, 329.63),      # Am
    (174.61, 220.00, 261.63),      # F
    (261.63, 329.63, 392.00),      # C
    (196.00, 246.94, 293.66),      # G
)

#: name -> (title, description, root scale, pulse seconds or None, brightness)
THEMES = {
    "detente": (
        "Detente",
        "Warm and unhurried; the world is calm.",
        (261.63, 329.63, 392.00), None, 0.55),
    "coldwar": (
        "Cold War",
        "A slow minor drone with a distant pulse.",
        (220.00, 261.63, 329.63), 4.0, 0.35),
    "defcon": (
        "DEFCON",
        "Lower, tenser, faster pulse. For a game that is going badly.",
        (174.61, 207.65, 261.63), 1.5, 0.22),
}

_backend = None
_enabled = True
_volume = 50
_index = 0
_tracks = []
_preparing = False
_prepare_error = ""
_backend_error = ""
_lock = threading.Lock()


class Track(object):
    """One playable item: a generated theme or a file of the player's own."""

    def __init__(self, key, title, path, description="", builtin=False):
        self.key = key
        self.title = title
        self.path = path
        self.description = description
        self.builtin = builtin

    @property
    def ready(self):
        return bool(self.path) and os.path.exists(self.path)

    def __repr__(self):
        return "<Track %s%s>" % (self.title, "" if self.ready else " (not ready)")


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------

def _cache_path(key):
    return os.path.join(Paths.user_dir(), _CACHE_DIR, "%s.wav" % key)


def _smooth(value, target, amount):
    """One-pole low pass, sample by sample.  The cheapest way to lose the hiss."""
    return value + (target - value) * amount


#: How often the renderer hands the interpreter back, and for how long.
#:
#: The synthesis is pure Python, so a worker running it holds the interpreter in
#: long stretches.  Measured here: generating a theme during startup made the
#: window take 1280 ms to appear instead of 52 ms, and -- with a coarser yield --
#: it still made a network reconnection miss a ten-second deadline, because two
#: Qt event loops were competing with the renderer for the GIL.
#:
#: The yield is ``time.sleep(0)``, which releases the interpreter and returns at
#: once.  A *timed* sleep here is a trap: ``sleep(0.0002)`` actually costs about
#: four milliseconds of scheduler granularity, and doing that a thousand times a
#: theme tripled the render time.  If this is ever tuned, measure a timed
#: dialogue and the total render time together, not one of them.
#: ``sleep(0)`` looked like the cheap way to yield and is not: it releases the
#: interpreter but the worker can take it straight back, and a network test that
#: waits on a ten-second timer failed again.  A real (if short) sleep is what
#: actually lets the event loop run.  Measured both ways: 1024/0.2 ms keeps a
#: reconnect alive; 8192/0.5 ms did not.
_BREATHE_EVERY = 1024
_BREATHE_SECONDS = 0.0002


def _breathe():
    """Release the GIL briefly so the interface can paint."""
    time.sleep(_BREATHE_SECONDS)


def render_theme(key, breathe=False):
    """Render one built-in theme to a list of floats in -1..1.

    Written as a plain loop rather than with an audio library because there is
    no audio library to depend on: the game installs onto a bare PyQt5, and a
    forty-eight second theme renders in a fraction of a second anyway.

    ``breathe`` is set when this runs on a worker thread: it yields the
    interpreter every few thousand samples so the window stays responsive while
    the music is being made.
    """
    title, _description, scale, pulse, brightness = THEMES[key]
    total = int(SAMPLE_RATE * TRACK_SECONDS)
    bar = TRACK_SECONDS / len(_PROGRESSION)
    out = [0.0] * total

    # A feedback delay gives the drone somewhere to live without a reverb unit.
    delay = int(SAMPLE_RATE * 0.28)
    feedback = 0.32
    history = [0.0] * (delay + 1)

    filtered = 0.0
    for i in range(total):
        if breathe and i % _BREATHE_EVERY == 0:
            _breathe()
        t = i / SAMPLE_RATE
        chord = _PROGRESSION[int(t / bar) % len(_PROGRESSION)]

        # Two detuned voices per chord note: the beating between them is what
        # keeps a static drone from sounding like a test tone.  (Iterating the
        # chord directly rather than a prepared list of voices was measured to
        # be faster: unpacking tuples in the inner loop costs more than the
        # tuple lookup it saves.)
        value = 0.0
        for note in chord:
            drift = 1.0 + 0.0015 * math.sin(2.0 * math.pi * 0.05 * t + note)
            value += math.sin(2.0 * math.pi * note * drift * t)
            value += 0.7 * math.sin(2.0 * math.pi * note * 1.5 * drift * t + 0.4)
        value /= (len(chord) * 1.7)

        # The root an octave down carries the mood.
        value += 0.5 * math.sin(2.0 * math.pi * (scale[0] / 2.0) * t)

        # A slow swell, so the loop breathes rather than sits.
        value *= 0.62 + 0.38 * math.sin(2.0 * math.pi * t / (TRACK_SECONDS / 2.0))

        if pulse:
            # A soft thump: a sine at the beat, decaying fast.
            phase = t % pulse
            thump = math.exp(-phase * 9.0) * math.sin(2.0 * math.pi * 62.0 * phase)
            value += 0.35 * thump

        # Low pass, then the delay line.
        filtered = _smooth(filtered, value, brightness)
        echo = history[i % len(history)]
        sample = filtered + echo * feedback
        history[i % len(history)] = sample
        out[i] = sample

    # Normalise IN PLACE.  The obvious ``[v / peak * 0.72 for v in out]`` builds
    # a second list of a million floats while the first is still alive, which is
    # the difference between a 34 MB spike and a 68 MB one.
    peak = max(1e-9, max(abs(v) for v in out))
    gain = 0.72 / peak
    for i in range(total):
        out[i] *= gain
    return out


def _fade(samples):
    """Fade the ends, so a loop does not click and a stop does not thump."""
    fade = int(SAMPLE_RATE * 1.5)
    if fade * 2 >= len(samples):
        return samples
    for i in range(fade):
        gain = i / fade
        samples[i] *= gain
        samples[-1 - i] *= gain
    return samples


def _write_wav(path, samples):
    """Write 16-bit mono, atomically: a reader never sees half a theme."""
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    # A name of its own per writer: two copies of the game sharing one user
    # directory (a LAN host and guest on one machine) may render the same theme
    # at once, and a shared ".part" name let one rename the other's file away.
    descriptor, temporary = tempfile.mkstemp(
        prefix=os.path.basename(path) + ".", suffix=".part", dir=directory or None)
    os.close(descriptor)
    try:
        with wave.open(temporary, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(SAMPLE_RATE)
            # Packed in one call rather than a million struct.pack ones.
            frames = array("h", (int(max(-1.0, min(1.0, v)) * 32000) for v in samples))
            if sys.byteorder != "little":
                frames.byteswap()
            handle.writeframes(frames.tobytes())
        os.replace(temporary, path)
    except OSError:
        # On Windows the rename fails while the other copy is playing the file
        # it wrote; that file is just as good as ours.
        try:
            os.remove(temporary)
        except OSError:
            pass
        if not os.path.exists(path):
            raise
    return path


def ensure_theme(key, breathe=False):
    """Render a built-in theme if it is not already cached."""
    path = _cache_path(key)
    if os.path.exists(path):
        return path
    return _write_wav(path, _fade(render_theme(key, breathe=breathe)))


def prepare(blocking=False, on_ready=None):
    """Generate the built-in themes, off the main thread by default.

    The first launch has no cache, so the themes must be made before they can be
    played, and doing that inline would freeze the interface at exactly the wrong
    moment.  Two things make the wait bearable: the track that is actually going
    to play is generated first, so the music starts as soon as one theme exists
    rather than after all three, and ``on_ready`` is called on the main thread
    after each one so the interface can start playing immediately.
    """
    global _preparing, _prepare_error

    def work():
        global _preparing, _prepare_error
        try:
            pending = [k for k in THEMES if not os.path.exists(_cache_path(k))]
            # The current track first, then the rest in playlist order.
            preferred = current().key if current() is not None else None
            if preferred in pending:
                pending.remove(preferred)
                pending.insert(0, preferred)
            for key in pending:
                # On a worker thread, so yield to the interface as we go.
                ensure_theme(key, breathe=True)
                refresh_tracks()
                if on_ready is not None:
                    _call_on_main(on_ready)
            _prepare_error = ""
        except (OSError, ValueError, wave.Error) as exc:
            _prepare_error = "could not prepare the built-in music: %s" % exc
        finally:
            _preparing = False
            refresh_tracks()
            if on_ready is not None:
                _call_on_main(on_ready)

    with _lock:
        if _preparing:
            return
        pending = [k for k in THEMES if not os.path.exists(_cache_path(k))]
        if not pending:
            refresh_tracks()
            return
        _preparing = True
    if blocking:
        work()
    else:
        threading.Thread(target=work, name="bop-music", daemon=True).start()


def _call_on_main(callback):
    """Run ``callback`` on the GUI thread.

    Generation happens on a worker, but every Qt object here belongs to the main
    thread, so the notification is posted rather than called directly.  With no
    application (a plain script) it is simply called.
    """
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication
    if QApplication.instance() is None:
        callback()
        return
    QTimer.singleShot(0, callback)


def preparing():
    """True while the built-in themes are still being generated."""
    return _preparing


def prepare_error():
    return _prepare_error


# ---------------------------------------------------------------------------
# The playlist
# ---------------------------------------------------------------------------

def _music_dirs():
    """Where to look for the player's own music."""
    directories = []
    for name in MUSIC_DIRS:
        # Both a folder beside the game (so a shared install or a mod can ship
        # tracks) and one in the user directory (the normal place).
        directories.append(Paths.resource(name))
        directories.append(os.path.join(Paths.user_dir(), name))
    return directories


def _pretty_title(name):
    """A file name as a track title: ``krush-me`` becomes ``Krush Me``."""
    stem = os.path.splitext(name)[0]
    words = stem.replace("_", " ").replace("-", " ").split()
    return " ".join(word[:1].upper() + word[1:] for word in words) or stem


def _user_tracks():
    """Every audio file the player has dropped into a ``music`` folder.

    Both places are searched: the folder beside the game (tracks that came with
    it) and the one in the user directory (the player's own).
    """
    found = []
    asset_dir = os.path.abspath(Paths.ASSET_DIR)
    for directory in _music_dirs():
        if not os.path.isdir(directory):
            continue
        inside_game = os.path.abspath(directory).startswith(asset_dir)
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            continue
        for name in names:
            if name.startswith(".") or name.endswith(".part"):
                continue
            if not name.lower().endswith(AUDIO_SUFFIXES):
                continue
            path = os.path.join(directory, name)
            if not os.path.isfile(path):
                continue
            found.append(Track(key="file:" + path, title=_pretty_title(name),
                               path=path,
                               description=("included with the game" if inside_game
                                            else "your own track"),
                               builtin=False))
    return found


def refresh_tracks():
    """Rebuild the playlist: real music first, the synthesised themes after.

    The generated themes used to lead the list, so a build that shipped tracks
    still opened on a drone and the tracks were only reachable by pressing next
    three times.  They are the fallback now: whatever is in a ``music`` folder is
    what somebody chose to hear, and the generated themes fill in when that
    folder is empty.
    """
    global _tracks, _index
    previous = _tracks[_index].key if _tracks and 0 <= _index < len(_tracks) else None
    tracks = _user_tracks()
    for key, (title, description, _scale, _pulse, _brightness) in THEMES.items():
        path = _cache_path(key)
        tracks.append(Track(key=key, title=title,
                            path=path if os.path.exists(path) else None,
                            description=description, builtin=True))
    _tracks = tracks
    if previous is not None:
        for position, track in enumerate(tracks):
            if track.key == previous:
                _index = position
                break
        else:
            _index = 0
    elif _index >= len(tracks):
        _index = 0
    return tracks


def tracks():
    if not _tracks:
        refresh_tracks()
    return list(_tracks)


def current_index():
    return _index


def current():
    items = tracks()
    return items[_index] if items else None


def set_index(position, autoplay=True):
    """Switch to a track by position.  Returns the track, or None."""
    global _index
    items = tracks()
    if not items:
        return None
    _index = int(position) % len(items)
    track = items[_index]
    if autoplay:
        play(replay=True)
    return track


def next_track(autoplay=True):
    return set_index(_index + 1, autoplay=autoplay)


def previous_track(autoplay=True):
    return set_index(_index - 1, autoplay=autoplay)


def now_playing():
    """A short line for the interface, or an explanation of the silence."""
    if not available():
        return "no audio device"
    track = current()
    if track is None:
        if preparing():
            return "preparing the built-in music\u2026"
        return "no tracks"
    if not track.ready:
        return "preparing %s\u2026" % track.title
    return track.title


def status_note():
    """Why there is no music, when there is none.  Empty when all is well."""
    if not _enabled:
        return "music is switched off"
    if not available():
        return _backend_error or "this machine has no audio output available"
    if _prepare_error:
        return _prepare_error
    if preparing():
        return "the built-in themes are being generated"
    return ""


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

class _SilentBackend(object):
    """Used where there is nothing to play through.  Never raises."""

    available = False

    def play(self, path, volume):
        return False

    def pause(self):
        pass

    def resume(self):
        pass

    def stop(self):
        pass

    def set_volume(self, volume):
        pass

    def playing(self):
        return False


class _MediaBackend(object):
    """Real playback, through QMediaPlayer.

    QSoundEffect is used for the short signals in :mod:`Sound`, but it decodes
    the whole file into memory, which is the wrong trade for a two-megabyte
    track: QMediaPlayer streams, loops and pauses properly.

    The volume API differs between Qt 5 and Qt 6 - Qt 6 moved it onto a separate
    ``QAudioOutput`` object and expects 0.0-1.0, while Qt 5 keeps a plain integer
    percentage on the player itself - so both are supported rather than assuming
    one.  Getting this wrong is not loud: the player simply fails to construct
    and the game goes quietly silent for ever.
    """

    def __init__(self):
        from PyQt5.QtMultimedia import QMediaPlayer
        self._player = QMediaPlayer()
        self._volume = 0.5
        # Qt 6: volume lives on QAudioOutput.  Qt 5: on the player itself.
        self._output = None
        if hasattr(self._player, "setAudioOutput"):
            from PyQt5.QtMultimedia import QAudioOutput
            self._output = QAudioOutput()
            self._player.setAudioOutput(self._output)
        self._path = None
        # Looping by hand: QMediaPlaylist is deprecated and the end-of-media
        # signal is both simpler and still supported.
        self._player.mediaStatusChanged.connect(self._on_status)

    @property
    def available(self):
        return True

    def _on_status(self, status):
        from PyQt5.QtMultimedia import QMediaPlayer
        if status == QMediaPlayer.EndOfMedia and self._path:
            self._player.setPosition(0)
            self._player.play()

    def play(self, path, volume):
        from PyQt5.QtCore import QUrl
        from PyQt5.QtMultimedia import QMediaContent
        self._path = path
        self.set_volume(volume)
        self._player.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
        self._player.play()
        return True

    def pause(self):
        self._player.pause()

    def resume(self):
        if self._path:
            self._player.play()

    def stop(self):
        self._path = None
        self._player.stop()

    def set_volume(self, volume):
        """``volume`` is 0.0-1.0, whichever API the running Qt wants."""
        self._volume = volume
        if self._output is not None:
            self._output.setVolume(volume)
        else:
            self._player.setVolume(int(round(volume * 100)))

    def _state(self):
        """The player's state, whichever Qt is running.

        Qt 5 has ``state()``; Qt 6 renamed it ``playbackState()``.  Asking for
        the wrong one raises AttributeError, which is exactly the kind of
        difference that turns a music feature into a stack trace on somebody
        else's machine.
        """
        getter = getattr(self._player, "playbackState", None)
        if getter is None:
            getter = self._player.state
        return getter()

    def playing(self):
        from PyQt5.QtMultimedia import QMediaPlayer
        return self._state() == QMediaPlayer.PlayingState

    def state_name(self):
        """The player's own state, for diagnostics."""
        from PyQt5.QtMultimedia import QMediaPlayer
        return {QMediaPlayer.StoppedState: "stopped",
                QMediaPlayer.PlayingState: "playing",
                QMediaPlayer.PausedState: "paused"}.get(self._state(), "?")

    def error_text(self):
        return self._player.errorString() or ""


def _build_backend():
    """Pick a backend once, and stay silent where sound is impossible."""
    global _backend
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None or app.platformName() == "offscreen":
        _backend = _SilentBackend()
        return _backend
    try:
        from PyQt5.QtMultimedia import QAudioDeviceInfo
    except ImportError:
        _backend = _SilentBackend()
        return _backend
    try:
        if QAudioDeviceInfo.defaultOutputDevice().isNull():
            _backend = _SilentBackend()
            return _backend
        _backend = _MediaBackend()
    except Exception as exc:              # a broken audio stack must not crash
        global _backend_error
        _backend_error = "could not open the audio player: %s" % exc
        _backend = _SilentBackend()
    return _backend


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def available():
    if _backend is None:
        _build_backend()
    return _backend.available


def enabled():
    return _enabled


def set_enabled(value):
    """Switch the music on or off (the interface's toggle)."""
    global _enabled
    _enabled = bool(value)
    if not _enabled:
        _backend_stop()
    else:
        play()
    return _enabled


def volume():
    return _volume


def set_volume(value):
    """0-100, as the settings slider shows it."""
    global _volume
    _volume = max(0, min(100, int(value)))
    if _backend is None:
        _build_backend()
    if _backend.available:
        _backend.set_volume(_volume / 100.0)
    return _volume


def play(replay=False):
    """Start (or resume) the current track.  Safe to call at any time."""
    global _enabled
    if not _enabled:
        return False
    if not available():
        return False
    track = current()
    if track is None or not track.ready:
        return False
    backend = _backend
    if not replay and backend.playing():
        return True
    return backend.play(track.path, _volume / 100.0)


def pause():
    if _backend is None or not _backend.available:
        return False
    _backend.pause()
    return True


def toggle():
    """Play if paused, pause if playing.  Returns the resulting state."""
    if _backend is not None and _backend.available and _backend.playing():
        pause()
        return False
    return play()


def stop():
    _backend_stop()


def _backend_stop():
    if _backend is None or not _backend.available:
        return
    _backend.stop()


def playing():
    return bool(_backend is not None and _backend.available and _backend.playing())


def shutdown():
    """Called when the window closes, so no audio thread outlives the app."""
    stop()
