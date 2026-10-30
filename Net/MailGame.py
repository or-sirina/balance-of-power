"""
Play-by-mail over a shared folder.

Corporate networks routinely forbid TCP between workstations while offering a
shared drive, and that is the entire reason this transport exists: a turn is a
file, and the shared folder is the wire.  It is built directly on
:mod:`Net.GameFile`, so a move *is* an ordinary portable game file — the same
thing Export writes — and can still be emailed by hand if the share is down.

The exchange is sequential, like the real thing: you make your move, you send
it, your opponent makes theirs.  One file per move, named

    <game>.turn<NNNN>.<SIDE>.bopg

carrying the position *after* the sender finished that turn.  Whose turn it is
is a property of the file itself (``meta.to_move``), not of any server, so there
is no state to keep in sync and no port to open.

Four real-world failure modes are handled explicitly, because a shared folder is
a hostile transport: several machines can read and write it at once and none of
them can be trusted to be quick or polite.

1. **Read while writing.**  The writer builds the file under a temporary name and
   renames it into place (:func:`Net.GameFile.write_game`); the reader ignores
   temporary names *and* retries a file that does not parse yet, so a copier that
   streams bytes is never mistaken for corruption.
2. **Both players acting on the same turn.**  Every move records the checksum of
   the position it was built on (``parent``).  A move whose ``parent`` is not the
   position you last applied was made against a position you have never seen: it
   is reported as a conflict and never silently applied, and two unapplied files
   claiming the same move number are reported as a fork.  Submitting is refused
   in the same situation, so the fork is caught on the way out too.
3. **A stale or duplicated file.**  Moves are applied in ``seq`` order.  A file
   behind the applied sequence is stale, a file whose sequence *and* position
   checksum match what was applied is a duplicate; both are reported and ignored,
   and replaying one is impossible by construction.
4. **A corrupt or truncated file.**  Declared size, checksum and JSON shape are
   all verified (see :mod:`Net.GameFile`), so the failure is a sentence naming
   the file rather than a half-loaded world.

Nothing here touches Qt for the file protocol, so the whole thing can be tested
headlessly; :class:`MailWatcher` adds the polling thread the dialogs need.
"""

import json
import os
import re
import threading
import time

from PyQt5.QtCore import QObject, QThread, pyqtSignal

from Net import GameFile

#: How often the watcher looks at the folder by default.
DEFAULT_POLL_MS = 5000

MOVE_RE = re.compile(r"^(?P<game>.+)\.turn(?P<seq>\d+)\.(?P<side>[A-Za-z]+)$")

SIDE_NAMES = ("USA", "USSR")


class MailError(Exception):
    """Something about this mailbox cannot work; the text is for the player."""


class MailForkError(MailError):
    """Both players moved from the same position and this machine holds both.

    ``conflict`` is the dict :meth:`MailSession.status` reports.  The dialog may
    offer to discard the local move (``apply_next(world, replace_own=True)``)
    after asking; nothing is ever discarded without that explicit say-so.
    """

    def __init__(self, message, conflict=None):
        super().__init__(message)
        self.conflict = conflict


def side_name(side):
    try:
        return SIDE_NAMES[int(side)]
    except (IndexError, TypeError, ValueError):
        return "side %s" % (side,)


def other_side(side):
    try:
        return 1 - int(side)
    except (TypeError, ValueError):
        return 1


def side_index(name):
    """``"USSR"`` or ``1`` -> 1.  Raises :class:`MailError` for anything else.

    Both spellings are accepted because the rest of the game passes sides around
    as the indexes 0/1 (``SIDE_USA``/``SIDE_USSR``) while a *file* records them
    as names — a file has to be readable by a human, and a checksum over the
    word "USSR" survives somebody opening it in a text editor.
    """
    if isinstance(name, bool):
        raise MailError("%r is not one of %s" % (name, " / ".join(SIDE_NAMES)))
    if isinstance(name, int):
        if 0 <= name < len(SIDE_NAMES):
            return int(name)
        raise MailError("side %d is not one of 0/1 (%s)"
                        % (name, " / ".join(SIDE_NAMES)))
    text = str(name or "").strip().upper()
    if text not in SIDE_NAMES:
        raise MailError("%r is not one of %s" % (name, " / ".join(SIDE_NAMES)))
    return SIDE_NAMES.index(text)


#: Policy for play by mail: the opponent is not at this keyboard, so a move of
#: yours that the other superpower could contest in a crisis is NOT put to a
#: crisis duel (the mover would be answering for both sides).  The setting is
#: written into every move's ``meta`` so a file says how it was played.
MAIL_CRISES_CONTESTED = False

GAME_CODE_LIMIT = 48

_RESERVED_NAMES = frozenset(["CON", "PRN", "AUX", "NUL"]
                            + ["COM%d" % n for n in range(1, 10)]
                            + ["LPT%d" % n for n in range(1, 10)])


def normalize_game_code(text):
    """The game code as it will be used in file names, or a :class:`MailError`.

    The code ends up inside a file name, so characters Windows (or the code
    that finds the files again) would drop are not silently dropped: "bop-AB!"
    and "bop-AB?" used to become the same mailbox, and a code of only
    punctuation became "game" -- the same game for everybody who did it.  Only
    letters, digits, ``-`` and ``_`` are kept; spaces become ``-``.
    """
    raw = str(text or "").strip()
    if not raw:
        raise MailError("Type a game code first: letters, digits, - and _ only.")
    code = "-".join(raw.split())
    bad = sorted(set(c for c in code if not (c.isalnum() or c in "-_")))
    if bad:
        raise MailError(
            "The game code %r contains %s, which cannot be used in a file name. "
            "Use letters, digits, - and _ only (for example \u201cbop-%s\u201d)."
            % (raw, " ".join(repr(c) for c in bad), "".join(
                c for c in code if c.isalnum())[:6].upper() or "K7MQ"))
    if code.split(".")[0].upper() in _RESERVED_NAMES:
        raise MailError("The game code %r is a reserved Windows device name "
                        "(CON, NUL, AUX, PRN, COM1-9, LPT1-9) and cannot be "
                        "used in a file name. Choose another, e.g. bop-%s."
                        % (raw, code.upper()))
    if not any(c.isalnum() for c in code):
        raise MailError("The game code %r needs at least one letter or digit." % raw)
    if len(code) > GAME_CODE_LIMIT:
        raise MailError("The game code is too long (%d characters; the limit is %d)."
                        % (len(code), GAME_CODE_LIMIT))
    return code


def safe_component(text, fallback="game", limit=48):
    """A filename-safe version of a user-supplied name."""
    kept = "".join(c for c in str(text or "") if c.isalnum() or c in " -_()")
    kept = kept.strip().replace(" ", "_")
    return (kept or fallback)[:limit]


#: No 0/O, 1/I/L: the code is read out loud or typed from a screen.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def new_game_code(player_name="", length=4):
    """A distinctive default mailbox name, e.g. ``bop-ALEX-K7MQ``.

    The old default ("bop-game") was the same on every PC, so two pairs sharing
    one folder silently loaded each other's opening position.  The random part
    makes a collision between pairs a one-in-a-million event; the player's name
    (when given) only makes the code easier to recognise in a folder listing.
    The creator reads the code to their partner, who must type it exactly (the
    comparison ignores case, because a Windows share does).
    """
    import secrets
    tail = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(int(length)))
    # ASCII only: a Cyrillic "МАКС" looks exactly like a Latin "MAKC" on screen,
    # so a partner typing what they see would never match the folder's name.
    who = "".join(c for c in str(player_name or "")
                  if c.isascii() and c.isalnum()).upper()[:6]
    return "bop-%s-%s" % (who, tail) if who else "bop-%s" % tail


def _stamp(value):
    if not value:
        return "?"
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(value)))
    except (OSError, OverflowError, ValueError, TypeError):
        return "?"


class Move:
    """One file in the mailbox, described but not necessarily loaded."""

    def __init__(self, path, header):
        self.path = path
        self.name = os.path.basename(path)
        self.header = header
        self.document = None
        meta = header.get("meta") or {}
        if not isinstance(meta, dict):
            raise GameFile.GameFileError(
                "the header's meta is not a record (a damaged or foreign file)")
        self.meta = meta
        self.game = str(meta.get("game") or "")
        try:
            self.seq = int(meta.get("seq"))
        except (TypeError, ValueError, OverflowError):
            self.seq = None
        # Normalised once here: every comparison below is against "USA"/"USSR",
        # and a hand-edited or foreign file must not be able to smuggle in a
        # different spelling of the same side.
        self.side = str(meta.get("side") or "").strip().upper()
        self.to_move = str(meta.get("to_move") or "").strip().upper()
        self.parent = str(meta.get("parent") or "")
        self.opening = bool(meta.get("opening"))
        self.game_over = bool(meta.get("game_over"))
        self.checksum = str(header.get("checksum") or "")
        self.created = header.get("created")
        self.turn = header.get("turn")
        try:
            self.mtime = os.stat(path).st_mtime
        except OSError:
            self.mtime = None

    @property
    def checksum_short(self):
        return self.checksum[:12]

    def loaded(self, retries=None, cancel=None):
        """Read and verify the whole file.  Raises ``GameFileError`` for the UI.

        ``retries`` bounds the patience: the default waits for a file that is
        still being copied (about a second locally, six on a network share),
        which is right on the watcher thread and wrong on the interface thread,
        where the caller passes ``1`` and gets an answer at once.
        """
        if self.document is None:
            if retries is None:
                self.document = GameFile.read_game(self.path, cancel=cancel)
            else:
                self.document = GameFile.read_game(self.path, retries=retries,
                                                   cancel=cancel)
            self.meta = self.document.get("meta") or self.meta
        return self.document

    def position_checksum(self, retries=None):
        """Checksum of the *position* this move carries.

        The envelope checksum identifies the file; the position checksum is what
        a child move records as its parent, so the two must not be confused.
        """
        return GameFile.state_checksum(self.loaded(retries)["state"])

    def describe(self):
        return "move %s by %s (%s) -> %s to move" % (
            self.seq, self.side or "?", _stamp(self.created or self.mtime),
            self.to_move or "?")


class Problem:
    """Something wrong with one file, kept so the UI can show it once."""

    def __init__(self, path, kind, message):
        self.path = path
        self.name = os.path.basename(path)
        self.kind = kind
        self.message = message

    def key(self):
        """Identity of *this* broken file, not of the problem.

        Size and mtime are included so that the file being fixed and re-sent
        under the same name is reported again.
        """
        try:
            stat = os.stat(self.path)
            return (self.name, stat.st_size, int(stat.st_mtime))
        except OSError:
            return (self.name, None, None)

    def describe(self):
        return "%s: %s" % (self.name, self.message)


class Mailbox:
    """A directory used as the wire for one play-by-mail game.

    Deliberately knows nothing about worlds: it lists, writes and reads move
    files.  :class:`MailSession` adds the game bookkeeping on top.
    """

    def __init__(self, directory, game_id):
        self.directory = os.path.abspath(os.path.expanduser(str(directory)))
        self.game_id = normalize_game_code(game_id)

    # -- layout -------------------------------------------------------------

    def ensure(self):
        """Create the folder if needed, and check that it is usable."""
        try:
            os.makedirs(self.directory, exist_ok=True)
        except OSError as exc:
            raise MailError("the shared folder %s cannot be created: %s"
                            % (self.directory, exc))
        if not os.path.isdir(self.directory):
            raise MailError("%s is not a folder" % self.directory)
        if not os.access(self.directory, os.W_OK):
            raise MailError(
                "the shared folder %s is not writable by you; play-by-mail "
                "needs a folder that both players can write to"
                % self.directory)
        return self.directory

    def move_path(self, seq, side):
        return os.path.join(self.directory, "%s.turn%04d.%s%s"
                            % (self.game_id, int(seq), side_name(side),
                               GameFile.SUFFIX))

    def _candidate_names(self):
        # Case-insensitive: a Windows share does not distinguish "bop-K7MQ"
        # from "bop-k7mq", so a partner who types it in lower case must still
        # find the creator's files.
        prefix = ("%s.turn" % self.game_id).lower()
        try:
            names = os.listdir(self.directory)
        except OSError as exc:
            raise MailError("the shared folder %s cannot be listed: %s"
                            % (self.directory, exc))
        # Temporary names are never candidates: a file under construction must
        # not be readable at all, and its name is the only thing we can use to
        # tell the difference without opening it.
        return sorted(name for name in names
                      if name.lower().startswith(prefix)
                      and name.endswith(GameFile.SUFFIX)
                      and not name.startswith(GameFile.TEMP_PREFIX))

    # -- writing ------------------------------------------------------------

    def write_move(self, state, meta, turn=None):
        """Atomically publish one move.  ``meta`` must carry seq/side/parent."""
        self.ensure()
        seq = int(meta["seq"])
        side = side_index(meta["side"])
        target = self.move_path(seq, side)
        GameFile.write_game(target, state, meta=meta, turn=turn)
        return target

    # -- reading ------------------------------------------------------------

    def scan(self):
        """Every readable move of this game, oldest first, plus problems found.

        Only headers are read here: a folder of twenty moves should not cost
        twenty world parses just to tell you whose turn it is.
        """
        moves = []
        problems = []
        for name in self._candidate_names():
            path = os.path.join(self.directory, name)
            match = MOVE_RE.match(name[:-len(GameFile.SUFFIX)])
            if match is None:
                # "... (1).bopg", "... - Copy.bopg", "...-DESKTOP-AB12.bopg":
                # what OneDrive / Explorer / a sync client leave when two
                # copies meet.  Never silently ignore a would-be move.
                problems.append(Problem(
                    path, "copy",
                    "looks like a duplicate or sync-conflict copy of a move "
                    "file, so it is ignored. If it is the real move, rename it "
                    "to the plain name (%s.turnNNNN.USA/USSR%s) after deleting "
                    "the original; otherwise delete it"
                    % (self.game_id, GameFile.SUFFIX)))
                continue
            if match.group("game").lower() != self.game_id.lower():
                continue
            try:
                header = GameFile.read_header(path)
                move = Move(path, header)
            except GameFile.GameFileError as exc:
                problems.append(Problem(path, "header", str(exc)))
                continue
            except (AttributeError, TypeError, ValueError, OverflowError) as exc:
                problems.append(Problem(
                    path, "header",
                    "the header holds unusable values (%s); ignored"
                    % type(exc).__name__))
                continue
            if match.group("side").upper() != move.side.upper():
                problems.append(Problem(
                    path, "name",
                    "the file name says %s but the header says %s; ignored"
                    % (match.group("side"), move.side or "?")))
                continue
            if move.seq is None:
                problems.append(Problem(path, "meta",
                                        "the file carries no move number; ignored"))
                continue
            if move.game.lower() != self.game_id.lower():
                # A file copied or renamed from another game: the name is only
                # a label, the header says what the position really belongs to.
                problems.append(Problem(
                    path, "game",
                    "the file is named for game %s but belongs to game %s; "
                    "ignored" % (self.game_id, move.game or "(none)")))
                continue
            if int(match.group("seq")) != move.seq:
                problems.append(Problem(
                    path, "name",
                    "the file name says move %s but the header says %s; ignored"
                    % (match.group("seq"), move.seq)))
                continue
            moves.append(move)
        moves.sort(key=lambda item: (item.seq, item.side, item.name))
        return moves, problems


class MailSession:
    """One player's end of a play-by-mail game.

    The folder-transport analogue of :class:`Net.Session.Session`: it owns the
    local side, the position that has been applied, and the bookkeeping that
    says whose turn it is.  It never blocks on anything and never touches a
    socket, so it is safe to drive from a worker thread.
    """

    #: How many position checksums a player remembers.  The parent check is "was
    #: this move built on something I have held?", and one checksum is not enough
    #: to answer it: after a fork is resolved by adopting the opponent's move,
    #: their next move is built on *their* position, which this player has seen
    #: but no longer holds.
    SEEN_LIMIT = 32

    UNVERIFIED = ("can't verify the folder yet (a file is still being copied "
                  "or is locked) \u2014 try again in a moment")

    def __init__(self, directory, game_id, local_side, marker_path=None,
                 legacy_markers=()):
        self.mailbox = Mailbox(directory, game_id)
        self.local_side = side_index(local_side)
        self.game_id = self.mailbox.game_id
        #: Where *this player's* progress lives.  Deliberately outside the
        #: shared folder: two players must be able to disagree about how far
        #: they have got without overwriting each other's idea of it.
        self.marker_path = marker_path
        #: Marker paths an earlier build used (no folder hash in the name).  A
        #: game in progress across the upgrade is picked up from one of them.
        self.legacy_markers = [path for path in (legacy_markers or ()) if path]
        self.applied = {}
        self.notices = []          # human lines produced by the last operation
        #: Problems already surfaced to the player.  A polling loop must not
        #: repeat the same complaint every few seconds, so a broken file is
        #: announced once and then only shown in the status listing.
        self._reported = set()
        #: ``(path, size, mtime) -> True`` for files the watcher thread has read
        #: in full and found intact.  The interface thread then reads a file
        #: once, without waiting, instead of sitting through the retry delays
        #: that a half-copied file needs.
        self._verified = {}
        #: Set by the watcher's stop(): ends any retry waiting at once.
        self._cancel = threading.Event()

    def _set_applied(self, **fields):
        """Replace the marker, keeping the chain of positions already held.

        The chain is *not* part of the new position, so it must survive the
        assignment; losing it makes every later move look as though it came
        from somewhere this player has never been.
        """
        seen = list(self.applied.get("seen") or [])
        self.applied = dict(fields)
        if seen:
            self.applied["seen"] = seen

    def _remember(self, checksum):
        if not checksum:
            return
        seen = [value for value in (self.applied.get("seen") or []) if value]
        if checksum in seen:
            seen.remove(checksum)
        seen.insert(0, checksum)
        self.applied["seen"] = seen[:self.SEEN_LIMIT]

    def _seen_checksums(self):
        seen = set(self.applied.get("seen") or [])
        if self.applied_checksum:
            seen.add(self.applied_checksum)
        return seen

    # -- marker -------------------------------------------------------------

    def load_marker(self):
        """Read the progress marker.  Interface thread only (see ``open``).

        Also drops a marker that is further on than anything in the folder (left
        over from an earlier game with the same code); that used to be done by
        ``status()`` on the watcher thread, racing with ``submit()``.
        """
        if not self.marker_path:
            return {}
        migrated = False
        try:
            with open(self.marker_path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            data = None
            if not os.path.exists(self.marker_path):
                data = self._read_legacy_marker()
                migrated = data is not None
        if isinstance(data, dict):
            # A marker written for another folder belongs to another game that
            # happened to use the same code: do not let it hide this one.
            folder = data.pop("folder", None)
            if folder and folder != self._folder_key():
                return self.applied
            self.applied = data
            if migrated:
                if self.save_marker():
                    try:
                        os.remove(self._legacy_used)
                    except OSError:
                        pass
        self._drop_stale_marker()
        return self.applied

    def _read_legacy_marker(self):
        """The first usable marker an earlier build left, or ``None``.

        Taken only when it names this folder or none at all (the old build did
        not record one), and removed once the new marker is written, so it
        cannot be adopted a second time by a different folder.
        """
        for path in self.legacy_markers:
            if os.path.abspath(path) == os.path.abspath(self.marker_path):
                continue
            try:
                with open(path, encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            folder = data.get("folder")
            if folder and folder != self._folder_key():
                continue
            self._legacy_used = path
            return data
        return None

    def _drop_stale_marker(self):
        if self.applied_seq <= 0:
            return
        try:
            moves, problems = self.mailbox.scan()
        except MailError:
            return
        # A newest file that cannot be read yet would look like "nothing there".
        if problems or not moves:
            return
        if self.applied_seq > moves[-1].seq:
            self.applied = {}

    def _folder_key(self):
        return os.path.normcase(self.mailbox.directory)

    def save_marker(self):
        if not self.marker_path:
            return False
        directory = os.path.dirname(os.path.abspath(self.marker_path))
        try:
            os.makedirs(directory, exist_ok=True)
            temporary = self.marker_path + ".part"
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(dict(self.applied, folder=self._folder_key()), handle)
            os.replace(temporary, self.marker_path)
        except OSError:
            return False
        return True

    # -- queries ------------------------------------------------------------

    @property
    def applied_seq(self):
        try:
            return int(self.applied.get("seq", 0))
        except (TypeError, ValueError):
            return 0

    @property
    def applied_checksum(self):
        return str(self.applied.get("checksum") or "")

    @property
    def local_name(self):
        return side_name(self.local_side)

    def _fresh_problems(self, problems):
        """Only the problems the player has not been told about yet."""
        fresh = []
        for problem in problems:
            key = problem.key()
            if key in self._reported:
                continue
            self._reported.add(key)
            fresh.append(problem)
        return fresh

    def status(self):
        """Everything a dialog shows: whose turn, and when the other moved."""
        try:
            moves, problems = self.mailbox.scan()
        except MailError as exc:
            return {"ok": False, "message": str(exc), "problems": [],
                    "conflict": None, "pending": False, "to_move": None,
                    "local_side": self.local_name, "applied_seq": self.applied_seq}
        latest = moves[-1] if moves else None
        # Read-only: this runs on the watcher thread.  A marker that is ahead of
        # the folder is dealt with when the mailbox is opened (``load_marker``).
        pending = [move for move in moves if move.seq is not None
                   and move.seq > self.applied_seq]
        # Read the waiting files in full *here* (status() runs on the watcher
        # thread, where waiting for a half-copied file costs nothing) so that
        # "Load" on the interface thread never has to.  A file that is still
        # being copied is not offered yet; it shows up once it is whole.
        unreadable = []
        # (A player who has never loaded anything gets only the newest position
        # offered -- see ``pending_moves`` -- so only that one is worth reading.)
        to_check = pending if self.applied_checksum else pending[-1:]
        for move in list(to_check):
            if self._cancel.is_set():
                break
            if not self._verify(move):
                pending.remove(move)
                unreadable.append(move)
                problems = problems + [Problem(
                    move.path, "incomplete",
                    "is still being copied or is damaged; it will be offered "
                    "as soon as it can be read")]
        # The conflict scan deliberately looks at the move we are *on* as well:
        # a fork is usually noticed by the player who already acted, as their
        # own move and the opponent's sitting at the same number.
        recent = [move for move in moves if move.seq is not None
                  and move.seq >= self.applied_seq]
        mine = None
        theirs = None
        for move in moves:
            if move.side.upper() == self.local_name:
                mine = move
            else:
                theirs = move
        to_move = None
        if latest is not None:
            if latest.to_move:
                to_move = latest.to_move
            elif latest.side in SIDE_NAMES:
                to_move = side_name(other_side(SIDE_NAMES.index(latest.side)))
        return {
            "ok": True,
            "folder": self.mailbox.directory,
            "game": self.game_id,
            "local_side": self.local_name,
            "applied_seq": self.applied_seq,
            "latest_seq": latest.seq if latest is not None else 0,
            "latest": latest,
            "mine": mine,
            "theirs": theirs,
            "theirs_when": _stamp(theirs.created or theirs.mtime) if theirs else "",
            "theirs_seen": _stamp(theirs.mtime) if theirs else "",
            "pending": bool(pending),
            "pending_count": len(pending),
            "unreadable_count": len(unreadable),
            "to_move": to_move,
            # The last move of a finished game is the last move there is: the
            # receiver loads it (and sees the end screen), and ``submit`` refuses
            # anything after it.  ``my_turn`` keeps its meaning ("the file is
            # addressed to me") so that loading it stays possible; a dialog may
            # also use ``game_over`` to grey out Send.
            "game_over": bool(latest is not None and latest.game_over),
            "my_turn": bool(to_move) and to_move == self.local_name,
            "conflict": self._find_conflict(recent),
            "problems": problems,
            "new_problems": self._fresh_problems(problems),
        }

    def _verify(self, move):
        """Is this file readable in full?  (Slow when it is not: watcher thread.)"""
        try:
            stat = os.stat(move.path)
            key = (move.path, stat.st_size, int(stat.st_mtime))
        except OSError:
            return False
        if key in self._verified:
            return True
        try:
            move.loaded(cancel=self._cancel)
        except GameFile.GameFileError:
            return False
        if len(self._verified) > 64:
            self._verified.clear()
        self._verified[key] = True
        return True

    def _find_conflict(self, pending):
        """Two unapplied moves claiming the same turn number (a fork)."""
        by_seq = {}
        for move in pending:
            by_seq.setdefault(move.seq, []).append(move)
        for seq, group in sorted(by_seq.items()):
            parents = set(move.parent for move in group)
            sides = set(move.side.upper() for move in group)
            if len(group) > 1 and (len(parents) > 1 or len(sides) > 1):
                names = [os.path.basename(move.path) for move in group]
                return {
                    "seq": seq,
                    "files": names,
                    "paths": [move.path for move in group],
                    "message": ("two players moved from the same position: "
                                "%d files claim move %s (%s). Decide which one "
                                "counts before loading either."
                                % (len(group), seq, ", ".join(names))),
                }
        return None

    def pending_moves(self):
        """Moves this player should consider loading, oldest first.

        Anything newer is obvious.  A move at the *same* number as the one
        already applied is included only when it is a different position — that
        is the other half of "both players acted on the same turn", seen by the
        player who acted: the folder holds their own move and the opponent's for
        the same turn, and one of the two has to go.  Loading the opponent's is
        the "their move counts" answer; deleting their file is the other.

        When this player has never applied anything (a fresh join into a game
        already under way) only the newest move is returned: each file is a
        complete position, so the intermediates would only cost time.
        """
        moves, _problems = self.mailbox.scan()
        fresh = []
        for move in moves:
            if move.seq is None or move.seq < self.applied_seq:
                continue
            if move.seq > self.applied_seq:
                fresh.append(move)
                continue
            if not self.applied_checksum or move.side.upper() == self.local_name:
                continue
            try:
                checksum = move.position_checksum(retries=1)
            except GameFile.GameFileError:
                fresh.append(move)          # let the caller report the damage
                continue
            if checksum != self.applied_checksum:
                fresh.append(move)
        if not self.applied_checksum and len(fresh) > 1:
            return fresh[-1:]
        return fresh

    def explains_skips(self):
        """Why each file in the folder is not the next move (for the log)."""
        notes = []
        try:
            moves, problems = self.mailbox.scan()
        except MailError as exc:
            return [str(exc)]
        for problem in problems:
            notes.append("ignored %s" % problem.describe())
        for move in moves:
            if move.seq is None:
                continue
            if move.seq < self.applied_seq:
                notes.append("%s is stale: it is move %s and you are at move %s"
                             % (move.name, move.seq, self.applied_seq))
            elif move.seq == self.applied_seq and self.applied_seq:
                try:
                    checksum = move.position_checksum(retries=1)
                except GameFile.GameFileError as exc:
                    notes.append("ignored %s: %s" % (move.name, exc))
                    continue
                if checksum == self.applied_checksum:
                    notes.append("%s is a duplicate of the move you already "
                                 "played" % move.name)
        return notes

    # -- actions ------------------------------------------------------------

    @staticmethod
    def state_game_over(state):
        """Does this position say the game has ended (peace, or nuclear war)?"""
        world = (state or {}).get("world") or {}
        return bool(world.get("winFlag") or world.get("ANWFlag")
                    or world.get("NWFlag"))

    def submit(self, state, turn=None, game_name="", game_over=None):
        """Publish the position *after* my turn.  Returns the published move.

        Refuses to write when the folder already holds a move built on a
        position this player has not seen — that is precisely the "both players
        acted on the same turn" fork, and publishing on top of it would throw
        somebody's turn away.

        Sending is idempotent per position: pressing the button twice (or once
        from a status that had not caught up with the first press) returns the
        move that is already there instead of writing the same position as a new
        move.  The final move of a game -- the 1990 verdict, or a nuclear war --
        is sent like any other: the position says the game is over, so it is
        flagged ``game_over`` in the move and nobody is asked to move after it.
        """
        self.mailbox.ensure()
        self.notices = []
        local = self.local_name
        if game_over is None:
            game_over = self.state_game_over(state)
        human = (state.get("world") or {}).get("human")
        if human is not None and int(human) == self.local_side and not game_over:
            raise MailError(
                "this position still says %s is to move, so your turn is not "
                "finished. Complete the turn (and answer any crisis) before "
                "sending it." % local)
        moves, _problems = self.mailbox.scan()
        newest = moves[-1] if moves else None
        if newest is not None and newest.game_over:
            raise MailError("The game is over (%s): there is no further move to "
                            "send." % newest.name)
        if newest is not None and newest.seq > self.applied_seq:
            raise MailError(
                "%s has already sent %s, which you have not loaded. Load it "
                "first, or your turn would be built on a position nobody else "
                "has." % (newest.side or "your opponent", newest.name))
        checksum = GameFile.state_checksum(state)
        if newest is not None and newest.side == local and not newest.opening \
                and newest.seq >= self.applied_seq:
            # Mine is the newest move and the opponent has not answered it: the
            # same position again is the same move.
            try:
                same = newest.position_checksum(retries=1) == checksum
            except GameFile.GameFileError:
                raise MailError(self.UNVERIFIED)
            if same:
                self.notices.append("%s was already sent; nothing was written "
                                    "again" % newest.name)
                return newest
        if newest is not None and newest.seq == self.applied_seq \
                and self.applied_checksum and newest.side != local:
            # Same move number, written by the opponent: somebody built a move
            # from the position I already moved from.  Publishing mine on top
            # would quietly erase theirs.
            try:
                other = newest.position_checksum(retries=1)
            except GameFile.GameFileError:
                raise MailError(self.UNVERIFIED)
            if other and other != self.applied_checksum:
                raise MailError(
                    "%s and your move are both built on move %s, but from "
                    "different positions: you and your opponent moved at the "
                    "same time. Compare notes and keep only one of the two "
                    "moves." % (newest.name, self.applied_seq))
        seq = max(self.applied_seq, newest.seq if newest is not None else 0) + 1
        meta = {
            "game": self.game_id,
            "seq": seq,
            "side": local,
            "to_move": side_name(other_side(self.local_side)),
            "parent": self.applied_checksum,
            "player": game_name,
            "year": (state.get("world") or {}).get("year"),
            # How crises were handled (see MAIL_CRISES_CONTESTED).
            "crises": "contested" if MAIL_CRISES_CONTESTED else "uncontested",
        }
        if game_over:
            meta["game_over"] = True
        path = self.mailbox.write_move(state, meta, turn=turn)
        self._set_applied(seq=seq, checksum=checksum,
                          file=os.path.basename(path), at=time.time(),
                          turn=turn, moved_by=local)
        self._remember(checksum)
        self.save_marker()
        return Move(path, GameFile.read_header(path))

    def start_game(self, state, turn=None, game_name=""):
        """Publish the opening position and give the folder to the opponent.

        This is move 1 and it is *not* a completed turn — ``to_move`` is the
        creator — so the opponent can pull the starting position (and the level,
        the sides and the year with it) without having to play first.  Only one
        player ever calls this; the other one just opens the folder.
        """
        self.mailbox.ensure()
        existing = self.mailbox._candidate_names()
        if existing:
            raise MailError(
                "this folder already holds moves for the game \u201c%s\u201d "
                "(%d file%s, e.g. %s). Starting again would mix the new game "
                "into the old one. Open that game instead, pick another game "
                "name, or choose an empty folder."
                % (self.game_id, len(existing), "" if len(existing) == 1 else "s",
                   existing[0]))
        local = self.local_name
        meta = {
            "game": self.game_id,
            "seq": 1,
            "side": local,
            "to_move": local,
            "parent": "",
            "opening": True,
            "player": game_name,
            "year": (state.get("world") or {}).get("year"),
            "crises": "contested" if MAIL_CRISES_CONTESTED else "uncontested",
        }
        path = self.mailbox.write_move(state, meta, turn=turn)
        checksum = GameFile.state_checksum(state)
        self._set_applied(seq=1, checksum=checksum,
                          file=os.path.basename(path), at=time.time(),
                          turn=turn, moved_by=local, opening=True)
        self._remember(checksum)
        self.save_marker()
        return Move(path, GameFile.read_header(path))

    def apply_next(self, world, replace_own=False):
        """Load every pending opponent move, oldest first.  Returns the last.

        Raises :class:`MailError` when there is nothing to load, or when the
        move does not belong to this player, and
        :class:`Net.GameFile.GameFileError` when a file cannot be trusted.

        When the folder holds *your own* move and your opponent's for the same
        turn (a fork), loading theirs would throw your move away.  That is
        refused with :class:`MailForkError` unless the caller passes
        ``replace_own=True`` after asking the player.
        """
        pending = self.pending_moves()
        if not pending:
            raise MailError("no new move in the folder")
        # Refuse the whole batch when the folder holds a fork: applying one of
        # two competing moves and then failing on the other would leave the
        # player halfway through a decision that is theirs to make.
        conflict = self._find_conflict(pending)
        if conflict is not None:
            raise MailError(conflict["message"])
        if not replace_own:
            own = self._own_move_at(self.applied_seq)
            clash = [m for m in pending if m.seq == self.applied_seq]
            if own is not None and clash:
                theirs = clash[0]
                raise MailForkError(
                    "You and %s both moved from the same position: your move "
                    "%s and their %s are for the same turn. Loading theirs would "
                    "throw your move away. Decide which one counts: load theirs "
                    "only if you are sure, or keep yours and ask them to "
                    "delete %s."
                    % (side_name(other_side(self.local_side)), own.name,
                       theirs.name, theirs.name),
                    conflict={"seq": self.applied_seq,
                              "files": [own.name, theirs.name],
                              "paths": [own.path, theirs.path],
                              "message": "fork at move %s" % self.applied_seq})
        self.notices = []
        applied = None
        for move in pending:
            applied = self._apply_one(world, move)
        return applied

    def _own_move_at(self, seq):
        """My own move file for ``seq``, if it is still in the folder."""
        try:
            moves, _problems = self.mailbox.scan()
        except MailError:
            return None
        for move in moves:
            if move.seq == seq and move.side.upper() == self.local_name \
                    and not move.opening:
                return move
        return None

    def _apply_one(self, world, move):
        if move.side.upper() == self.local_name:
            raise MailError("%s was sent by you (%s), so there is nothing in it "
                            "to load" % (move.name, self.local_name))
        if not move.opening and move.to_move \
                and move.to_move.upper() != self.local_name:
            raise MailError("%s is addressed to %s, not to you (%s)"
                            % (move.name, move.to_move, self.local_name))
        # One attempt, no waiting: this runs on the interface thread, and the
        # watcher has already read the file in full (see ``status``).
        document = move.loaded(retries=1)
        checksum = GameFile.state_checksum(document["state"])
        seen = self._seen_checksums()
        if seen and move.parent and move.parent not in seen:
            raise MailError(
                "%s was made from a game you have never seen. Somebody else "
                "moved from the same turn, so compare notes before loading it."
                % move.name)
        self.notices.append("loaded %s" % move.describe())
        if move.seq == self.applied_seq and self.applied_checksum:
            # The "their move counts" answer to a fork: the move made here for
            # this turn is discarded in favour of the one that arrived.
            self.notices.append("the move you had made for turn %s was replaced "
                                "by %s" % (move.seq, move.name))
        GameFile.install_into(world, document)
        self._set_applied(seq=move.seq, checksum=checksum, file=move.name,
                          at=time.time(), turn=move.turn, moved_by=move.side,
                          received_at=move.mtime, opening=move.opening)
        self._remember(checksum)
        self.save_marker()
        return move


class MailWatcher(QThread):
    """Polls a :class:`MailSession` off the UI thread.

    The folder may be an SMB mount that takes seconds to answer; a ``QTimer``
    doing this on the GUI thread would freeze the window exactly as badly as a
    blocking socket read.  The thread only calls the session's read-only
    queries, so there is nothing to lock.
    """

    statusChanged = pyqtSignal(dict)

    def __init__(self, session, interval_ms=DEFAULT_POLL_MS, parent=None):
        super().__init__(parent)
        self.session = session
        self.interval_ms = max(500, int(interval_ms))
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()
        self.session._cancel.set()

    def run(self):
        while not self._stop.is_set():
            try:
                status = self.session.status()
            except Exception as exc:            # a watcher must never die
                status = {"ok": False, "message": "%s" % exc, "problems": [],
                          "conflict": None, "pending": False, "to_move": None}
            if self._stop.is_set():
                break
            self.statusChanged.emit(status)
            waited = 0
            while waited < self.interval_ms and not self._stop.is_set():
                self.msleep(100)
                waited += 100


#: Watchers that outlived a close(); held here so Qt never destroys a running one.
_ORPHANS = []


class MailGame(QObject):
    """The dialog-facing facade: one mail session plus its polling watcher."""

    statusChanged = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = None
        self.watcher = None

    # -- lifecycle ----------------------------------------------------------

    def open(self, directory, game_id, local_side, marker_path=None,
             interval_ms=DEFAULT_POLL_MS, legacy_markers=()):
        """Attach to a shared folder.  Returns the :class:`MailSession`."""
        self.close()
        session = MailSession(directory, game_id, local_side,
                              marker_path=marker_path,
                              legacy_markers=legacy_markers)
        session.mailbox.ensure()
        session.load_marker()
        self.session = session
        self.watcher = MailWatcher(session, interval_ms=interval_ms, parent=self)
        self.watcher.statusChanged.connect(self.statusChanged)
        self.watcher.start()
        return session

    def close(self):
        if self.watcher is not None:
            self.watcher.stop()
            # Bounded join: the worker sleeps in 100 ms slices and does at most
            # one listing, so it cannot hold the interface hostage.
            if not self.watcher.wait(3000):
                # Still inside a file read.  Destroying a running QThread
                # aborts the process, so park it, parentless, until it ends.
                orphan = self.watcher
                orphan.setParent(None)
                _ORPHANS.append(orphan)
                orphan.finished.connect(lambda o=orphan: _ORPHANS.remove(o)
                                        if o in _ORPHANS else None)
            self.watcher = None
        self.session = None

    # -- operations ---------------------------------------------------------

    def submit(self, state, turn=None, game_name="", game_over=None):
        if self.session is None:
            raise MailError("no mail game is open")
        return self.session.submit(state, turn=turn, game_name=game_name,
                                   game_over=game_over)

    def apply_next(self, world, replace_own=False):
        if self.session is None:
            raise MailError("no mail game is open")
        return self.session.apply_next(world, replace_own=replace_own)

    def status(self):
        if self.session is None:
            return {"ok": False, "message": "no mail game is open",
                    "problems": [], "conflict": None, "pending": False,
                    "to_move": None}
        return self.session.status()


def legacy_marker_paths(side, *codes):
    """Marker paths of the previous build: ``<code>.<SIDE>.json``, no folder hash."""
    import Paths
    paths = []
    for code in codes:
        path = os.path.join(Paths.user_dir(), "mail", "%s.%s.json"
                            % (safe_component(code, "game"), side_name(side)))
        if path not in paths:
            paths.append(path)
    return paths


def default_marker_path(game_id, side, folder=None):
    """Where this player's progress marker lives (per user, never shared).

    ``folder`` (the shared folder) is part of the name when given, so the same
    code used in another folder is another game with its own marker.
    """
    import Paths
    where = ""
    if folder:
        import hashlib
        where = "." + hashlib.sha1(os.path.normcase(os.path.abspath(
            os.path.expanduser(str(folder)))).encode("utf-8", "replace")
            ).hexdigest()[:8]
    return os.path.join(Paths.user_dir(), "mail",
                        "%s%s.%s.json" % (safe_component(game_id, "game"), where,
                                          side_name(side)))
