"""
Resource and user-data path resolution.

The original port opened every asset with a path relative to the current
working directory (``open("data/world_data.json")``, ``QPixmap("img/...")``),
so the game only started when it was launched from exactly one directory and
wrote its save files into the installation tree.

This module centralises both concerns:

* read-only assets (``data/``, ``img/``) are resolved relative to this file,
  so the game can be started from anywhere;
* writable files (saves, options, network log) go into a per-user directory.

``BOP_USER_DIR`` overrides the writable location, which is useful for tests
and for running two instances side by side.
"""

import os

# Directory that contains the game modules, data/ and img/.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ASSET_DIR = BASE_DIR
IMAGE_DIR = os.path.join(ASSET_DIR, "img")
DATA_DIR = os.path.join(ASSET_DIR, "data")
LOCALE_DIR = os.path.join(DATA_DIR, "local")

_APP_DIR_NAME = "balance-of-power"


def resource(*parts):
    """Absolute path of a read-only resource inside the installation tree."""
    return os.path.join(ASSET_DIR, *parts)


def image(*parts):
    """Absolute path of a file inside ``img/``."""
    return os.path.join(IMAGE_DIR, *parts)


def data(*parts):
    """Absolute path of a file inside ``data/``."""
    return os.path.join(DATA_DIR, *parts)


def locale_file(language):
    """Absolute path of a localisation file.

    Accepts both ``"english"`` and ``"english.json"``; the menu stores the
    file name, while the loader historically used the bare language name.
    """
    name = language if str(language).endswith(".json") else "%s.json" % language
    return os.path.join(LOCALE_DIR, name)


def locale_names():
    """Names of the available localisation files, sorted."""
    try:
        return sorted(f for f in os.listdir(LOCALE_DIR)
                      if f.endswith(".json") and os.path.isfile(os.path.join(LOCALE_DIR, f)))
    except OSError:
        return []


#: preferred path -> directory actually used (decided once per path).
_resolved = {}
#: Set when the preferred directory could not be used; shown to the player once.
_warning = ""
_warning_shown = False


def _preferred_dir():
    override = os.environ.get("BOP_USER_DIR")
    if override:
        return override
    if os.name == "nt":
        # %LOCALAPPDATA% is the per-user, no-admin location on Windows.  Using
        # the XDG shape there would scatter saves into C:\Users\<u>\.local.
        base = (os.environ.get("LOCALAPPDATA")
                or os.path.join(os.path.expanduser("~"), "AppData", "Local"))
        return os.path.join(base, _APP_DIR_NAME)
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, _APP_DIR_NAME)


def _writable(path):
    """Create ``path`` and prove a file can be written there."""
    os.makedirs(path, exist_ok=True)
    probe = os.path.join(path, ".bop-write-test-%d" % os.getpid())
    with open(probe, "w") as handle:
        handle.write("x")
    try:
        os.remove(probe)
    except OSError:
        pass            # writable but not deletable: still good enough for saves


def user_dir():
    """Writable per-user directory, created on first use.  Never raises.

    On a locked-down PC the preferred location (a redirected or read-only
    profile, a bad ``BOP_USER_DIR``) may be unusable.  The game then uses a
    folder in the system temp directory instead and :func:`take_warning` returns
    a message, once, saying that saves will not persist.
    """
    global _warning
    preferred = _preferred_dir()
    cached = _resolved.get(preferred)
    if cached:
        return cached
    try:
        _writable(preferred)
        _resolved[preferred] = preferred
        return preferred
    except OSError as exc:
        reason = exc.strerror or str(exc)
    import tempfile
    try:
        import getpass
        who = getpass.getuser()
    except Exception:
        who = "user"
    fallback = os.path.join(tempfile.gettempdir(), "balance-of-power-%s" % who)
    try:
        _writable(fallback)
    except OSError:
        fallback = tempfile.gettempdir()    # nothing better; callers guard writes
    _warning = ("Cannot write to %s (%s). Using %s instead: saves and settings "
                "may not persist after you close the game." % (preferred, reason, fallback))
    _resolved[preferred] = fallback
    return fallback


def take_warning():
    """The "saves will not persist" message, once; afterwards an empty string."""
    global _warning, _warning_shown
    if _warning and not _warning_shown:
        _warning_shown = True
        return _warning
    return ""


def user_file(name):
    """Absolute path of a writable file in the per-user directory."""
    return os.path.join(user_dir(), name)
