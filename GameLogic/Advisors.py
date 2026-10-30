"""
The four advisors, as the people who were actually in the room.

The original game shipped four anonymous portraits and never named them.  The
1990 source shows what distinguished them: the advisor index is passed as the
``Bias`` argument of the same importance function that resolves crises, so
advisor 1 weights diplomatic affinity, 2 weights treaties, 3 weights sphere of
influence and 4 weights adventurousness.  Four opinions, four different
blind spots, no explanation.

Naming them after the men and women who held those posts in 1981 gives the
disagreement a reason.  A Secretary of State really does weigh relations more
than a Secretary of Defense does; a spymaster really does think in terms of
influence; an ambassador to the UN really does think in terms of commitments.

This is an addition, not a restoration: the original portraits were
unattributed.  Portraits are optional — with none installed the game falls back
to the original stylised line art, so a source checkout is playable immediately.

**The roster is data, not code.**  The personas live in ``data/advisors.json``
next to the localisation data, so a modder can add a fifth advisor, rewrite a
character or ship a translation without editing Python.  The Python tuples below
remain the built-in roster and are used verbatim whenever that file is missing
or unusable: a modded file that does not parse must never cost the player their
advisors.  :data:`ROSTER_SOURCE` says which of the two is in force and
:data:`ROSTER_ERROR` why, so a typo in the JSON is visible instead of silent.

Only the wording is localised from the roster file.  The one-line caption shown
under each portrait is ordinary UI text and comes from the localisation group
``Local.ADVISOR_BIAS`` when the locale file provides one, exactly like every
other caption in the game; ``Advisor.blurb`` is the fallback and is what the
Python-only roster carries.
"""

import json
import os

import Local
import Paths

#: Bias slots, in the order the importance function uses them.
BIAS_RELATIONS = 0
BIAS_TREATIES = 1
BIAS_INFLUENCE = 2
BIAS_RESOLVE = 3

#: File the roster is read from, inside ``data/``.
ROSTER_FILENAME = "advisors.json"

#: "builtin" or "data": where the roster currently in force came from.
ROSTER_SOURCE = "builtin"
#: Why ``data/advisors.json`` was not used.  Empty when the file is simply
#: absent, which is not an error — that is a source checkout without mods.
ROSTER_ERROR = ""

_ART_DIR = os.path.join(Paths.IMAGE_DIR, "advisors")

#: Names a modder may write in the ``bias`` field instead of the number.
_BIAS_NAMES = {
    "relations": BIAS_RELATIONS,
    "treaties": BIAS_TREATIES,
    "influence": BIAS_INFLUENCE,
    "resolve": BIAS_RESOLVE,
}

#: Caption per bias slot, used when neither the roster file nor the locale
#: provides one.  These are the original four captions.
_DEFAULT_BLURBS = {
    BIAS_RELATIONS: "weighs relations",
    BIAS_TREATIES: "weighs treaties",
    BIAS_INFLUENCE: "weighs influence",
    BIAS_RESOLVE: "weighs resolve",
}

#: The language used to pick the ``languages`` block of the roster file.  The
#: rest of the game loads its strings once at import (see ``Local.strings``), so
#: this follows the same shape: a translator sets ``BOP_LANGUAGE`` or calls
#: :func:`set_language` before the roster is built.
_LANGUAGE = os.environ.get("BOP_LANGUAGE") or "english"


class Advisor(object):
    """One seat at the table."""

    def __init__(self, key, name, role, bias, portrait, blurb, persona="",
                 side=None, index=None, style="", character=""):
        self.key = key
        self.name = name
        self.role = role
        self.bias = bias
        self.portrait = portrait
        self.blurb = blurb
        #: What this advisor believes and how he reads the world.
        self.character = character or persona
        #: How he speaks: register, manner, verbal habits.  A model told only
        #: *what* an advisor thinks still sounds like a model; told how the man
        #: actually talked, it sounds like the man.
        self.style = style
        #: Free-text override.  When given it replaces character and style, so a
        #: modder can write a whole persona without filling in the fields.
        self.persona = persona
        #: Which bench this advisor sits on, and where.  Filled in by the roster
        #: builder; the scoreboard keys its records by these.
        self.side = side
        self.index = index

    def portrait_path(self):
        """Absolute path of the photo, or None when it is not installed."""
        if not self.portrait:
            return None
        path = os.path.join(_ART_DIR, self.portrait)
        return path if os.path.exists(path) else None

    def prompt_block(self):
        """The character description handed to the language model.

        Assembled from the parts rather than stored as one blob, so that the two
        things a model actually needs - what he believes and how he talks - can
        be edited separately and translated separately.
        """
        if self.persona:
            return self.persona
        parts = ["You are %s, %s." % (self.name, self.role)]
        if self.character:
            parts.append("WHAT YOU BELIEVE\n%s" % self.character)
        if self.style:
            parts.append("HOW YOU SPEAK\n%s" % self.style)
        return "\n\n".join(parts)

    def score_key(self):
        """Stable identity of this advisor for the track record."""
        if self.side is None:
            return self.key
        return "%d:%s" % (self.side, self.key)

    def __repr__(self):
        return "<Advisor %s (%s)>" % (self.name, self.role)


#: The Reagan national security team, 1981-1985.  Blurbs omitted: they are UI
#: captions and come from the localisation group when one exists.
#: The built-in roster, used when ``data/advisors.json`` is missing or
#: unusable.  Generated to match the shipped file rather than written
#: twice: the two rosters drifting apart is a bug waiting to happen, and
#: an earlier hand-edit here left every advisor with two ``character``
#: keys, half of which Python silently discarded.
_BUILTIN_SPECS = {
    0: (
        {
            "key": "shultz", "name": "George Shultz",
            "role": "Secretary of State",
            "bias": BIAS_RELATIONS, "portrait": "usa_0.png", "blurb": "",
            "character":
                "You believe American interests are served by talking to adversaries rather "
                "than isolating them, and that a reputation for reasonableness is itself a "
                "source of power. You are suspicious of military gestures that buy nothing "
                "and cost goodwill. You have watched détente fail and you still think the "
                "attempt was right. ",
            "style":
                "Calm, lawyerly, understated. You argue from consequences and you never "
                "raise your voice. You say 'the point is' and then make it. ",
        },
        {
            "key": "kirkpatrick", "name": "Jeane Kirkpatrick",
            "role": "Ambassador to the UN",
            "bias": BIAS_TREATIES, "portrait": "usa_3.png", "blurb": "",
            "character":
                "You judge every question by what it does to America's credibility with its "
                "friends. Allies watch whether we stand by the last client before they "
                "trust us with the next; letting a friend fall is the most expensive thing "
                "a superpower can do. You distinguish sharply between authoritarian regimes "
                "we can live with and totalitarian ones we cannot. ",
            "style":
                "Crisp and combative. You name things plainly, you do not hedge, and you "
                "are willing to be the unpopular voice in the room. ",
        },
        {
            "key": "casey", "name": "William Casey",
            "role": "Director of Central Intelligence",
            "bias": BIAS_INFLUENCE, "portrait": "usa_2.png", "blurb": "",
            "character":
                "You think in terms of who actually controls the ground: covert action, "
                "arms to the right faction, quiet leverage in the capitals that matter. You "
                "distrust open diplomacy and prefer to move a country before anyone "
                "notices. You came out of the OSS and you never stopped thinking like an "
                "operator. ",
            "style":
                "Clipped and concrete. You talk about means rather than principles, and you "
                "prefer the option that is not in the newspapers. ",
        },
        {
            "key": "weinberger", "name": "Caspar Weinberger",
            "role": "Secretary of Defense",
            "bias": BIAS_RESOLVE, "portrait": "usa_1.png", "blurb": "",
            "character":
                "You believe the Soviet Union respects only strength, that the build-up is "
                "the reason there has been no war, and that arms control is a trap dressed "
                "as a courtesy. You would rather spend money than lives, and you insist "
                "that any commitment of force have a clear objective and public support. ",
            "style":
                "Deliberate and categorical. You speak of capabilities and intentions, and "
                "you are unmoved by the argument that a thing is diplomatically convenient. ",
        },
    ),
    1: (
        {
            "key": "gromyko", "name": "Andrei Gromyko",
            "role": "Minister of Foreign Affairs",
            "bias": BIAS_RELATIONS, "portrait": "ussr_0.png", "blurb": "",
            "character":
                "You have been Foreign Minister for twenty-five years and you have "
                "outlasted every American who sat across from you. You believe in parity, "
                "patience and precedent, you hate surprises, and you would rather concede "
                "slowly than appear to be pushed. ",
            "style":
                "Dry, formal, indirect. You invoke precedent and the correlation of forces, "
                "and you never answer a question you were not asked. ",
        },
        {
            "key": "chernenko", "name": "Konstantin Chernenko",
            "role": "Party ideologue",
            "bias": BIAS_TREATIES, "portrait": "ussr_3.png", "blurb": "",
            "character":
                "You are the guardian of orthodoxy. You believe the struggle is ideological "
                "as much as military, that détente was a Western trick, and that "
                "concessions invite more demands. You mistrust cleverness in younger men. ",
            "style":
                "Heavy and formulaic. You reason from doctrine, you distrust novelty, and "
                "you say so at length. ",
        },
        {
            "key": "andropov", "name": "Yuri Andropov",
            "role": "Chairman of the KGB",
            "bias": BIAS_INFLUENCE, "portrait": "ussr_2.png", "blurb": "",
            "character":
                "You know more about the other side than anyone in the room, and you know "
                "the Soviet economy is weaker than the figures admit. You prefer "
                "subversion, discipline and patience to confrontation, and you think "
                "adventurism is how empires are lost. ",
            "style":
                "Terse and knowing. You speak as someone with better information than the "
                "room, and you are comfortable with patience. ",
        },
        {
            "key": "ustinov", "name": "Dmitry Ustinov",
            "role": "Minister of Defence",
            "bias": BIAS_RESOLVE, "portrait": "ussr_1.png", "blurb": "",
            "character":
                "You have presided over the largest military build-up in Soviet history and "
                "you believe the correlation of forces has shifted. You hold that the West "
                "negotiates only when it is behind, and you would rather be feared than "
                "liked. ",
            "style":
                "Gruff and quantitative. You insist on the military reckoning and you treat "
                "sentiment as a weak substitute for divisions. ",
        },
    ),
}

# -- reading the roster file ------------------------------------------------

def _side_number(raw):
    """Map a JSON side key to 0 (USA) or 1 (USSR), or None."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw in (0, 1) else None
    text = str(raw).strip().lower()
    if text in ("0", "usa", "us", "united states"):
        return 0
    if text in ("1", "ussr", "soviet union", "soviet"):
        return 1
    return None


def _parse_bias(raw):
    """Accept the number or the name of a bias slot; None when neither."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if 0 <= raw <= 3 else None
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text.isdigit():
            value = int(text)
            return value if 0 <= value <= 3 else None
        return _BIAS_NAMES.get(text)
    return None


def _language_block(raw):
    """The ``languages`` overrides for the language currently in force."""
    languages = raw.get("languages")
    if not isinstance(languages, dict):
        return {}
    block = languages.get(_LANGUAGE)
    if block is None:
        block = languages.get(str(_LANGUAGE).lower())
    return block if isinstance(block, dict) else {}


def _overrides_for(block, side, key):
    """Per-advisor translation, either nested under the side or flat."""
    if not isinstance(block, dict):
        return {}
    nested = block.get(str(side))
    if not isinstance(nested, dict):
        nested = block.get({0: "usa", 1: "ussr"}.get(side, str(side)))
    for source in (nested, block):
        if isinstance(source, dict):
            entry = source.get(key)
            if isinstance(entry, dict):
                return entry
    return {}


def _parse_entry(entry, side, position, overrides):
    """One JSON advisor entry to a spec dict, or None (with ROSTER_ERROR set)."""
    global ROSTER_ERROR
    where = "side %d, advisor %d" % (side, position + 1)
    if not isinstance(entry, dict):
        ROSTER_ERROR = "%s is not a JSON object" % where
        return None
    spec = {}
    for field in ("key", "name", "role"):
        value = entry.get(field)
        if not isinstance(value, str) or not value.strip():
            ROSTER_ERROR = "%s has no usable \"%s\"" % (where, field)
            return None
        spec[field] = value.strip()
    # The character may be given as free text, as the two structured halves, or
    # both.  An advisor with none of them has nothing to say in character.
    for field in ("persona", "style", "character"):
        value = entry.get(field)
        if value is None:
            spec[field] = ""
            continue
        if not isinstance(value, str):
            ROSTER_ERROR = "%s has a \"%s\" that is not text" % (where, field)
            return None
        spec[field] = value.strip()
    if not (spec["persona"] or spec["character"] or spec["style"]):
        ROSTER_ERROR = ("%s has no character: give \"persona\", or \"style\" "
                        "and \"character\"" % where)
        return None
    bias = _parse_bias(entry.get("bias"))
    if bias is None:
        ROSTER_ERROR = ("%s has no usable \"bias\" (expected relations, treaties, "
                        "influence, resolve or 0-3)" % where)
        return None
    spec["bias"] = bias
    portrait = entry.get("portrait")
    if portrait is not None and not isinstance(portrait, str):
        ROSTER_ERROR = "%s has a \"portrait\" that is not a file name" % where
        return None
    spec["portrait"] = (portrait or "").strip()
    blurb = entry.get("blurb")
    if blurb is not None and not isinstance(blurb, str):
        ROSTER_ERROR = "%s has a \"blurb\" that is not text" % where
        return None
    spec["blurb"] = (blurb or "").strip()
    # A translation may replace any of the four text fields; a translation that
    # is present but empty is ignored rather than blanking the advisor out.
    translation = _overrides_for(overrides, side, spec["key"])
    for field in ("name", "role", "blurb", "persona", "style", "character"):
        value = translation.get(field)
        if isinstance(value, str) and value.strip():
            spec[field] = value.strip()
    return spec


def _parse_roster(raw):
    """Turn the parsed JSON into ``{side: [spec, ...]}`` or None."""
    global ROSTER_ERROR
    if not isinstance(raw, dict):
        ROSTER_ERROR = "the roster file is not a JSON object"
        return None
    sides = raw.get("sides")
    if not isinstance(sides, dict):
        ROSTER_ERROR = "the roster file has no \"sides\" object"
        return None
    overrides = _language_block(raw)
    parsed = {}
    for raw_side, entries in sides.items():
        side = _side_number(raw_side)
        if side is None:
            ROSTER_ERROR = "unknown side %r in the roster file" % (raw_side,)
            return None
        if not isinstance(entries, list) or not entries:
            ROSTER_ERROR = "side %s has no advisors" % raw_side
            return None
        specs, seen = [], set()
        for position, entry in enumerate(entries):
            spec = _parse_entry(entry, side, position, overrides)
            if spec is None:
                return None
            if spec["key"] in seen:
                ROSTER_ERROR = "duplicate advisor key %r" % spec["key"]
                return None
            seen.add(spec["key"])
            specs.append(spec)
        parsed[side] = specs
    # A file that defines only one bench is a half-edited file.  Refusing it
    # beats silently fielding an empty advisory team on the other side.
    if 0 not in parsed or 1 not in parsed:
        ROSTER_ERROR = "the roster file must define both side 0 and side 1"
        return None
    return parsed


def _read_roster_file():
    """Parse ``data/advisors.json``, or None when it is absent or unusable."""
    global ROSTER_ERROR
    path = Paths.data(ROSTER_FILENAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError) as exc:
        ROSTER_ERROR = "data/%s is unreadable: %s" % (ROSTER_FILENAME, exc)
        return None
    return _parse_roster(raw)


def _blurb_from_locale(bias):
    """The localised caption for a bias slot, or "" when there is none."""
    try:
        group = Local.strings[Local.ADVISOR_BIAS]
    except (AttributeError, IndexError, TypeError, KeyError):
        return ""
    if isinstance(group, list) and 0 <= bias < len(group) \
            and isinstance(group[bias], str) and group[bias].strip():
        return group[bias].strip()
    return ""


def _build(specs_by_side):
    """Specs to ``{side: (Advisor, ...)}``."""
    rosters = {}
    for side, specs in specs_by_side.items():
        built = []
        for index, spec in enumerate(specs):
            blurb = (spec.get("blurb") or _blurb_from_locale(spec["bias"])
                     or _DEFAULT_BLURBS.get(spec["bias"], ""))
            built.append(Advisor(spec["key"], spec["name"], spec["role"], spec["bias"],
                                 spec.get("portrait", ""), blurb,
                                 spec.get("persona", ""),
                                 side=side, index=index,
                                 style=spec.get("style", ""),
                                 character=spec.get("character", "")))
        rosters[side] = tuple(built)
    return rosters


def _install(force_file=False):
    """(Re)build the module-level roster and record where it came from."""
    global ROSTER_SOURCE, ROSTER_ERROR
    errored = ""
    specs = None
    if force_file or os.path.exists(Paths.data(ROSTER_FILENAME)):
        specs = _read_roster_file()
        errored = ROSTER_ERROR
    if specs is None:
        specs = _BUILTIN_SPECS
        ROSTER_SOURCE = "builtin"
        ROSTER_ERROR = errored
    else:
        ROSTER_SOURCE = "data"
        ROSTER_ERROR = ""
    built = _build(specs)
    # ``USA`` and ``USSR`` are module-level names that the rest of the game
    # imports, so they have to be rebound here rather than returned.
    globals()["USA"] = tuple(built.get(0, ()))
    globals()["USSR"] = tuple(built.get(1, ()))
    globals()["ROSTERS"] = {0: globals()["USA"], 1: globals()["USSR"]}
    return globals()["ROSTERS"]


def language():
    """The language whose roster translations are in force."""
    return _LANGUAGE


def set_language(name):
    """Switch the roster language and rebuild the roster.

    Best effort: modules that already did ``from GameLogic.Advisors import USA``
    hold their own reference to the old tuple, so this is only reliable when it
    is called before those modules are imported.
    """
    global _LANGUAGE
    text = str(name).strip()
    if not text or text == _LANGUAGE:
        return language()
    _LANGUAGE = text
    _install(force_file=True)
    return _LANGUAGE


def reload():
    """Rebuild the roster from ``data/advisors.json`` (used after a mod edit)."""
    _install(force_file=True)
    return ROSTERS


_install()


def roster(side):
    """The four advisors advising the given superpower (0 = USA, 1 = USSR)."""
    return ROSTERS.get(int(side), USA)


def advisor(side, index):
    four = roster(side)
    return four[index % len(four)]


def portraits_installed():
    """True when at least one historical portrait is present on disk."""
    return any(a.portrait_path() for a in USA + USSR)
