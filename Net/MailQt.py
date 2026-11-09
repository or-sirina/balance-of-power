"""Optional Qt adapters for the portable mail protocol."""
from PyQt5.QtCore import QObject, QThread, pyqtSignal
from Net.MailGame import *

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
