"""
Replicating a live :class:`GameLogic.World.World` across the network.

The host is authoritative: it owns the ``World`` and every rule runs there.
Clients hold a mirror of the same object which they only ever *update from* the
host, never advance on their own.  That removes any dependence on the two
machines agreeing about Python's random number generator, and it means a client
can join a game that is already in progress.

The translation is deliberately generic — it walks ``__dict__`` and rewrites
object references into ids — so that adding a field to ``Country`` or ``World``
does not require touching this file.
"""

from GameLogic.Crisis import Crisis
from GameLogic.News import News

#: Attributes that must never cross the wire.
_SKIP_WORLD = {"USA", "USSR", "country", "news", "crisis"}
_SKIP_COUNTRY = {"parent", "mapPolyObject", "history"}
_SKIP_NEWS = set()
_SKIP_HISTORY = {"c"}
_SKIP_CRISIS = set()


# --- encoding ---------------------------------------------------------------

def _encode(value, country_ids):
    """Convert a live value into something ``json`` can serialise."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_encode(item, country_ids) for item in value]
    if isinstance(value, dict):
        return {str(key): _encode(item, country_ids) for key, item in value.items()}
    # Object references are replaced by a marker.
    if hasattr(value, "id") and id(value) in country_ids:
        return {"__country__": country_ids[id(value)]}
    if isinstance(value, News):
        return {"__news__": _encode_object(value, _SKIP_NEWS, country_ids)}
    raise TypeError("cannot serialise %r" % (type(value).__name__,))


def _encode_object(obj, skip, country_ids):
    out = {}
    for key, value in obj.__dict__.items():
        if key in skip:
            continue
        try:
            out[key] = _encode(value, country_ids)
        except TypeError:
            continue  # un-serialisable helper attribute: safely dropped
    return out


def _encode_history(history, country_ids):
    out = {}
    for key, value in history.__dict__.items():
        if key in _SKIP_HISTORY:
            continue
        out[key] = _encode(value, country_ids)
    return out


def world_to_state(world):
    """Return a JSON-serialisable snapshot of ``world``."""
    country_ids = {id(c): c.id for c in world.country}
    state = {
        "world": _encode_object(world, _SKIP_WORLD, country_ids),
        "countries": [_encode_object(c, _SKIP_COUNTRY, country_ids) for c in world.country],
        "histories": [_encode_history(c.history, country_ids) for c in world.country],
        "news": [_encode_object(n, _SKIP_NEWS, country_ids) for n in world.news],
        "crisis": _encode_object(world.crisis, _SKIP_CRISIS, country_ids),
    }
    # The crisis headline is one of the entries of ``world.news``; the copy
    # inside "crisis" is only a fallback.  Its position is what lets the decoder
    # hand back the very same object, so that answering the crisis changes the
    # headline the news window shows.
    head = getattr(world.crisis, "whichHead", None)
    for index, item in enumerate(world.news):
        if item is head and head is not None:
            state["crisis_head"] = index
            break
    return state


# --- decoding ---------------------------------------------------------------

def _decode(value, countries, news_refs):
    if isinstance(value, list):
        return [_decode(item, countries, news_refs) for item in value]
    if isinstance(value, dict):
        if "__country__" in value and len(value) == 1:
            index = value["__country__"]
            if 0 <= index < len(countries):
                return countries[index]
            return None
        if "__news__" in value and len(value) == 1:
            payload = _decode(value["__news__"], countries, news_refs)
            news = News.__new__(News)
            news.__dict__.update(payload)
            news_refs.append(news)
            return news
        return {key: _decode(item, countries, news_refs)
                for key, item in value.items()}
    return value


def apply_state(world, state):
    """Mutate ``world`` in place so that it matches ``state``.

    Everything is updated in place on purpose: the UI holds references to
    ``Country`` objects (map polygons, the close-up window, the policy dialog)
    and rebuilding the object graph would invalidate all of them.
    """
    countries = list(world.country)

    # News objects are reconstructed first so that country attributes pointing
    # at a headline (crisis bookkeeping) can resolve.
    news_refs = []
    news = []
    for payload in state.get("news", ()):
        decoded = _decode(payload, countries, news_refs)
        item = News.__new__(News)
        item.__dict__.update(decoded)
        news.append(item)

    def resolve(value, pending_news):
        return _decode(value, countries, pending_news)

    # World scalars
    for key, value in state.get("world", {}).items():
        setattr(world, key, resolve(value, news_refs))

    # Countries
    for index, payload in enumerate(state.get("countries", ())):
        if index >= len(countries):
            break
        country = countries[index]
        for key, value in payload.items():
            setattr(country, key, resolve(value, news_refs))
        # Keep the back reference intact; it is never serialised.
        country.parent = world

    # Histories
    for index, payload in enumerate(state.get("histories", ())):
        if index >= len(countries):
            break
        history = countries[index].history
        for key, value in payload.items():
            setattr(history, key, resolve(value, news_refs))
        history.c = countries[index]

    # News list
    world.news = list(news)

    # Crisis
    crisis_payload = state.get("crisis")
    if crisis_payload:
        for key, value in crisis_payload.items():
            setattr(world.crisis, key, resolve(value, news_refs))
    # States from before "crisis_head" existed keep the separate copy.
    head_index = state.get("crisis_head")
    if isinstance(head_index, int) and not isinstance(head_index, bool) \
            and 0 <= head_index < len(world.news):
        world.crisis.whichHead = world.news[head_index]

    world.USA = countries[0]
    world.USSR = countries[1]
    return world


class StateError(ValueError):
    """A state document that cannot be applied to this world."""


_FORBIDDEN_KEYS = {
    "world": _SKIP_WORLD,
    "country": _SKIP_COUNTRY,
    "history": _SKIP_HISTORY,
}


def _kind(value):
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return None


def _check_payload(label, payload, target, forbidden):
    if not isinstance(payload, dict):
        raise StateError("%s is not an object" % label)
    for key, value in payload.items():
        if not isinstance(key, str) or key.startswith("__") or key in forbidden:
            raise StateError("%s has a field that may not be set (%r)"
                             % (label, key))
        current = getattr(target, key, None)
        if current is None or value is None or callable(current):
            continue
        # Plain data may not change its kind: a string where a score belongs
        # would only blow up later, in the middle of somebody's turn.
        if _kind(current) is not None and _kind(current) != _kind(value) \
                and not (_kind(current) == "dict" and _kind(value) == "dict"):
            raise StateError("%s: %r should be a %s, not a %s"
                             % (label, key, _kind(current), _kind(value)))


def validate_state(world, state):
    """Raise :class:`StateError` unless ``state`` fits ``world``.

    Checksums only prove a file arrived intact; anybody can write a file with a
    valid checksum and nonsense inside, and a half-applied nonsense state would
    leave the live game unusable.
    """
    if not isinstance(state, dict):
        raise StateError("the game state is not an object")
    count = len(world.country)
    for key in ("world", "countries", "histories", "news"):
        if key not in state and key in ("world", "countries"):
            raise StateError("the game state has no %r section" % key)
    countries = state.get("countries")
    if not isinstance(countries, list) or len(countries) != count:
        raise StateError("the game holds %s countries, this copy has %d"
                         % (len(countries) if isinstance(countries, list)
                            else "no", count))
    histories = state.get("histories", [])
    if not isinstance(histories, list) or (histories and len(histories) != count):
        raise StateError("the game's histories do not match its countries")
    if not isinstance(state.get("news", []), list):
        raise StateError("the game's news is not a list")
    _check_payload("world", state["world"], world, _FORBIDDEN_KEYS["world"])
    for index, payload in enumerate(countries):
        _check_payload("country %d" % index, payload, world.country[index],
                       _FORBIDDEN_KEYS["country"])
    for index, payload in enumerate(histories):
        _check_payload("history %d" % index, payload, world.country[index].history,
                       _FORBIDDEN_KEYS["history"])
    for index, payload in enumerate(state.get("news", [])):
        if not isinstance(payload, dict):
            raise StateError("news item %d is not an object" % index)
    crisis = state.get("crisis")
    if crisis and not isinstance(crisis, dict):
        raise StateError("the game's crisis is not an object")
    if isinstance(crisis, dict):
        _check_payload("crisis", crisis, world.crisis, _SKIP_CRISIS)


def apply_state_safely(world, state):
    """Validate, then apply ``state``; on any failure restore the old position.

    Returns ``world``.  Raises :class:`StateError` (nothing touched) or the
    original exception after rolling back.
    """
    validate_state(world, state)
    backup = world_to_state(world)
    refs = (list(world.country), world.news, world.USA, world.USSR)
    try:
        return apply_state(world, state)
    except Exception:
        try:
            apply_state(world, backup)
        finally:
            world.country[:] = refs[0]
            world.news, world.USA, world.USSR = refs[1], refs[2], refs[3]
        raise


def clone_world(world):
    """Deep-copy a world through the snapshot round-trip.

    Used by the AI simulations and by the tests.  A pickle round-trip would be
    faster, but routing it through :func:`world_to_state` keeps a single
    definition of "everything that matters" and stops the two from drifting.
    """
    return apply_state(_blank_like(world), world_to_state(world))


def _blank_like(world):
    """Create an empty shell of the same class, ready for :func:`apply_state`."""
    from GameLogic.World import World
    clone = World.__new__(World)
    clone.country = [type(c).__new__(type(c)) for c in world.country]
    for original, copy in zip(world.country, clone.country):
        copy.history = type(original.history).__new__(type(original.history))
        copy.history.c = copy
        copy.mapPolyObject = None
    clone.crisis = Crisis.__new__(Crisis)
    clone.news = []
    return clone
