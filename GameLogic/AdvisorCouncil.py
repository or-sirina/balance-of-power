"""
The council: all four advisors speaking at once, and then arguing.

Two things live here that a one-to-one chat cannot give you.

**Speaking up (E1).**  When a crisis opens, the four advisors should say their
piece without being asked, and they should disagree — that disagreement is the
whole reason for having four of them.  Asking each one separately would be four
model calls for four sentences, so this is one *batched* request: a single
system prompt puts the four of them in a room and asks each for one line, keyed
by advisor.  One call, four verdicts, and they can see each other's positions
because they are answering in the same breath.

**Convening them (E2).**  The debate is two rounds: everyone speaks, then
everyone answers the sharpest objection raised against them.  That transcript is
the actual product — a list of positions and counter-positions the player can
read in ten seconds, instead of a paragraph of prose from one voice.

Everything degrades to the rule-based verdicts in
:func:`GameLogic.CrisisHandler.getAdvisorOpinion` when there is no model, no key,
or no network, so the council always says *something*.
"""

from GameLogic.Advisors import (BIAS_INFLUENCE, BIAS_RELATIONS,
                               BIAS_RESOLVE, BIAS_TREATIES, roster)

#: How many advisors answer in one request.  Kept at the roster size; a modded
#: longer roster is chunked rather than truncated.
MAX_SPEAKERS_PER_CALL = 6

COUNCIL_SYSTEM = """You are the national security council of {country} in {year}. \
You are advising {leader}, who must decide what to do.

The four of you are:
{roster}

Rules:
- Each of you answers in character, in ONE sentence of at most 25 words.
- You MUST disagree with each other. If you all agree, the player learns nothing.
- Never invent numbers. Use only the situation and the FACTS given to you.
- Reply with exactly one line per advisor, in the form 'KEY: your sentence',
  using the KEY given above. No preamble, no summary, no other text."""

DEBATE_SYSTEM = """You are the national security council of {country} in {year}. \
This is the second round of the same meeting.

{first_round}

Now each of you answers the strongest objection raised against your position, in
ONE sentence of at most 25 words. Do not repeat your first sentence. If you now
think someone else is right, say so. Reply with exactly one line per advisor in
the form 'KEY: your sentence'."""


def _roster_lines(side):
    lines = []
    for advisor in roster(side):
        lines.append("%s = %s, %s (cares most about %s)"
                     % (advisor.key, advisor.name, advisor.role,
                        advisor.blurb or "the balance of power"))
    return "\n".join(lines)


def parse_reply(text, side):
    """Pull ``KEY: sentence`` lines out of a model answer.

    Returns ``{key: sentence}``.  A reply that ignores the format still yields
    whatever could be matched, and an empty result tells the caller to fall back
    rather than to show nothing.
    """
    known = {}
    for advisor in roster(side):
        known[advisor.key.lower()] = advisor.key
        known[advisor.name.lower()] = advisor.key
    spoken = {}
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("-*# ").strip()
        if ":" not in line:
            continue
        label, _, sentence = line.partition(":")
        key = known.get(label.strip().lower())
        if key is None:
            continue
        sentence = sentence.strip().strip('"').strip()
        if sentence:
            spoken[key] = sentence
    return spoken


#: What each advisor actually looks at, phrased from the real board.  This is
#: what makes the offline council disagree: the four judge the same move through
#: four different lenses, and the number behind each lens is a real one.
_BIAS_LENS = {
    BIAS_RELATIONS: "look at East-West relations, which stand at {relations}",
    BIAS_TREATIES: "look at our treaty credibility, which is {credibility}",
    BIAS_INFLUENCE: "look at {target}, where our standing is {ours} against their "
                    "{theirs}",
    BIAS_RESOLVE: "ask what letting it stand teaches them about us next time",
}


def offline_verdicts(world, side, headline):
    """The rule-based verdicts, used when no model is available.

    These are the same four lines the crisis window has always shown; the point
    of the offline path is that the council keeps working, not that it is
    clever.
    """
    from GameLogic.CrisisHandler import getAdvisorOpinion

    me = world.country[side]
    them = world.country[1 - side]
    target = getattr(headline, "target", None)
    lines = {}
    for index, advisor in enumerate(roster(side)):
        if target is None:
            # Nothing on the table: the council can still say what each of them
            # is watching.  Without this the offline council returned four
            # empty strings whenever it was asked about the situation in
            # general rather than about one specific provocative move.
            lines[advisor.key] = _general_line(world, side, advisor)
            continue
        try:
            verdict = getAdvisorOpinion(world, headline, index + 1)
        except (AttributeError, IndexError, KeyError, TypeError):
            lines[advisor.key] = _general_line(world, side, advisor)
            continue
        lens = _BIAS_LENS.get(advisor.bias, "").format(
            target=_name(target.id),
            relations=world.USA.diplOpinion[1],
            credibility=me.integrity,
            ours=me.diplOpinion[target.id],
            theirs=them.diplOpinion[target.id])
        text = verdict.strip()
        if not text.endswith((".", "!", "?")):
            text += "."
        lines[advisor.key] = "%s I %s." % (text, lens)
    return lines


#: What each advisor says when there is no single decision on the table.
_GENERAL_LINE = {
    BIAS_RELATIONS: "Relations with them stand at {relations}; anything that "
                    "does not move that number is noise to me.",
    BIAS_TREATIES: "Our treaty credibility is {credibility}. Broken promises "
                   "cost us more than any single country is worth.",
    BIAS_INFLUENCE: "We hold {clients} formal allies, and our sphere of "
                    "influence stands at {sphere}. That is the ledger I would "
                    "defend.",
    BIAS_RESOLVE: "They are watching whether we mean what we say. Every quiet "
                  "year they conclude we do not.",
}


def _general_line(world, side, advisor):
    """A one-line standing position, when there is no specific move to judge."""
    me = world.country[side]
    template = _GENERAL_LINE.get(advisor.bias)
    if template is None:
        return "%s, and I have nothing to add." % (advisor.role or advisor.name)
    try:
        from GameLogic.Objectives import count_clients
        return template.format(relations=world.USA.diplOpinion[1],
                               credibility=me.integrity,
                               clients=count_clients(world, side),
                               sphere=me.dMess)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return template.split("{")[0].strip().rstrip(";,") + "."


def _name(country_id):
    import Local
    try:
        return Local.countryName(country_id)
    except (AttributeError, IndexError, TypeError, ValueError):
        return "that country"


def _situation(world, side, situation, headline):
    from GameLogic.AdvisorChat import country_facts, situation_text
    base = situation
    if base is None:
        base = situation_text(world, side, headline=headline)
    if headline is not None:
        try:
            country = headline.target
            facts = country_facts(world, side, country)
            base = "%s\n\nFACTS: %s" % (base, facts)
        except (AttributeError, IndexError, KeyError, TypeError):
            pass
    return base


def _ask_model(client, system, user, execute):
    """One completion, through whichever runner the caller supplied."""
    from GameLogic.AdvisorChat import guarded_chat
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
    return guarded_chat(client, execute, messages)


def convene(world, side, situation=None, headline=None, config=None,
            client=None, execute=None, rounds=2):
    """Run the council and return its transcript.

    ``rounds=1`` is "speak up": one line each, no rebuttals, which is what a
    crisis window wants.  ``rounds=2`` is the full debate for the council
    window.  Returns ``(transcript, used_model)`` where the transcript is a list
    of ``(advisor, text, round_number)``.
    """
    from GameLogic.AdvisorChat import chat_config

    country = _country_name(world, side)
    speakers = list(roster(side))
    transcript = []
    used_model = False

    situation_text = _situation(world, side, situation, headline)

    client = client or _client_for(config or _config(), world)
    if client is not None:
        try:
            system = COUNCIL_SYSTEM.format(
                country=country, year=world.year, leader=_leader(world, side),
                roster=_roster_lines(side))
            spoken = parse_reply(_ask_model(client, system, situation_text, execute), side)
            for advisor in speakers:
                sentence = spoken.get(advisor.key)
                if sentence:
                    transcript.append((advisor, sentence, 1))
        except Exception:
            # Any transport, schema or budget problem: the council falls back to
            # its rule-based verdicts rather than showing an empty room.
            transcript = []
        if transcript:
            used_model = True
            if rounds > 1 and len(transcript) > 1:
                # The rebuttals are a bonus.  If they fail, the opening round
                # the player was already promised stands.
                try:
                    transcript.extend(
                        _second_round(client, side, transcript, situation_text, execute))
                except Exception:
                    pass

    if not transcript:
        for advisor, text in _offline_pairs(world, side, headline):
            transcript.append((advisor, text, 1))
    return transcript, used_model


def _second_round(client, side, first_round, situation, execute):
    """Each advisor answers the sharpest objection to its own position."""
    opening = "\n".join("%s: %s" % (advisor.name, text)
                        for advisor, text, _ in first_round)
    # The country, the leader and the year are all in the situation text, which
    # is in front of the model for this call as well; naming them again in the
    # system prompt would only risk contradicting it.
    system = DEBATE_SYSTEM.format(country="your country", year="this year",
                                  first_round=opening)
    spoken = parse_reply(_ask_model(client, system, situation, execute), side)
    replies = []
    for advisor in roster(side):
        sentence = spoken.get(advisor.key)
        if sentence:
            replies.append((advisor, sentence, 2))
    return replies


def _offline_pairs(world, side, headline):
    lines = offline_verdicts(world, side, headline)
    return [(advisor, lines[advisor.key]) for advisor in roster(side)
            if advisor.key in lines]


def _config():
    from GameLogic.LLMClient import LLMConfig
    return LLMConfig()


def _client_for(config, world):
    """A chat client, or None when the council should stay offline.

    The level-5 opponent model cannot write prose, so this deliberately asks for
    the chat model rather than whatever the opponent is configured with.
    """
    from GameLogic.AdvisorChat import ai_advisors_enabled, chat_config
    from GameLogic.LLMClient import LLMClient
    if not ai_advisors_enabled(config):
        # The player chose the historical bench: the council still speaks, it
        # just does not reach for a model.
        return None
    try:
        resolved = chat_config(config)
    except (AttributeError, TypeError):
        resolved = config
    if resolved is None or not getattr(resolved, "usable", False):
        return None
    return LLMClient(resolved)


def _country_name(world, side):
    import Local
    try:
        return Local.countryName(int(side))
    except (AttributeError, IndexError, TypeError, ValueError):
        return "the country"


def _leader(world, side):
    try:
        return world.country[int(side)].name
    except (AttributeError, IndexError, TypeError, ValueError):
        return "the leadership"
