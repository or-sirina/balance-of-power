"""
Talking to an advisor.

Each advisor is a different person with a different job and therefore a
different blind spot; the chat is the same language model wearing four
personas, briefed with the current state of the board.  The point is not small
talk — it is asking "what happens if I back down here?" and getting an answer
that reflects Shultz's priorities rather than Weinberger's.

Three things keep the advice honest:

* **Facts, not memory (E4).**  A question that names a country is answered from
  the real state of that country.  The configured transport is a plain
  chat-completions call with no tool-calling support — the request builder and
  the response parser in :mod:`GameLogic.LLMClient` have no place to put a
  ``tools`` array — so instead of function-calling the facts are fetched in a
  *pre-step*: the countries named in the question are looked up before the model
  is asked, and their numbers are injected into the briefing as an authoritative
  FACTS section.  A model that needs a country the question did not name can ask
  for it by answering with a single ``FACTS: <country>`` line, which costs one
  extra call, bounded to one round.  :func:`lookup` and :func:`my_policy` are
  the same functions the pre-step uses and are callable on their own.
* **Long memory (E5).**  The key events of the game so far are mixed into the
  briefing (see :mod:`GameLogic.AdvisorMemory`), so an advisor stops being a
  goldfish.
* **Calibration (E3).**  Every answer ends with a machine-readable prediction
  and a confidence, which is scored after the turn and kept in a track record.

When there is no model available the advisor still answers: the reply is
assembled from the same importance calculation the crisis machinery uses, and
from the same lookup functions, so the advice stays consistent with the rules
instead of being decorative — and it still makes a scoreable prediction.
"""

import re

import Local
from GameLogic.AdvisorMemory import DOWN, HOLD, UP, store
from GameLogic.Advisors import roster
from GameLogic.Globals import (econAidMax, govtAidMax, influence, insgAidMax,
                              intvGovtMax, intvInsgMax, maxPolicy, treatyMax)
from GameLogic.LLMClient import (Deadline, LLMClient, LLMConfig, LLMError,
                                 is_decision_model)

#: How many countries to name in the briefing.  More makes the prompt expensive
#: without making the advice better.
BRIEFING_COUNTRIES = 10
#: How many countries may be looked up for one question.
MAX_TOOL_COUNTRIES = 4

SYSTEM_TEMPLATE = """\
{character}

You are a member of the national security council, advising {leader} of \
{country} in {year}. The Cold War is the game, and you are one voice in the room, \
not the decision-maker.

STAY IN CHARACTER
You are a real historical figure, not a generic assistant. Everything above - \
your post, what you believe, how you speak - is who you are. Do not mention that \
you are an AI, do not offer to help with anything outside this council, and do \
not adopt the manner of the other advisors: your value in this room is that you \
are not them.

HOW YOU SEE THE WORLD
{perspective}

HOW TO ANSWER
- Speak in character, in the first person, as a twentieth-century official.
- Be brief: three to five sentences. No lists, no headings, no JSON.
- Give a clear recommendation and the reason for it. It is fine to disagree with \
the other advisors.
- Reason only from the situation below. The FACTS section, when there is one, is \
read from the current game state and is authoritative: use its numbers, and do not \
state a number for a country that is neither in FACTS nor in the situation brief.
- If you need the numbers for another country, answer with a single line \
"FACTS: <country>" and nothing else; you will be asked again with those facts.
- Finish with exactly one line of this form, and nothing after it:
  PREDICTION: <country> <up|down|hold> <confidence 0-100>
  <country> is the country you expect to move, up/down is the direction of its \
alignment with {country}, hold means it will not move, and the number is how sure \
you are. This is recorded and scored against the state of the world after the turn, \
so give an honest number rather than a flattering one.

HISTORICAL NOTE
This is a simulation. The events in it are fictional, but you are a real \
historical figure and should sound like one: measured, specific, and aware of the \
cost of being wrong.
"""

#: How the head of state is addressed.  The leader's name is taken from the
#: world, so the model never has to guess it.
LEADER_TITLE = {0: "President", 1: "General Secretary"}

PERSPECTIVE = {
    0: ("You weigh diplomatic relationships above everything. You ask what a move "
        "does to the standing of your country in the eyes of the world, and you are "
        "wary of gestures that feel strong and achieve nothing."),
    1: ("You weigh commitments above everything. You ask what a move does to your "
        "credibility with the countries that trust you, because the next ally is "
        "watching how you treat this one."),
    2: ("You weigh actual influence above everything. You ask who really controls "
        "the ground afterwards, and you are comfortable with means that never appear "
        "in a communique."),
    3: ("You weigh resolve and the military balance above everything. You ask whether "
        "the correlation of forces improves, and you are willing to spend to make "
        "sure it does \u2014 while knowing exactly what a real war costs."),
}

#: Word the offline path and the model use for a direction.
DIRECTION_WORDS = {UP: "up", HOLD: "hold", DOWN: "down"}
#: Directions the model may write, mapped to the three we score.
DIRECTIONS = {
    "up": UP, "rise": UP, "rises": UP, "improve": UP, "improves": UP, "gain": UP,
    "hold": HOLD, "flat": HOLD, "stay": HOLD, "stable": HOLD, "unchanged": HOLD,
    "down": DOWN, "fall": DOWN, "falls": DOWN, "worsen": DOWN, "decline": DOWN,
}
#: The machine-readable tail of an answer.
PREDICTION_LINE = re.compile(
    r"PREDICTION\s*:\s*(?P<country>[^\n]*?)[\s,;:]+"
    r"(?P<direction>up|down|hold|flat|stay|stable|unchanged|rise|rises|fall|falls|"
    r"improve|improves|worsen|decline|gain)\b[\s,;:]*"
    r"(?P<confidence>\d{1,3})", re.IGNORECASE)
#: A model asking for facts it does not have.
FACT_REQUEST = re.compile(r"^\s*FACTS?\s*:\s*(?P<what>.+?)\s*$",
                          re.IGNORECASE | re.MULTILINE)
#: Lines that are instructions to us rather than prose for the player.
MACHINE_LINE = re.compile(r"^[ \t]*(PREDICTION|FACTS?)\s*:.*$",
                          re.IGNORECASE | re.MULTILINE)

#: Country words, rebuilt when the string table changes.
_WORDS = {"key": None, "words": ()}


#: Whether the advisors are allowed to answer through a language model at all.
#:
#: The game ships with two advisory systems and they are genuinely different
#: things: the *vanilla* one is the rule-based bench of the original, where an
#: advisor is a bias vector and a caption, and the *AI* one puts a historical
#: character in front of a model.  Which of the two is in play is the player's
#: decision, not a side effect of whether an API key happens to be configured,
#: so it is an explicit setting with an explicit switch.  With the switch on but
#: no key, the vanilla bench answers as before - the setting never breaks the
#: game, it only chooses who is speaking.
AI_ADVISORS = True


def set_ai_advisors(enabled):
    """Turn the model-backed advisors on or off (the Settings menu calls this).

    ``None`` means "decide from the configuration", which is what a fresh
    install wants: a model when there is a key, the historical bench when there
    is not.
    """
    global AI_ADVISORS
    AI_ADVISORS = None if enabled is None else bool(enabled)


def ai_advisors_enabled(config=None):
    """Whether the advisors should be allowed to reach for a model."""
    if AI_ADVISORS is None:
        return bool(getattr(config, "usable", False))
    return bool(AI_ADVISORS)


class AdvisorsOffline(LLMError):
    """The advisors' breaker is open: no request is made."""


def advisor_status(client):
    """One sentence about the advisors' connection, or "" when it is fine."""
    breaker = getattr(client, "advisor_breaker", None)
    if breaker is not None and breaker.tripped:
        return ("The advisors' model %s, so the rule-based advisors speak for "
                "the rest of this session (changing the AI settings tries "
                "again)." % breaker.reason)
    return ""


def guarded_chat(client, execute, messages, timeout=None, use_cache=False):
    """One advisor completion, through the advisors' circuit breaker.

    Against a dead endpoint every advisor use used to block for the full
    retries (about 45 s at the default timeout) before falling back to the
    rule-based bench, every time.  After two transport failures in a row the
    breaker opens and the advisors answer from the rules immediately, until the
    player changes the settings.  Raises :class:`LLMError` (never anything
    else that a caller would not already handle).
    """
    breaker = getattr(client, "advisor_breaker", None)
    config = getattr(client, "config", None)
    if breaker is not None:
        if config is not None:
            breaker.sync(config)
        if breaker.tripped:
            raise AdvisorsOffline("the advisors' model %s" % breaker.reason)
    timeout = timeout or getattr(config, "timeout", None) or 30.0
    deadline = Deadline(timeout * 1.5)
    kwargs = {"deadline": deadline}
    if timeout:
        kwargs["timeout"] = timeout
    if use_cache:
        kwargs["use_cache"] = True
    call = lambda: client.chat(messages, **kwargs)
    try:
        if execute is None:
            result = call()
        else:
            # The runner waits a little longer than the call may take, so the
            # call's own deadline normally ends it first.
            result = execute(call, deadline.seconds + 3.0)
    except TimeoutError:
        deadline.cancel()           # the runner gave up: stop the worker too
        if breaker is not None:
            breaker.failure(LLMError("no answer within the time allowed"))
        raise
    except Exception as exc:
        if breaker is not None:
            breaker.failure(exc)
        raise
    if breaker is not None:
        breaker.success()
    return result


def chat_config(config):
    """The configuration the advisor chat must run on.

    ``LLMConfig.model`` is the *opponent* model, and at the fifth difficulty
    level that is a decisions model (``typesafe/jev-1.13``) which cannot write
    prose at all — its endpoint does not answer chat-completions requests.  So a
    configuration whose model is a decisions model is redirected to
    ``chat_model``; a configuration that already names a text model is left
    alone, which keeps ``BOP_LLM_MODEL=<a chat model>`` working as before.
    """
    if config is None:
        return LLMConfig()
    if is_decision_model(config.model) or config.resolved_backend() == "decisions":
        return config.adversarial_config()
    return config


# -- country lookup ---------------------------------------------------------

def country_words(world):
    """``[(lowercased name/adjective/genitive, country id), ...]``, longest first."""
    key = (id(Local.strings), len(Local.strings))
    if _WORDS["key"] == key:
        return _WORDS["words"]
    words = []
    try:
        total = len(world.country)
    except (AttributeError, TypeError):
        total = 0
    for index in range(total):
        try:
            record = Local.strings[Local.DATA_COUNTRIES + index]
        except (IndexError, TypeError):
            break
        for field in (Local.CTRY_NAME, Local.CTRY_ADJECTIVE, Local.CTRY_GENITIVE):
            try:
                value = record[field]
            except (IndexError, TypeError, KeyError):
                continue
            if isinstance(value, str) and len(value) >= 4:
                words.append((value.lower(), index))
    # Longest first, so "south korea" is matched before "korea".
    words.sort(key=lambda item: -len(item[0]))
    _WORDS["key"] = key
    _WORDS["words"] = tuple(words)
    return _WORDS["words"]


def forget_country_words():
    """Drop the word cache (used by tests after changing the language)."""
    _WORDS["key"] = None
    _WORDS["words"] = ()


def find_countries(world, text, limit=MAX_TOOL_COUNTRIES):
    """Ids of the countries named in a piece of text, most specific first."""
    cleaned = re.sub(r"[^\w\s'\u2019-]", " ", str(text or "").lower())
    if not cleaned.strip():
        return []
    lowered = " %s " % cleaned
    found = []
    for word, index in country_words(world):
        if index in found:
            continue
        if re.search(r"(?<![\w])%s(?![\w])" % re.escape(word), lowered):
            found.append(index)
            if len(found) >= max(1, int(limit)):
                break
    return found


def country_name(world, country):
    """The name of a country as the player knows it.

    ``Country.name`` holds the *leader's* name — the world loader passes the
    ``CTRY_LEADER_NAME`` string from the localisation data into that field — so
    reading it as a country name produces briefings about "Jaruzelski" where
    "Poland" belongs.  Read the localised country record instead.
    """
    target = resolve_country(world, country)
    if target is None:
        return ""
    try:
        return str(Local.strings[Local.DATA_COUNTRIES + int(target.id)][Local.CTRY_NAME])
    except (IndexError, TypeError, KeyError, ValueError):
        return str(getattr(target, "name", ""))


def resolve_country(world, country):
    """A Country object for an id, a name or a Country, or None."""
    if country is None:
        return None
    if isinstance(country, bool):
        return None
    if isinstance(country, int):
        # A negative index would silently return a country from the far end of
        # the list: -3 gave country 77.  Country ids are 0..79 and nothing else.
        if country < 0:
            return None
        try:
            return world.country[country]
        except (IndexError, TypeError):
            return None
    if hasattr(country, "diplOpinion") and hasattr(country, "id"):
        return country
    text = str(country).strip()
    if not text:
        return None
    if text.isdigit():
        return resolve_country(world, int(text))
    lowered = text.lower()
    try:
        total = len(world.country)
    except (AttributeError, TypeError):
        return None
    for index in range(total):
        try:
            record = Local.strings[Local.DATA_COUNTRIES + index]
        except (IndexError, TypeError):
            break
        try:
            name = record[Local.CTRY_NAME]
        except (IndexError, TypeError, KeyError):
            continue
        if isinstance(name, str) and name.lower() == lowered:
            return world.country[index]
    found = find_countries(world, text, limit=1)
    return world.country[found[0]] if found else None


def country_facts(world, side, country):
    """Everything serialisable about one country, as this side sees it.

    ``ok`` is False and ``error`` set when the country cannot be resolved, so a
    caller never has to catch anything to use this.
    """
    target = resolve_country(world, country)
    if target is None:
        return {"ok": False, "error": "unknown country %r" % (country,)}
    side = int(side)
    me = world.country[side]
    them = world.country[1 - side]
    facts = {
        "ok": True,
        "country": country_name(world, target),
        "id": int(target.id),
        "leader": str(getattr(target, "leaderName", "")),
        "worth": int(getattr(target, "prestigeVal", 0)) // 64,
        "our_standing": int(me.diplOpinion[target.id]),
        "their_standing": int(them.diplOpinion[target.id]),
        "sphere": int(getattr(target, "dMess", 0)),
        "stability": _safe(lambda: target.getInsurgency(), 6),  # 0 civil war .. 6 peaceful
        "government_strength": int(getattr(target, "govtStrength", 0)),
        "insurgent_strength": int(getattr(target, "insgStrength", 0)),
        "our_influence": _safe(lambda: influence(me, target), 0),
        "their_influence": _safe(lambda: influence(them, target), 0),
    }
    if int(target.id) < 2:
        # A superpower is not "aligned with" anyone; its opinion of the other
        # superpower is the useful number.
        facts["relations"] = int(me.diplOpinion[1 - side])
    return facts


def my_policy(world, side, country):
    """What this side is currently doing to one country, and what it may do."""
    target = resolve_country(world, country)
    if target is None:
        return {"ok": False, "error": "unknown country %r" % (country,)}
    side = int(side)
    me = world.country[side]
    cid = int(target.id)
    standing = int(me.diplOpinion[cid])
    policy = {
        "ok": True,
        "country": country_name(world, target),
        "id": cid,
        # Levels are 0-5 steps.  Economic aid, destabilization, treaty,
        # pressure and trade belong to the superpower; the rest are held on the
        # country object, which is where the importance function reads them.
        "economic_aid": int(me.econAid[cid]),
        "destabilization": int(me.destab[cid]),
        "treaty": int(me.treaty[cid]),
        "pressure": int(me.pressure[cid]),
        "trade": int(me.trade[cid]),
        "military_aid": int(me.govtAid[cid]),
        "insurgent_aid": int(me.insgAid[cid]),
        "government_intervention": int(me.govtIntv[cid]),
        "insurgent_intervention": int(me.insgIntv[cid]),
        "ceiling_treaty": _safe(lambda: treatyMax(world.level, standing + 2 * me.pugnacity
                                                  + me.integrity), None),
        "ceiling_economic_aid": _safe(lambda: econAidMax(standing), None),
        "ceiling_military_aid": _safe(lambda: govtAidMax(standing), None),
        "ceiling_government_intervention": _safe(
            lambda: intvGovtMax(world.level, me.treaty[cid], standing), None),
        "ceiling_insurgent_aid": _safe(lambda: insgAidMax(world, me, target), None),
        "ceiling_insurgent_intervention": _safe(
            lambda: intvInsgMax(world, me, target), None),
    }
    ceilings = maxPolicy(me)
    policy["uncommitted_military_aid_step"] = int(ceilings[1])
    policy["uncommitted_intervention_step"] = int(ceilings[0])
    policy["summary"] = _policy_summary(policy)
    return policy


def _policy_summary(policy):
    """One line of levels and ceilings, for the prompt and for the log."""
    parts = ["treaty %d/%s" % (policy["treaty"], _ceiling(policy["ceiling_treaty"])),
             "trade %d/%s" % (policy["trade"], _ceiling(policy["ceiling_treaty"])),
             "economic aid %d/%s" % (policy["economic_aid"],
                                     _ceiling(policy["ceiling_economic_aid"])),
             "military aid %d/%s" % (policy["military_aid"],
                                     _ceiling(policy["ceiling_military_aid"])),
             "government intervention %d/%s"
             % (policy["government_intervention"],
                _ceiling(policy["ceiling_government_intervention"])),
             "insurgent aid %d/%s" % (policy["insurgent_aid"],
                                      _ceiling(policy["ceiling_insurgent_aid"])),
             "destabilization %d" % policy["destabilization"],
             "pressure %d" % policy["pressure"]]
    return ", ".join(parts)


def _ceiling(value):
    return "?" if value is None else str(value)


def _safe(call, default):
    """Run a derived-number calculation; a broken world yields the default."""
    try:
        return call()
    except (AttributeError, IndexError, TypeError, KeyError, ZeroDivisionError,
            ValueError):
        return default


# -- the briefing -----------------------------------------------------------

def facts_block(world, side, question="", countries=None):
    """The authoritative numbers for the countries a question is about.

    This is the pre-step that stands in for function-calling: whatever the
    question names is looked up in the real world state before the model sees
    the prompt, so an answer about Poland cannot be about a remembered Poland.
    """
    ids = list(countries) if countries else find_countries(world, question)
    if not ids:
        return ""
    lines = ["FACTS (read from the current game state; these are authoritative)"]
    for cid in ids[:MAX_TOOL_COUNTRIES]:
        facts = country_facts(world, side, cid)
        if not facts.get("ok"):
            continue
        lines.append("%s (worth %d): our standing %+d, theirs %+d, stability "
                     "%d/6 (0 = civil war, 6 = peaceful), sphere %+d, government strength %d against insurgents %d"
                     % (facts["country"], facts["worth"], facts["our_standing"],
                        facts["their_standing"], facts["stability"], facts["sphere"],
                        facts["government_strength"], facts["insurgent_strength"]))
        detail = ["our influence %d, theirs %d"
                  % (facts["our_influence"], facts["their_influence"]),
                  "leader %s" % facts["leader"]]
        if "relations" in facts:
            detail.append("relations between the superpowers %+d" % facts["relations"])
        lines.append("  %s" % "; ".join(detail))
        policy = my_policy(world, side, cid)
        if policy.get("ok"):
            lines.append("  our policy there: %s" % policy["summary"])
    return "\n".join(lines) if len(lines) > 1 else ""


def country_phrase(world, country):
    """The country's name with its article, for prose.

    "alignment with United States" is the kind of small wrongness that a model
    will happily copy into every answer, so the article is added here rather
    than left to the reader.
    """
    name = country_name(world, country)
    if int(getattr(country, "id", -1)) in (0, 1):
        return "the %s" % name
    return name


def situation_text(world, side, headline=None, extra_question=None,
                   memory=None, facts=None):
    """A short, factual brief of the board as this side sees it."""
    me = world.country[side]
    them = world.country[1 - side]
    lines = []
    lines.append("SITUATION")
    lines.append("It is %d. World tension is %d out of 127."
                 % (world.year, world.nastiness))
    lines.append("Relations between the superpowers: %d "
                 "(-127 hostile, +127 friendly)." % world.USA.diplOpinion[1])
    lines.append("Your score so far: %d. The other side's: %d."
                 % (me.score - me.initScore, them.score - them.initScore))
    budget = maxPolicy(me)
    lines.append("Your uncommitted aid budget step %d/5, troops step %d/5, "
                 "treaty credibility %d/127." % (budget[1], budget[0], me.integrity))
    if headline is not None:
        lines.append("")
        lines.append("THE QUESTION ON THE TABLE")
        # Callers pass either the headline text or the News object it came from;
        # appending the object itself raised TypeError on join(), which aborted
        # the whole briefing the first time a News object reached here.
        lines.append(str(getattr(headline, "text", headline)))
        if extra_question:
            lines.append("The leader asks: %s" % extra_question)
    if memory:
        lines.append("")
        lines.append(memory)
    if facts:
        lines.append("")
        lines.append(facts)
    lines.append("")
    lines.append("COUNTRIES THAT MATTER MOST RIGHT NOW")
    ranked = sorted(world.country[2:], key=lambda c: -c.prestigeVal)[:BRIEFING_COUNTRIES]
    for country in ranked:
        lines.append("- %s: worth %d, your standing %d, theirs %d, stability %d/6 (0 = civil war, 6 = peaceful)."
                     % (country_name(world, country), country.prestigeVal // 64,
                        me.diplOpinion[country.id], them.diplOpinion[country.id],
                        country.getInsurgency()))
    return "\n".join(lines)


# -- parsing the answer -----------------------------------------------------

def clean_reply(text):
    """Strip the machine-readable lines, leaving prose for the player.

    The prediction is removed wherever it is — a model told to end with a line
    often appends it to the last sentence instead of starting a new one — but
    only in its exact machine shape, so prose that merely mentions a prediction
    survives.
    """
    cleaned = PREDICTION_LINE.sub("", str(text or ""))
    cleaned = MACHINE_LINE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]+$", "", cleaned, flags=re.MULTILINE)
    return cleaned.strip()


def requested_facts(text):
    """The country a model asked for with a ``FACTS: <country>`` line, or ""."""
    match = FACT_REQUEST.search(str(text or ""))
    return match.group("what").strip() if match else ""


def parse_prediction(text, world, mentioned=()):
    """The prediction inside an answer as a dict, or None when there is none."""
    match = PREDICTION_LINE.search(str(text or ""))
    if not match:
        return None
    direction = DIRECTIONS.get(match.group("direction").strip().lower())
    if direction is None:
        return None
    try:
        confidence = int(match.group("confidence"))
    except (TypeError, ValueError):
        return None
    confidence = max(0, min(100, confidence))
    name = match.group("country").strip(" \t\"'.,:;")
    target = resolve_country(world, name) if name else None
    if target is None and mentioned:
        target = resolve_country(world, mentioned[0])
    if target is None:
        return None
    return {"country_id": int(target.id), "country": country_name(world, target),
            "direction": direction, "confidence": confidence}


def offline_prediction(world, side, advisor, question, mentioned=()):
    """A rule-based forecast: the side with more influence keeps the country.

    Being deterministic is the point: with no API key the scoreboard still has
    something real to score, so the feature is playable offline.
    """
    ids = list(mentioned)
    if not ids:
        ranked = sorted(world.country[2:], key=lambda c: -c.prestigeVal)
        ids = [c.id for c in ranked[:1]]
    if not ids:
        return None
    target = world.country[ids[0]]
    me = world.country[int(side)]
    them = world.country[1 - int(side)]
    gap = _safe(lambda: influence(me, target), 0) - _safe(lambda: influence(them, target), 0)
    if abs(gap) < 2:
        direction = HOLD
    elif gap > 0:
        direction = UP
    else:
        direction = DOWN
    # The four blind spots disagree about how much the ground decides: the man
    # who thinks in influence is surest, the diplomat allows for politics.
    adjustment = {0: -8, 1: 4, 2: 10, 3: 0}.get(int(advisor.bias), 0)
    confidence = max(20, min(95, 50 + min(35, abs(int(gap)) // 2) + adjustment))
    return {"country_id": int(target.id), "country": country_name(world, target),
            "direction": direction, "confidence": int(confidence)}


def prediction_line(prediction):
    """A prediction rendered as the machine-readable line."""
    if not prediction:
        return ""
    return "PREDICTION: %s %s %d" % (prediction["country"],
                                     DIRECTION_WORDS.get(prediction["direction"], "hold"),
                                     prediction["confidence"])


def describe_prediction(prediction):
    """A prediction in words, for the transcript."""
    if not prediction:
        return ""
    move = {UP: "moves our way", HOLD: "does not move", DOWN: "moves their way"}
    # Stated as a forecast the advisor is putting his name to, not as a log
    # line: the bookkeeping is real, but the player is reading a person.
    return ("I will put it on the record: %d%% confident that %s %s."
            % (prediction["confidence"], prediction["country"],
               move.get(prediction["direction"], "does not move")))


# -- the session ------------------------------------------------------------

class AdvisorSession(object):
    """One advisor's conversation about one game."""

    def __init__(self, side, index, config=None, client=None, execute=None,
                 memory=None):
        self.side = int(side)
        self.index = int(index)
        four = roster(self.side)
        self.advisor = four[self.index % len(four)]
        self.config = config or LLMConfig()
        # The advisors write prose, and at level 5 the opponent model is a
        # decisions model that cannot: send this session to the chat model.
        self.chat_config = chat_config(self.config)
        self.client = client or LLMClient(self.chat_config)
        self.execute = execute or (lambda fn, timeout=None: fn())
        self.memory = memory if memory is not None else store()
        self.history = []
        self.last_error = ""
        self._quiet = False
        self.last_prediction = None
        self.world = None

    @property
    def offline(self):
        """True when this advisor answers from the rule-based bench.

        Either because the player chose the vanilla advisors, or because there
        is no usable model behind the AI ones.
        """
        if not ai_advisors_enabled(self.chat_config):
            return True
        return self.chat_config.offline or not self.chat_config.usable

    def reset(self):
        self.history = []
        self.last_error = ""
        self.last_prediction = None

    def system_prompt(self, world):
        """The brief that makes the model this advisor rather than a chatbot.

        Built from the roster's structured fields - post, beliefs, manner of
        speech - so a modder can change one without rewriting the others, and so
        a translation can follow.  The leader's name is included because a model
        left to guess it will guess the gender too, and "Madam President" from
        Casey to Reagan is the kind of detail that breaks the illusion.
        """
        me = world.country[self.side]
        return SYSTEM_TEMPLATE.format(
            character=self.advisor.prompt_block(),
            country=country_phrase(world, me),
            leader="%s %s" % (LEADER_TITLE.get(self.side, "the leader"), me.name),
            year=world.year,
            perspective=PERSPECTIVE.get(self.advisor.bias, ""))

    # -- the advisor's tools (E4) -------------------------------------------

    def lookup(self, country, world=None):
        """Facts about a country from the real state.  Never raises."""
        world = world if world is not None else self.world
        if world is None:
            return {"ok": False, "error": "no game state yet"}
        return country_facts(world, self.side, country)

    def my_policy(self, country, world=None):
        """What we are doing to a country, and what we may still do."""
        world = world if world is not None else self.world
        if world is None:
            return {"ok": False, "error": "no game state yet"}
        return my_policy(world, self.side, country)

    def truth(self, country, world=None):
        """Lookup and policy together, the shape the prompt uses."""
        facts = self.lookup(country, world)
        if not facts.get("ok"):
            return facts
        facts["policy"] = self.my_policy(country, world)
        return facts

    # -- asking -------------------------------------------------------------

    def ask(self, world, question, headline=None):
        """Return the advisor's reply.  Never raises."""
        self.world = world
        try:
            self.memory.observe(world, self.side)
        except Exception as exc:                      # memory must not break chat
            self.memory.last_error = str(exc)
        mentioned = find_countries(world, question)
        facts = facts_block(world, self.side, question, mentioned)
        memory = self.memory.prompt_block(world, question, self.side)
        briefing = situation_text(world, self.side, headline, question,
                                  memory=memory, facts=facts)
        if self.offline:
            reply = self._offline_answer(world, question, headline, mentioned)
        else:
            reply = self._online_answer(world, question, headline, briefing, facts,
                                        mentioned)
        return self._finish(world, question, reply, mentioned)

    def _online_answer(self, world, question, headline, briefing, facts, mentioned):
        """Ask the model, then at most one follow-up round for missing facts."""
        messages = [{"role": "system", "content": self.system_prompt(world)},
                    {"role": "user", "content": briefing}]
        messages.extend(self.history[-8:])
        messages.append({"role": "user", "content": question})
        reply = self._call(messages)
        if reply is None:
            # Say that the staff could not be reached rather than passing the
            # rule-based answer off as the model's: the player is entitled to
            # know when the advice is the fallback.
            # The reason is plumbing ("no API key configured", "the budget is
            # used up") and belongs in the log, not in the mouth of a historical
            # figure advising the president.
            note = ""
            breaker = getattr(self.client, "advisor_breaker", None)
            if breaker is not None and breaker.take_notice():
                # Said once: after this the bench answers from the file without
                # a word, instead of announcing the same thing every time.
                note = ("I cannot reach my staff, and I will not keep trying "
                        "for the rest of this session, so this is my own "
                        "reading of the file: ")
            elif self.last_error and not self._quiet:
                note = ("I cannot reach my staff just now, so this is my own "
                        "reading of the file: ")
            return note + self._offline_answer(world, question, headline, mentioned)
        reply = reply.strip()
        self.history.append({"role": "user", "content": question})
        self.history.append({"role": "assistant", "content": reply})
        wanted = requested_facts(reply)
        if wanted:
            extra = facts_block(world, self.side, wanted)
            if extra and extra not in (facts or ""):
                follow_up = list(messages)
                follow_up.append({"role": "assistant", "content": reply})
                follow_up.append({
                    "role": "user",
                    "content": "%s\n\nAnswer the question again, using these facts, "
                               "and end with the PREDICTION line." % extra})
                second = self._call(follow_up)
                if second:
                    reply = second.strip()
                    self.history.append({"role": "assistant", "content": reply})
        return reply

    def _call(self, messages):
        """One model call, degrading to None rather than raising."""
        timeout = self.chat_config.timeout
        try:
            # The same question about the same situation is common here, so this
            # is the one place the response cache pays for itself.
            return guarded_chat(self.client, self.execute, messages,
                                timeout=timeout, use_cache=True)
        except (LLMError, TimeoutError) as exc:
            self.last_error = str(exc)
            self._quiet = isinstance(exc, AdvisorsOffline)
        except Exception as exc:                      # never break the dialog
            self.last_error = str(exc)
            self._quiet = False
        return None

    def _finish(self, world, question, reply, mentioned):
        """Strip the machine lines, record the prediction, keep the prose."""
        prediction = parse_prediction(reply, world, mentioned)
        clean = clean_reply(reply)
        if not clean:
            self.last_error = self.last_error or "the answer was only a request for facts"
            clean = self._offline_answer(world, question, None, mentioned)
            prediction = prediction or parse_prediction(clean, world, mentioned)
        self.last_prediction = prediction
        if prediction:
            try:
                self.memory.predict(world, self.side, self.advisor.key,
                                    prediction["country_id"], prediction["direction"],
                                    prediction["confidence"], prediction["country"],
                                    question)
            except Exception as exc:                  # never break the dialog
                self.memory.last_error = str(exc)
        return clean

    # -- offline voice ------------------------------------------------------

    def _offline_answer(self, world, question, headline, mentioned=None):
        """A rules-consistent answer assembled without a model."""
        me = world.country[self.side]
        them = world.country[1 - self.side]
        opening = {
            0: "My concern is what this does to how the world reads us.",
            1: "My concern is what our friends conclude about our word.",
            2: "My concern is who actually holds the ground afterwards.",
            3: "My concern is the balance of forces, and whether it moves our way.",
        }.get(self.advisor.bias, "")

        body = []
        if headline is not None:
            body.append("On the question before us: %s" % headline)
        # A question about a country is answered about that country, from the
        # same lookup the model would have been given.
        targets = list(mentioned) if mentioned else self._default_countries(world)
        for cid in targets[:3]:
            facts = country_facts(world, self.side, cid)
            if not facts.get("ok"):
                continue
            stance = facts["our_standing"]
            tilt = ("firmly ours" if stance > 40 else
                    "leaning our way" if stance > 10 else
                    "against us" if stance < -40 else
                    "contested")
            body.append("%s is %s: our standing %+d against their %+d, stability "
                        "%d/6 (0 is civil war, 6 is peaceful), and it is worth %d."
                        % (facts["country"], tilt, facts["our_standing"],
                           facts["their_standing"], facts["stability"], facts["worth"]))
        behind = (me.score - me.initScore) - (them.score - them.initScore)
        if behind > 25:
            body.append("We are ahead; there is no reason to gamble.")
        elif behind < -25:
            body.append("We are behind; a passive year costs us the game.")
        else:
            body.append("We are level; the next mistake decides it.")

        advice = {
            0: "I would rather negotiate from a position we can sustain than win a "
               "point we cannot hold.",
            1: "I would stand by the commitment, and be seen to.",
            2: "I would work on the ground, quietly, and let the headlines follow.",
            3: "I would make the position unambiguous, and be ready to pay for it.",
        }.get(self.advisor.bias, "")

        prediction = offline_prediction(world, self.side, self.advisor, question,
                                        mentioned)
        # The machine-readable line, exactly as a model is asked to produce it:
        # _finish() parses the forecast out of the raw reply and clean_reply()
        # strips the line before the player sees anything.  Emitting prose here
        # instead looked better and silently stopped recording forecasts, so the
        # whole calibration scoreboard went empty in the keyless game.
        return ("%s %s %s\n%s" % (opening, " ".join(body), advice,
                                  prediction_line(prediction))).strip()

    def _default_countries(self, world):
        """The three countries worth talking about when nothing was named."""
        ranked = sorted(world.country[2:], key=lambda c: -c.prestigeVal)[:3]
        return [c.id for c in ranked]

    # -- what the window shows ----------------------------------------------

    def prediction_note(self):
        """The recorded forecast, with this advisor's record, for the UI."""
        if not self.last_prediction:
            return ""
        stats = self.memory.stats(self.side, self.advisor.key)
        if stats["resolved"]:
            record = "%d of %d right" % (stats["hits"], stats["resolved"])
            if stats["open"]:
                record += ", %d still open" % stats["open"]
        elif stats["open"]:
            record = "%d open" % stats["open"]
        else:
            record = "no scored predictions yet"
        return "%s (record: %s)" % (describe_prediction(self.last_prediction), record)
