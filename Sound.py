"""
Short sound signals: the turn change, a crisis opening, the endgame.

The original piped at the change of side; the port had gone silent.  Three
signals are enough to give the game a pulse, and they are *synthesised* rather
than shipped as assets, so no new file enters the repository and no new
dependency enters the build: the tones are computed with :mod:`wave`,
:mod:`struct` and :mod:`math` from the standard library and handed to
``QSoundEffect``, which ships with PyQt5.

Two things make this safe to call from anywhere:

* **The backend degrades to a no-op.**  ``PyQt5.QtMultimedia`` is probed at
  first use, not at import time, and the module is switched off entirely when
  there is no audio output device, when the application is running under the
  ``offscreen`` platform (the test and screenshot harness runs there), or when
  the import fails.  A machine without sound never raises and never waits.
* **Nothing blocks.**  The WAV files are written once, lazily, into the user
  directory (``Paths.user_file``); a failure to write them simply leaves the
  module silent.

Game code only ever calls :func:`play`; the switch behind :func:`set_enabled`
is what the interface toggles.
"""

import math
import os
import struct
import wave

import Paths

#: 22.05 kHz mono is plenty for a beep and keeps the generated files small.
SAMPLE_RATE = 22050

#: One entry per effect: ``[(frequency_hz, seconds, amplitude), ...]``.  A zero
#: frequency is a rest, and a negative one is the endgame's falling glide.  A
#: recipe is deliberately short — these are signals, not music.
RECIPES = {
    # Turn change: a rising fifth, the sound of a page turning.
    "turn": ((660.0, 0.085, 0.42), (880.0, 0.19, 0.38)),
    # Crisis: two flat low notes, deliberately not pleasant.
    "crisis": ((311.0, 0.13, 0.46), (0.0, 0.05, 0.0), (311.0, 0.13, 0.46),
               (0.0, 0.04, 0.0), (233.0, 0.30, 0.42)),
    # Endgame: one long tone sliding down and dying out.  The original refuses
    # to show a mushroom cloud, and it would be just as wrong to sound like one:
    # this is the air going out of the room, not an explosion.
    "endgame": ((-1.0, 1.5, 0.5),),
}

#: The endgame tone sweeps between these two pitches.
_ENDGAME_FROM = 196.0
_ENDGAME_TO = 49.0

#: Where the generated WAVs are cached, relative to the user directory.
_CACHE_DIR = "sounds"

_backend = None
_enabled = True
_write_failed = False


# --- synthesis --------------------------------------------------------------

def _envelope(position, length, attack=0.012, release=0.05):
    """Trapezoid envelope, so a tone starts and stops without a click."""
    if position < attack:
        return position / attack
    remaining = length - position
    if remaining < release:
        return max(0.0, remaining / release)
    return 1.0


def _render(recipe):
    """Turn a recipe into a list of samples in [-1, 1]."""
    samples = []
    for frequency, seconds, amplitude in recipe:
        count = max(1, int(SAMPLE_RATE * seconds))
        for i in range(count):
            position = i / float(SAMPLE_RATE)
            if frequency == 0.0:
                samples.append(0.0)
                continue
            env = _envelope(position, seconds)
            if frequency < 0.0:
                # A glide, used by the endgame: the pitch falls as the note
                # dies, which reads as something winding down rather than as a
                # second, separate signal.
                progress = i / float(max(1, count - 1))
                pitch = _ENDGAME_FROM + (_ENDGAME_TO - _ENDGAME_FROM) * progress
                env *= 1.0 - 0.55 * progress
            else:
                pitch = frequency
            # A little third harmonic keeps the tone from sounding like a test
            # signal on cheap speakers.
            value = math.sin(2.0 * math.pi * pitch * position)
            value += 0.18 * math.sin(4.0 * math.pi * pitch * position)
            samples.append(amplitude * env * value)
    return samples


def _write_wav(path, samples):
    """Write 16-bit mono PCM, clipping anything that overshot the mix."""
    frames = bytearray()
    for value in samples:
        scaled = int(max(-1.0, min(1.0, value)) * 32000.0)
        frames += struct.pack("<h", scaled)
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(bytes(frames))


def _effect_path(name):
    """Path of the cached WAV, generated on first use."""
    global _write_failed
    directory = Paths.user_file(_CACHE_DIR)
    path = os.path.join(directory, "%s.wav" % name)
    if os.path.exists(path) or _write_failed:
        return path if os.path.exists(path) else None
    recipe = RECIPES.get(name)
    if recipe is None:
        return None
    try:
        os.makedirs(directory, exist_ok=True)
        _write_wav(path, _render(recipe))
    except (OSError, struct.error, wave.Error):
        # A read-only or full user directory must not take the game down: the
        # signal is simply never heard.
        _write_failed = True
        return None
    return path


# --- backends ---------------------------------------------------------------

class SilentBackend(object):
    """The no-op backend, and the base class for the real one."""

    available = False

    def play(self, name):
        pass


class QtSoundBackend(SilentBackend):
    """``QSoundEffect`` playback.  One effect object per signal, reused."""

    available = True

    def __init__(self):
        from PyQt5.QtCore import QUrl
        from PyQt5.QtMultimedia import QSoundEffect
        self._url = QUrl
        self._effects = {}
        self._cls = QSoundEffect

    def _effect(self, name):
        effect = self._effects.get(name)
        if effect is None:
            path = _effect_path(name)
            if path is None:
                return None
            effect = self._cls()
            effect.setSource(self._url.fromLocalFile(path))
            effect.setVolume(0.45 if name != "endgame" else 0.55)
            self._effects[name] = effect
        return effect

    def play(self, name):
        effect = self._effect(name)
        if effect is not None:
            effect.play()


def _build_backend():
    """Choose a backend once, and stay silent when the environment cannot play.

    The ``offscreen`` platform is the test and screenshot harness: it has no
    audio, and probing for it there produced a stream of backend warnings, so it
    is short-circuited.
    """
    global _backend
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        _backend = SilentBackend()
        return _backend
    if app.platformName() == "offscreen":
        _backend = SilentBackend()
        return _backend
    try:
        from PyQt5.QtMultimedia import QAudioDeviceInfo
    except ImportError:
        _backend = SilentBackend()
        return _backend
    try:
        if QAudioDeviceInfo.defaultOutputDevice().isNull():
            _backend = SilentBackend()
            return _backend
        _backend = QtSoundBackend()
    except (AttributeError, RuntimeError):
        _backend = SilentBackend()
    return _backend


# --- public interface -------------------------------------------------------

def available():
    """True when this machine can actually make a sound."""
    if _backend is None:
        _build_backend()
    return _backend.available


def enabled():
    return _enabled


def set_enabled(value):
    """Switch the signals on or off (the interface's sound toggle)."""
    global _enabled
    _enabled = bool(value)
    if not _enabled:
        stop()
    return _enabled


def play(name):
    """Play a named signal.  Safe to call from any thread that owns the UI."""
    if not _enabled:
        return False
    if _backend is None:
        _build_backend()
    if not _backend.available:
        return False
    _backend.play(name)
    return True


def stop():
    """Silence anything still playing, e.g. when the toggle goes off."""
    if _backend is None or not _backend.available:
        return
    for effect in getattr(_backend, "_effects", {}).values():
        effect.stop()
