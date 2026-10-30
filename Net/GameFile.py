"""
The portable game file: one self-contained file that can be emailed.

A network snapshot is a live JSON blob with no identity and no version, which is
fine between two copies of the same build that already agree what they are
doing.  A file that leaves the building needs more than that:

* it must say what it is, so opening the wrong file gives a sentence instead of
  a traceback;
* it must say which version of the *format* it uses, because the world keeps
  gaining fields and a file from a newer build must be refused politely rather
  than half-applied;
* it must survive being copied around: a checksum turns "the state silently
  decoded as nonsense" into "the file was damaged in transit";
* it must never be observed half-written, because play-by-mail
  (:mod:`Net.MailGame`) reads it straight out of a shared folder.

Layout — two text lines and then one opaque blob::

    BOPG1\\n
    {"format": ..., "format_version": 1, ..., "checksum": ...}\\n
    <zlib-compressed canonical JSON of the state, or raw JSON>

Splitting the header from the body is what makes ``read_header`` cheap: listing
a folder of moves never has to inflate a few hundred kilobytes per file, and a
corrupt body is reported per file instead of killing the listing.

The state itself is :func:`Net.State.world_to_state`, deliberately: the network
path and the file path must not drift into two definitions of "the game".
"""

import hashlib
import json
import os
import tempfile
import time
import zlib

from Net.State import StateError, apply_state, apply_state_safely, world_to_state

#: First line of every game file.  Short, printable, and greppable.
GAME_MAGIC = b"BOPG1"
MAGIC_LINE = GAME_MAGIC + b"\n"

FORMAT_NAME = "balance-of-power-game"

#: Bump when the *envelope* changes shape, not when the world gains a field
#: (the world is generic by design, so new attributes travel for free).
FORMAT_VERSION = 1

#: Conventional extension for an exported game.
SUFFIX = ".bopg"

#: Prefix of a file that is still being written.  Readers skip it; writers never
#: publish a file with this prefix.
TEMP_PREFIX = ".bopg-tmp-"

#: Refuse to inflate something absurd instead of eating all the memory.
MAX_STATE_BYTES = 64 * 1024 * 1024

#: Bodies larger than this are deflated.  A world snapshot is a few hundred
#: kilobytes of JSON and roughly a twentieth of that deflated, which is the
#: difference between "attaches to an email" and "gets blocked by the mail
#: server".
COMPRESS_THRESHOLD = 8 * 1024

#: How many times a read retries a file that does not parse yet.  A writer that
#: renames into place cannot be observed half-finished, but a copy tool or a
#: rude editor can; a couple of short retries cost nothing and turn a spurious
#: "damaged file" report into silence.
READ_RETRIES = 4
READ_RETRY_DELAY = 0.25
#: A file on a network share (``\\\\server\\share\\...``) is read through an
#: antivirus scanner, an SMB oplock and sometimes a "cloud placeholder"
#: hydration, any of which can refuse an open for a few seconds ("the process
#: cannot access the file because it is being used by another process").  Give
#: those longer: 8 tries over about six seconds.
UNC_READ_RETRIES = 8
UNC_READ_RETRY_DELAY = 0.75

#: Directories where ``os.replace`` was refused (a share that grants Write but
#: not Delete/rename).  Remembered so the next write goes straight to the direct
#: write instead of leaving another temporary file nobody may delete.
_NO_REPLACE_DIRS = set()


class GameFileError(Exception):
    """The file is not a game file, or is one this build cannot use.

    The message is written for the player, not for the log: it ends up in a
    message box.
    """


class VersionMismatch(GameFileError):
    """A well-formed game file in a format version this build does not know."""


# --- canonical form ---------------------------------------------------------

def canonical_state_bytes(state):
    """The one serialisation a checksum may be taken over.

    Sorted keys and no whitespace, so writing the same world twice produces the
    same bytes, and so a file rewritten by a different build still checks out.
    """
    text = json.dumps(state, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=True)
    return text.encode("utf-8")


def state_checksum(state):
    return hashlib.sha256(canonical_state_bytes(state)).hexdigest()


def world_checksum(world):
    """Checksum of a live world, for play-by-mail parent/child bookkeeping."""
    return state_checksum(world_to_state(world))


# --- writing ----------------------------------------------------------------

def build_header(state, meta=None, turn=None, created=None, encoding="zlib",
                 size=None, checksum=None):
    """The JSON header that sits on line two."""
    return {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "created": time.time() if created is None else float(created),
        "turn": turn,
        "encoding": encoding,
        "size": size,
        "checksum": state_checksum(state) if checksum is None else checksum,
        "meta": dict(meta or {}),
    }


def dumps(state, meta=None, turn=None, created=None, compress=True):
    """Serialise a whole game to bytes (the envelope described above)."""
    if not isinstance(state, dict):
        raise GameFileError("a game file can only be built from a state mapping")
    body = canonical_state_bytes(state)
    header = build_header(state, meta=meta, turn=turn, created=created,
                          encoding="json", size=len(body))
    if compress and len(body) > COMPRESS_THRESHOLD:
        packed = zlib.compress(body, 6)
        if len(packed) < len(body):
            header["encoding"] = "zlib"
            body = packed
    head = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return MAGIC_LINE + head + b"\n" + body


def write_game(path, state, meta=None, turn=None, compress=True):
    """Write a game file atomically and return its header.

    Atomic means: write a sibling temporary file, force it to disk, then
    ``os.replace`` it into place.  A reader never sees a partial file, and on a
    shared folder the rename happens after the bytes are durable, so a machine
    that lists the directory cannot pick up an empty file.  This is the same
    rule the play-by-mail mailbox uses, kept in one place.
    """
    payload = dumps(state, meta=meta, turn=turn, compress=compress)
    directory = os.path.dirname(os.path.abspath(path)) or "."
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as exc:
        raise GameFileError("could not write %s: %s" % (path, exc))
    if directory in _NO_REPLACE_DIRS:
        _write_direct(path, payload)
        return read_header(path)
    handle = None
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=TEMP_PREFIX, suffix=".part",
                                         dir=directory)
        handle = os.fdopen(fd, "wb")
        handle.write(payload)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            # Some network filesystems refuse fsync; the rename is still the
            # ordering barrier that matters, so carry on.
            pass
        handle.close()
        handle = None
        try:
            _replace_with_retry(temporary, path)
        except PermissionError:
            # The share lets us create files but not rename over or delete
            # them (Write without Delete/Modify).  Fall back to writing the
            # final file directly.  That is no longer atomic, but nothing
            # that reads can be fooled: the header carries the exact body size
            # and a SHA-256 of the state, so a half-written file is reported
            # as damaged and retried, never accepted.  _write_direct also reads
            # the result back and refuses to report success on a mismatch.
            _NO_REPLACE_DIRS.add(directory)
            _write_direct(path, payload)
        else:
            temporary = None
    except OSError as exc:
        raise GameFileError("could not write %s: %s" % (path, exc))
    finally:
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass
        if temporary is not None:
            try:
                os.remove(temporary)
            except OSError:
                pass
    return read_header(path)


def _replace_with_retry(source, destination, delays=(0.05, 0.15, 0.4)):
    """os.replace, retried a few times on PermissionError.

    On Windows a sharing violation (the partner, an antivirus scan or OneDrive
    has the destination open for a moment) looks exactly like a share that
    forbids rename; only a refusal that persists is treated as the latter.
    """
    for delay in delays:
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            time.sleep(delay)
    os.replace(source, destination)


def _write_direct(path, payload):
    """Write ``payload`` straight to ``path`` and prove it arrived intact.

    The fallback for a folder where rename is not allowed.  The file is created
    exclusively when it is new (two writers cannot both think they made it) and
    overwritten when it is not.  Afterwards the bytes are read back and
    compared with what was meant to be written; if they differ the file is
    removed when possible and the write is reported as failed, so a corrupt
    file is never left looking like a success.
    """
    mode = "wb" if os.path.exists(path) else "xb"
    created = mode == "xb"
    try:
        with open(path, mode) as handle:
            handle.write(payload)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        with open(path, "rb") as handle:
            written = handle.read()
    except OSError as exc:
        if created:
            try:
                os.remove(path)
            except OSError:
                pass
        raise GameFileError("could not write %s: %s" % (path, exc))
    if written != payload:
        if created:
            try:
                os.remove(path)
            except OSError:
                pass
        raise GameFileError("could not write %s: the file did not read back "
                            "intact" % path)


def export_world(world, path, meta=None, turn=None, compress=True):
    """Write ``world`` to ``path``.  Returns the header actually written."""
    return write_game(path, world_to_state(world), meta=meta, turn=turn,
                      compress=compress)


# --- reading ----------------------------------------------------------------

def _split_lines(data):
    """Split the envelope into (header dict, body bytes, header byte length)."""
    if not data.startswith(MAGIC_LINE):
        raise GameFileError("This is not a Balance of Power game file.")
    rest = data[len(MAGIC_LINE):]
    newline = rest.find(b"\n")
    if newline < 0:
        raise GameFileError("the game file is truncated: it has no header "
                            "line")
    raw_header = rest[:newline]
    body = rest[newline + 1:]
    try:
        header = json.loads(raw_header.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise GameFileError("the game file header is unreadable: the file is "
                            "damaged or truncated")
    if not isinstance(header, dict):
        raise GameFileError("the game file header is not an object")
    return header, body


def _check_version(header, source):
    version = header.get("format_version")
    name = header.get("format")
    if name != FORMAT_NAME:
        raise GameFileError("%s is not a Balance of Power game file"
                            % source)
    if not isinstance(version, int) or isinstance(version, bool):
        raise GameFileError("%s is not a Balance of Power game file: it carries "
                            "no usable version number" % source)
    if version > FORMAT_VERSION:
        raise VersionMismatch(
            "%s was written by a newer version of Balance of Power "
            "(game file version %d; this copy understands up to %d). "
            "Update the game, or ask your opponent to export again from an "
            "older copy." % (source, version, FORMAT_VERSION))
    if version < 1:
        raise VersionMismatch(
            "%s declares game file version %d, which this copy no longer "
            "understands." % (source, version))
    return version


def _inflate(header, body, source):
    encoding = header.get("encoding")
    if encoding == "zlib":
        try:
            # Capped: a small file must not be able to inflate to gigabytes.
            inflater = zlib.decompressobj()
            body = inflater.decompress(body, MAX_STATE_BYTES + 1)
            if len(body) > MAX_STATE_BYTES or inflater.unconsumed_tail:
                raise GameFileError(
                    "%s holds more state than this game will load." % source)
            if not inflater.eof:
                raise zlib.error("truncated stream")
        except zlib.error:
            raise GameFileError(
                "%s is damaged: its contents could not be read. Ask your "
                "opponent to send it again." % source)
    elif encoding == "json":
        pass
    else:
        raise GameFileError("%s uses a format this copy does not know (%r)"
                            % (source, encoding))
    expected = header.get("size")
    if isinstance(expected, int) and expected >= 0 and len(body) != expected:
        raise GameFileError(
            "%s is truncated: it should hold %d bytes and holds %d. Ask your "
            "opponent to send it again." % (source, expected, len(body)))
    if len(body) > MAX_STATE_BYTES:
        raise GameFileError("%s holds %d bytes of state, more than this game "
                            "will load." % (source, len(body)))
    return body


def _loads(data, source):
    header, body = _split_lines(data)
    _check_version(header, source)
    body = _inflate(header, body, source)
    try:
        state = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise GameFileError("%s is damaged: its contents are not readable"
                            % source)
    if not isinstance(state, dict) or "world" not in state or "countries" not in state:
        raise GameFileError("%s does not contain a game." % source)
    checksum = header.get("checksum")
    actual = state_checksum(state)
    if checksum and checksum != actual:
        raise GameFileError(
            "%s failed its integrity check: the file was damaged on the way. "
            "Ask your opponent to send it again." % source)
    return {
        "format": header.get("format"),
        "format_version": header.get("format_version"),
        "created": header.get("created"),
        "turn": header.get("turn"),
        "meta": header.get("meta") or {},
        "checksum": actual,
        "state": state,
        "source": source,
    }


def loads(data, source="this game file"):
    """Parse an in-memory game file.  Raises :class:`GameFileError`."""
    try:
        return _loads(data, source)
    except GameFileError:
        raise
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        # A last-resort net: anything the parser did not anticipate is still
        # reported as a damaged file rather than escaping as a mystery crash.
        raise GameFileError("%s is damaged and could not be read" % source)


def read_header(path):
    """Cheap read of just the envelope header (no inflate, no checksum).

    Used to list and sort a folder of moves without paying for the world in
    every one of them.
    """
    try:
        with open(path, "rb") as handle:
            head = handle.read(len(MAGIC_LINE))
            if head != MAGIC_LINE:
                raise GameFileError("%s is not a Balance of Power game file"
                                    % os.path.basename(path))
            raw = b""
            while len(raw) < 64 * 1024:
                char = handle.read(1)
                if not char:
                    break
                if char == b"\n":
                    break
                raw += char
        header = json.loads(raw.decode("utf-8"))
    except OSError as exc:
        raise GameFileError("could not read %s: %s" % (path, exc))
    except (UnicodeDecodeError, ValueError):
        raise GameFileError("the header of %s is unreadable, so the file is "
                            "damaged or truncated" % os.path.basename(path))
    if not isinstance(header, dict):
        raise GameFileError("the header of %s is not an object"
                            % os.path.basename(path))
    return header


#: Errors that will not improve by waiting.
_PERMANENT_OS_ERRORS = (FileNotFoundError, IsADirectoryError, NotADirectoryError)


def read_game(path, retries=READ_RETRIES, delay=READ_RETRY_DELAY, cancel=None):
    """Read and verify a game file.

    A file that does not parse yet is retried a few times: a shared folder means
    the writer is another machine, and even an atomic rename can race with a
    copier that streams the bytes.  Only after the retries is a file declared
    damaged.  ``cancel`` is an optional ``threading.Event``: setting it ends the
    waiting between retries at once (a closing dialog must not wait for them).
    """
    if str(path).startswith("\\\\"):
        # A UNC path: the default patience is not enough for a scanned share.
        if retries == READ_RETRIES:
            retries = UNC_READ_RETRIES
        if delay == READ_RETRY_DELAY:
            delay = UNC_READ_RETRY_DELAY
    attempts = max(1, int(retries))
    last = None
    for attempt in range(attempts):
        try:
            with open(path, "rb") as handle:
                data = handle.read()
            return loads(data, source=os.path.basename(path) or path)
        except OSError as exc:
            # Antivirus scan, SMB sharing violation, a file the writer still
            # holds: an OSError here is usually "not yet", not "never".
            last = GameFileError("could not read %s: %s"
                                 % (os.path.basename(path) or path,
                                    getattr(exc, "strerror", None) or exc))
            if isinstance(exc, _PERMANENT_OS_ERRORS):
                raise last
            if attempt + 1 < attempts:
                _nap(delay, cancel)
        except GameFileError as exc:
            last = exc
            # A version mismatch or a wrong-format file will never improve.
            if isinstance(exc, VersionMismatch) or "not a Balance of Power" in str(exc):
                raise
            if attempt + 1 < attempts:
                _nap(delay, cancel)
    raise last


def _nap(delay, cancel):
    """Sleep ``delay`` seconds, or stop early (with an error) when cancelled."""
    if cancel is None:
        time.sleep(delay)
    elif cancel.wait(delay):
        raise GameFileError("reading was cancelled")


# --- convenience ------------------------------------------------------------

def describe(document_or_header):
    """One human-readable line about a game file, for a dialog."""
    meta = document_or_header.get("meta") or {}
    turn = document_or_header.get("turn")
    year = meta.get("year")
    parts = []
    if meta.get("game"):
        parts.append(str(meta["game"]))
    if year:
        parts.append("year %s" % year)
    if turn is not None:
        parts.append("turn %s" % turn)
    if meta.get("side"):
        parts.append("sent by %s" % meta["side"])
    if meta.get("to_move"):
        parts.append("%s to move" % meta["to_move"])
    created = document_or_header.get("created")
    if created:
        parts.append("written %s" % time.strftime("%Y-%m-%d %H:%M",
                                                  time.localtime(created)))
    return ", ".join(parts) or "game"


def install_into(world, document):
    """Apply a document's state to a live world, in place.

    In place on purpose: the map polygons and every open dialog hold references
    to the same ``Country`` objects, so rebuilding the graph would blank the
    map.  This is the same rule :func:`Net.State.apply_state` documents for
    network snapshots — an imported game is just a snapshot that arrived by
    email.
    """
    # Validated and rolled back on failure: a file with a valid checksum can
    # still hold nonsense, and the live game must survive loading it.
    try:
        apply_state_safely(world, document["state"])
    except StateError as exc:
        raise GameFileError("the game in this file cannot be loaded: %s" % exc)
    except GameFileError:
        raise
    except Exception as exc:         # rolled back by apply_state_safely
        raise GameFileError("the game in this file could not be applied "
                            "(%s: %s); your game is unchanged"
                            % (type(exc).__name__, exc))
    return world
