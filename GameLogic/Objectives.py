"""
Intermediate objectives: something to aim at between 1982 and 1990.

The original game has exactly one way to find out how you are doing: the
prestige score, which only becomes legible at the very end.  For nine turns the
player is flying blind — you can be losing the unaligned world by a mile and
the interface will not say so, because the score is a single number that mostly
moves for reasons the player did not cause.

This module adds a short list of intermediate objectives, each of which is
either met or not met at any moment, so the player gets feedback while there is
still time to act on it.  Meeting one pays a prestige bonus, once.

The objectives themselves live in ``data/objectives.json`` and name a *check*
implemented here; a modder can add objectives from the existing predicates, or
repoint an objective at different countries, without touching Python.  An
unknown check name is dropped with a note rather than raising, so a bad data
file degrades to "fewer objectives" instead of "no game".

Everything here is pure logic over ``World``; the panel lives in
``Dialog/ObjectivesBar.py``.
"""

import json

import Paths

#: Treaty level at which a country counts as a formal ally rather than merely
#: friendly.  Levels 1 and 2 are the baseline "we have relations" state that
#: every country starts with; 3 and up is a real commitment.
ALLY_TREATY_LEVEL = 3

#: Objectives that could not be loaded, as (id, reason) pairs, for the UI to
#: report rather than silently swallow.
FAILED = []


class Objective(object):
    """One intermediate objective."""

    def __init__(self, oid, title, detail, reward, check, side=None, params=None,
                 short=""):
        self.id = oid
        self.title = title
        self.detail = detail
        #: A strip-sized label.  Without one the panel has to elide the title,
        #: and "…old your allian…" tells the player nothing.
        self.short = short or title
        self.reward = int(reward)
        #: Which superpower it applies to, or None for both.
        self.side = side
        self.check_name = check
        self.check = CHECKS.get(check)
        self.params = params or {}

    def applies_to(self, side_id):
        return self.side is None or int(self.side) == int(side_id)

    def met(self, world, side_id):
        """Whether the objective is currently satisfied."""
        if self.check is None or not self.applies_to(side_id):
            return False
        try:
            return bool(self.check(world, side_id, self.params))
        except (AttributeError, IndexError, KeyError, TypeError, ZeroDivisionError):
            # A malformed objective must not abort a turn; treat it as unmet and
            # leave a trace of what went wrong.
            return False

    def progress(self, world, side_id):
        """A short 'x of y' style line, when the check can supply one."""
        reporter = PROGRESS.get(self.check_name)
        if reporter is None:
            return ""
        try:
            return reporter(world, side_id, self.params)
        except (AttributeError, IndexError, KeyError, TypeError, ZeroDivisionError):
            return ""


# ---------------------------------------------------------------------------
# The checks.  Each is (world, side_id, params) -> bool.
# ---------------------------------------------------------------------------

def _opponent(world, side_id):
    return world.country[1 - int(side_id)]


def _side(world, side_id):
    return world.country[int(side_id)]


def _members(params, side_id):
    key = "members_ussr" if int(side_id) == 1 else "members_usa"
    if key in params:
        return list(params[key])
    return list(params.get("members", []))


def alliance_loyal(world, side_id, params):
    """Every founding ally still prefers us to the other superpower."""
    me, them = _side(world, side_id), _opponent(world, side_id)
    for cid in _members(params, side_id):
        if me.treaty[cid] <= them.treaty[cid]:
            return False
    return bool(_members(params, side_id))


def gulf_held(world, side_id, params):
    """Enough of the named countries think better of us than of the rival."""
    me, them = _side(world, side_id), _opponent(world, side_id)
    held = sum(1 for cid in params.get("members", [])
               if me.diplOpinion[cid] > them.diplOpinion[cid])
    return held >= int(params.get("minimum", 1))


def _sphere_total(world):
    """Sum of the "don't mess" values of the 78 minor countries.

    That number is the whole map's tilt: a high value for a country means it
    sits in the American sphere, a low one in the Soviet (see
    ``Local.TAG_SPHERE``), and the crisis ladder moves it with
    ``changeDMess``.  The superpowers' OWN values never change, which is what
    this objective used to compare, so it could not be met by anyone.
    """
    return sum(c.dMess for c in world.country[2:])


def _sphere_gain(world, side_id):
    """How far the unaligned world has moved toward ``side_id`` since the start.

    Positive is good for the side: up for the USA, down for the USSR.  A save
    made before the baseline recorded the total has nothing to measure from, so
    it starts counting from now rather than staying unreachable for ever.
    """
    base = _baseline(world, side_id)
    if base.get("dMess_total") is None:
        base["dMess_total"] = _sphere_total(world)
    moved = _sphere_total(world) - base["dMess_total"]
    return moved if int(side_id) == 0 else -moved


def sphere_growth(world, side_id, params):
    """Our sphere of influence is larger than it was at the start."""
    return _sphere_gain(world, side_id) >= int(params.get("gain", 1))


def calm_world(world, side_id, params):
    """World tension has never gone above the limit during the window.

    Once breached it stays breached: an objective called "keep the world calm
    to 1985" that a player could repair with one quiet year afterwards would be
    measuring today's tension, not the promise.  The breach is recorded when the
    objective is refreshed at the end of a turn, which is the point at which
    that turn's tension has already been accumulated.
    """
    base = _baseline(world, side_id)
    limit = int(params.get("limit", 100))
    until = int(params.get("until", 9999))
    if base.get("tension_broken"):
        return False
    if world.year > until:
        # The deadline has passed.  The promise was "calm to <year>", so what
        # happens after it is none of this objective's business; before this
        # check the objective kept being judged for the rest of the game, so a
        # breach in 1988 could still take away points promised for 1985.
        return True
    if world.nastiness > limit:
        base["tension_broken"] = True
        base["tension_broken_year"] = world.year
        return False
    return True


def clients_kept(world, side_id, params):
    """We still have most of the formal allies we started with."""
    base = _baseline(world, side_id).get("clients")
    if base is None:
        return False
    level = int(params.get("treaty_level", ALLY_TREATY_LEVEL))
    now = count_clients(world, side_id, level)
    return (base - now) <= int(params.get("max_lost", 0))


CHECKS = {
    "alliance_loyal": alliance_loyal,
    "gulf_held": gulf_held,
    "sphere_growth": sphere_growth,
    "calm_world": calm_world,
    "clients_kept": clients_kept,
}


# ---------------------------------------------------------------------------
# Progress reporters, for the panel.  Optional: a check without one shows only
# met / not met.
# ---------------------------------------------------------------------------

def _alliance_progress(world, side_id, params):
    me, them = _side(world, side_id), _opponent(world, side_id)
    members = _members(params, side_id)
    held = sum(1 for cid in members if me.treaty[cid] > them.treaty[cid])
    return "%d of %d allies still with you" % (held, len(members))


def _gulf_progress(world, side_id, params):
    me, them = _side(world, side_id), _opponent(world, side_id)
    members = params.get("members", [])
    held = sum(1 for cid in members if me.diplOpinion[cid] > them.diplOpinion[cid])
    return "%d of %d, %d needed" % (held, len(members), int(params.get("minimum", 1)))


def _sphere_progress(world, side_id, params):
    return "sphere %+d since 1982" % _sphere_gain(world, side_id)


def _calm_progress(world, side_id, params):
    base = _baseline(world, side_id)
    if base.get("tension_broken"):
        return "tension passed %d in %s \u2014 this one is lost" % (
            int(params.get("limit", 100)), base.get("tension_broken_year", "?"))
    until = int(params.get("until", 9999))
    if world.year > until:
        # Past the deadline the promise is settled; today's tension is not
        # its business, so show the verdict rather than a live reading that
        # contradicts it ("holding | tension 123, limit 100" in 1988).
        return "kept to %d \u2014 tension stayed under %d" % (
            until, int(params.get("limit", 100)))
    return "tension %d, limit %d" % (world.nastiness, int(params.get("limit", 100)))


def _clients_progress(world, side_id, params):
    base = _baseline(world, side_id).get("clients")
    if base is None:
        return ""
    level = int(params.get("treaty_level", ALLY_TREATY_LEVEL))
    return "%d of %d allies still with you" % (count_clients(world, side_id, level), base)


PROGRESS = {
    "alliance_loyal": _alliance_progress,
    "gulf_held": _gulf_progress,
    "sphere_growth": _sphere_progress,
    "calm_world": _calm_progress,
    "clients_kept": _clients_progress,
}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _read_data():
    try:
        with open(Paths.data("objectives.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        FAILED.append(("*", "objectives.json unreadable: %s" % exc))
        return None


def load():
    """Load the objective list, dropping anything unusable.

    Cached: the panel asks for this on every interface refresh, and re-reading
    and re-parsing a file several times a second would be silly.  Call
    :func:`reload` after changing the data file.
    """
    global _CACHE
    if _CACHE is None:
        _CACHE = _load_uncached()
    return _CACHE


def reload():
    """Drop the cache and re-read the data file."""
    global _CACHE
    _CACHE = None
    return load()


def _load_uncached():
    del FAILED[:]
    data = _read_data()
    if not isinstance(data, dict):
        return []
    objectives = []
    for entry in data.get("objectives", []):
        if not isinstance(entry, dict):
            FAILED.append(("*", "an entry is not an object"))
            continue
        check = entry.get("check")
        if check not in CHECKS:
            FAILED.append((entry.get("id", "?"), "unknown check %r" % (check,)))
            continue
        try:
            objectives.append(Objective(
                oid=entry.get("id") or check,
                title=entry.get("title", ""),
                detail=entry.get("detail", ""),
                reward=entry.get("reward", 0),
                check=check,
                side=entry.get("side"),
                params=entry.get("params") or {},
                short=entry.get("short", "")))
        except (TypeError, ValueError) as exc:
            FAILED.append((entry.get("id", "?"), str(exc)))
    return objectives


#: Parsed objectives, filled on first use.
_CACHE = None


# ---------------------------------------------------------------------------
# State, kept on the world so it serialises with the rest of the game
# ---------------------------------------------------------------------------

def count_clients(world, side_id, level=ALLY_TREATY_LEVEL):
    """How many countries are formal allies of ``side_id``."""
    side = _side(world, side_id)
    return sum(1 for c in world.country[2:] if side.treaty[c.id] >= level)


def _state(world):
    state = getattr(world, "objectiveState", None)
    if state is None:
        state = world.objectiveState = {"baseline": {}, "held": {}, "ever": {},
                                       "bonus": [0, 0]}
    for key, empty in (("baseline", {}), ("held", {}), ("ever", {})):
        state.setdefault(key, empty)
    state.setdefault("bonus", [0, 0])
    return state


def _key(side_id):
    """The state's key for one side.

    Stringified because this state travels: ``Net/State`` turns every dict key
    into a string for JSON, so a mirror -- and an undo, which restores through
    the same path -- came back with "0" where the code then looked for 0.  The
    objectives quietly reset themselves on every network update.
    """
    return str(int(side_id))


def _baseline(world, side_id):
    baseline = _state(world)["baseline"]
    return baseline.setdefault(_key(side_id), {})


def snapshot(world):
    """Record the starting position, the moment a game begins.

    Called once per game: ``sphere_growth`` and ``clients_kept`` are only
    meaningful against the position the player actually inherited.
    """
    state = _state(world)
    state["baseline"] = {}
    state["held"] = {}
    state["ever"] = {}
    state["bonus"] = [0, 0]
    for side_id in (0, 1):
        base = _baseline(world, side_id)
        base["dMess"] = _side(world, side_id).dMess      # kept for old readers
        base["dMess_total"] = _sphere_total(world)
        base["clients"] = count_clients(world, side_id)
        base["tension_broken"] = False
    # A commitment that holds in 1982 counts from 1982.  Without this the strip
    # would show three objectives holding and a bonus of zero until the first
    # turn ended, which reads as a bug because it is one.
    for side_id in (0, 1):
        refresh(world, side_id)
    return state


def ensure_state(world):
    """Make sure a world has objective state, for saves made before it existed."""
    state = getattr(world, "objectiveState", None)
    if not state or not state.get("baseline"):
        snapshot(world)
    return _state(world)


def evaluate(world, side_id):
    """Return ``[(objective, met, progress_text)]`` for one superpower."""
    ensure_state(world)
    rows = []
    for objective in load():
        if not objective.applies_to(side_id):
            continue
        rows.append((objective, objective.met(world, side_id),
                     objective.progress(world, side_id)))
    return rows


def refresh(world, side_id):
    """Recompute one side's objective standing for this turn.

    These are *standing commitments*, not achievements.  A reward is held only
    while its objective holds: the alliance intact now is worth points now, and
    it stops being worth them the moment an ally defects.  Paying out once and
    forgetting would be worse than useless — three of the five are already true
    in 1982, so a one-off award would hand the player 350 points on turn one for
    doing nothing at all.

    Returns ``(bonus, newly_met, newly_lost)`` where the last two are lists of
    objective titles, for the interface to report a change.
    """
    state = ensure_state(world)
    held = state["held"].setdefault(_key(side_id), {})
    ever = state["ever"].setdefault(_key(side_id), {})
    total = 0
    newly_met, newly_lost = [], []
    for objective, is_met, _progress in evaluate(world, side_id):
        if is_met:
            total += objective.reward
            ever[objective.id] = True
            if not held.get(objective.id):
                newly_met.append(objective.title)
        elif held.get(objective.id):
            newly_lost.append(objective.title)
        held[objective.id] = bool(is_met)
    state["bonus"][int(side_id)] = total
    return total, newly_met, newly_lost


def award(world, side_id):
    """Backwards-compatible wrapper: refresh and return what is newly met."""
    _bonus, newly_met, _lost = refresh(world, side_id)
    return newly_met


def ever_met(world, side_id, objective_id):
    """Whether the objective has ever been held this game.

    Kept separately from "held now" so the panel can tell "you are keeping this
    up" from "you had it once and lost it", which are very different things to a
    player reading a scoreboard.
    """
    state = ensure_state(world)
    return bool(state["ever"].setdefault(_key(side_id), {}).get(objective_id))


def bonus(world, side_id):
    """What the currently-held commitments are worth to one superpower.

    Derived rather than stored.  A cached total is one more thing that can drift
    out of step with the list beside it - and it did: the strip counted four
    objectives holding while displaying the bonus from three, because the world
    had moved on since the total was last written.  The check for ``calm_world``
    records a breach as it goes, so evaluating here is also what keeps that one
    honest even if a turn never calls :func:`refresh`.
    """
    total = 0
    for objective, is_met, _progress in evaluate(world, side_id):
        if is_met:
            total += objective.reward
    return total


def summary(world, side_id):
    """``(met, total)`` for a compact counter in the interface."""
    rows = evaluate(world, side_id)
    return sum(1 for _, is_met, _ in rows if is_met), len(rows)
