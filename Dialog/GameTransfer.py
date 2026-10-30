"""
Moving a whole game in and out of the running window.

:mod:`Net.GameFile` knows the bytes; this module knows the *window*.  It exists
because both save slots (a game you carry on a USB stick) and play-by-mail
(:mod:`Net.MailGame`, a game you leave in a shared folder) need exactly the same
two operations: "write what I have now" and "become this other position".

Installing in place is the whole trick.  ``MainWindow.setWorld`` would swap in a
new ``World`` object, but the map polygons, the close-up window and the policy
dialog all hold references to the *current* ``Country`` objects, so a rebuilt
graph blanks the map.  :func:`Net.State.apply_state` mutates the existing
objects, which is what the network path already relies on for every snapshot —
an imported game is simply a snapshot that arrived by email.

The widget poking below is deliberately defensive and confined to one function:
if ``MainWindow`` were to grow a real ``installGame(document)`` hook (see
``docs/PATCH-REQUESTS-network.md``), this file would shrink to two calls.
"""

import time

from Net import GameFile


#: The two superpowers, by the same names the wire protocol uses.  Deliberately
#: not ``Country.name``: that is the *leader*, and a leader changes when the
#: government falls.
SIDE_NAMES = ("USA", "USSR")


def side_name(side):
    """``"USA"`` or ``"USSR"`` for a side index."""
    try:
        return SIDE_NAMES[int(side)]
    except (IndexError, TypeError, ValueError):
        return "side %s" % (side,)


def document_meta(world, game_name="", extra=None):
    """The header metadata written next to an exported position."""
    meta = {
        "game": game_name or "Balance of Power %d" % world.year,
        "year": world.year,
        "level": world.level,
        "two_player": bool(world.twoPFlag),
        "human": side_name(world.human),
        "cmptr": side_name(1 - world.human),
        "scores": [world.country[0].score - world.country[0].initScore,
                   world.country[1].score - world.country[1].initScore],
    }
    if extra:
        meta.update(extra)
    return meta


def export_to(parent, path, game_name="", turn=None, extra_meta=None):
    """Write the window's world to ``path``.  Returns the file header.

    Raises :class:`Net.GameFile.GameFileError` with a player-readable message.
    """
    world = getattr(parent, "world", None)
    if world is None:
        raise GameFile.GameFileError("there is no game to export yet")
    meta = document_meta(world, game_name=game_name, extra=extra_meta)
    return GameFile.export_world(world, path, meta=meta, turn=turn)


def install(parent, document, side=None, extra=None):
    """Make ``parent``'s window play ``document``'s position.

    ``side``, when given, forces which superpower the local player is; the saved
    position is otherwise taken at face value.  Returns the world.
    """
    world = getattr(parent, "world", None)
    if world is None:
        raise GameFile.GameFileError("this window has no world to load into")

    # Prefer the window's own hook: it owns the bookkeeping that has to follow a
    # position change, and this module's guarded reproduction of it would
    # silently stop applying a step the day ``setWorld`` grows a new one.
    hook = getattr(parent, "installGame", None)
    if callable(hook):
        return hook(document, side)

    # Validate and apply first (install_into rolls back on failure); only then
    # leave any session, so a bad file cannot cost the player a live game.
    GameFile.install_into(world, document)
    leave = getattr(parent, "leave_session", None)
    if callable(leave):
        try:
            leave()
        except Exception:                      # a broken session must not stop
            pass                               # the import
    _clear_transient_state(parent)

    if side is not None:
        world.human = int(side)
        world.cmptr = 1 - int(side)

    resync_window(parent, world, side)
    return world


def _clear_transient_state(parent):
    """Drop state that belongs to the position we are replacing.

    ``leave_session`` clears the network bookkeeping, but a duel or a queued
    crisis holds live ``News`` objects from the *old* world; leaving one behind
    makes the next turn resolve a crisis that no longer exists.
    """
    for name, value in (("duel", None), ("crisis_pending", False),
                        ("crisis_queue", []), ("remote_turn", -1)):
        if hasattr(parent, name):
            try:
                setattr(parent, name, value)
            except AttributeError:
                pass
    window = getattr(parent, "crisisWindow", None)
    if window is not None:
        try:
            window.hide()
        except (AttributeError, RuntimeError):
            pass


def resync_window(parent, world, side):
    """Re-run the parts of ``MainWindow.setWorld`` that still apply here.

    Kept in one place, guarded, and commented, so that a future
    ``MainWindow.installGame`` has an obvious list of what to absorb.
    """
    if callable(getattr(parent, "updateLevel", None)):
        parent.updateLevel()
    parent.local_side = int(world.human if side is None else side)
    news = getattr(parent, "newsWindow", None)
    if news is not None:
        try:
            news.setLocked(any((world.winFlag, world.ANWFlag, world.NWFlag)))
            news.question.setEnabled(False)
            news.backDown.setEnabled(False)
            news.filters[2 * world.cmptr].setChecked(True)
            news.setAdvisorSide(world.human)
        except (AttributeError, IndexError, RuntimeError):
            pass
    setup = getattr(parent, "setup_llm_opponent", None)
    if callable(setup):
        try:
            # Level 5 is the model-backed opponent; an imported network game is
            # never one, and setup_llm_opponent already clears it for twoPFlag.
            setup(world.level)
        except Exception:
            pass
    for name in ("reset_undo_history", "refresh_ui", "check_game_over"):
        method = getattr(parent, name, None)
        if callable(method):
            method()
    if callable(getattr(parent, "setStatus", None)):
        parent.setStatus(-1)
    if world.twoPFlag:
        # Two humans, one of them at this keyboard for now (hot-seat play, or a
        # play-by-mail turn that just arrived).  Say so in the status bar, since
        # nothing else on screen distinguishes it from a single-player game.
        try:
            parent.statusBarWidget.setHoverText(
                "%s to move" % side_name(world.human))
        except (AttributeError, RuntimeError):
            pass


def read(path, retries=GameFile.READ_RETRIES):
    """Read a game file, turning failures into player-readable errors."""
    return GameFile.read_game(path, retries=retries)


def summary(document):
    """A short human line about a document, for dialogs and logs."""
    parts = [GameFile.describe(document)]
    meta = document.get("meta") or {}
    scores = meta.get("scores") or []
    if scores:
        parts.append("score " + " / ".join("{:+,}".format(int(s)) for s in scores))
    return " | ".join(parts)


def export_filename(world, prefix="Balance of Power", turn=None):
    """A friendly, filesystem-safe default name for an exported position."""
    stamp = time.strftime("%Y%m%d-%H%M")
    pieces = [prefix, str(world.year)]
    if turn is not None:
        pieces.append("turn%s" % turn)
    pieces.append(stamp)
    safe = "-".join("".join(c for c in piece if c.isalnum() or c in " -_")
                    for piece in pieces)
    return safe.strip().replace(" ", "_") + GameFile.SUFFIX
