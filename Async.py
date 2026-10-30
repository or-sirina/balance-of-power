"""
Running a blocking call without freezing the interface.

A chat-completions request is a network round trip of anything from 400 ms to
half a minute.  Calling it straight from the turn loop would lock the window
solid for that long — no repaint, no window-manager response, and on a corporate
desktop a "not responding" ghost window.  So the call goes to a worker thread
while the main thread keeps pumping events and updates a status line.

The thread is abandoned rather than killed on timeout, and it is a plain daemon
``threading.Thread`` rather than a ``QThread``: a ``QThread`` that is still
running when the interpreter (or its parent) goes away aborts the process with
"QThread: Destroyed while thread is still running", which is exactly what a
request stuck behind a dead proxy would do at exit.  A daemon thread just dies
with the process, and a request that is allowed to finish into a discarded
result is harmless.

The worker never touches Qt.  It runs the callable and parks the outcome in a
dict; the result (or the exception) is picked up and delivered by the caller's
own thread, which is the GUI thread.
"""

import threading

from PyQt5.QtCore import QThread, QTimer
from PyQt5.QtWidgets import QApplication


def run_blocking(fn, timeout=35.0, on_tick=None, tick_ms=60, parent=None):
    """Call ``fn`` on a worker thread; keep the UI alive; return its result.

    ``on_tick`` is called every ``tick_ms`` with the elapsed milliseconds, which
    is where a caller puts a "still thinking" indicator.  ``parent`` is accepted
    for compatibility and unused: a plain thread has no Qt parent.

    Raises :class:`TimeoutError` if ``fn`` has not finished in time, and
    re-raises anything ``fn`` raised.
    """
    box = {}

    def target():
        try:
            box["result"] = fn()
        except BaseException as exc:      # re-raised on the caller's thread
            box["error"] = exc

    worker = threading.Thread(target=target, name="bop-blocking", daemon=True)
    worker.start()

    waited = 0
    while worker.is_alive() and waited < timeout * 1000:
        # processEvents is what keeps the window painting and the buttons alive.
        QApplication.processEvents()
        QThread.msleep(tick_ms)
        waited += tick_ms
        if on_tick is not None:
            try:
                on_tick(waited)
            except Exception:
                pass

    if worker.is_alive():
        raise TimeoutError("no answer within %.0f s" % (timeout,))
    if "error" in box:
        raise box["error"]
    return box.get("result")


def pump(ms=50):
    """Let Qt breathe for a moment (used between scripted steps)."""
    QApplication.processEvents()
    loop_guard = 0
    timer = QTimer()
    timer.setSingleShot(True)
    timer.start(ms)
    while timer.isActive() and loop_guard < 1000:
        QApplication.processEvents()
        QThread.msleep(5)
        loop_guard += 1
