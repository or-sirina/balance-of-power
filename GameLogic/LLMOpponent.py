"""
A superpower opponent driven by a language model.

The fifth difficulty level hands the computer superpower to an LLM reached over
an OpenAI-compatible API (OpenRouter by default).  Two rules shape the whole
module:

**It can never break the game.**  Every failure — no key, no network, a timeout,
a proxy that eats the request, a model that answers with prose, a plan that
proposes an illegal action — falls back to the ordinary heuristic AI
(:func:`GameLogic.MovePlanner.compuAI`), which is what the other four levels use.
The player loses a little cleverness, never a turn.

**It only proposes; the game disposes.**  Everything the model asks for is
re-validated against exactly the same ceilings the heuristic AI obeys
(``maxPolicy``, the per-verb diplomatic and budgetary caps, the staging-area
rule for insurgency aid).  A model cannot grant itself extra budget by asking
nicely.

The level is also playable with no network at all: set the model to
``mock/heuristic`` and the same prompt/parse/validate/apply pipeline runs
against a deterministic local planner.  That is what the tests use.
"""

import json

import Local

from GameLogic.Globals import (econAidMax, econConv, getMaxLevel, govtAidMax,
                               insgAidMax, insgStrengthMax, intvGovtMax,
                               intvInsgMax, maxPolicy, tradeMax, treatyMax)
from GameLogic.JevClient import JevClient, JevError
from GameLogic.LLMClient import (Deadline, LLMClient, LLMConfig, LLMError,
                                 LLMNotConfigured, MOCK_MODEL, POLICY_SCHEMA,
                                 SharedBudget, _redact, extract_json,
                                 failure_kind, failure_phrase)
from constants import (AVL_ACTIONS, DESTAB, ECONAID, GOVTAID, GOVTINTV,
                       INGSINTV, INSGAID, PRESSURE, TRADE, TREATY)

#: Human-readable verb names, used both in the prompt and in the answer.
ACTION_NAMES = {
    DESTAB: "destabilise",
    ECONAID: "economic_aid",
    GOVTAID: "military_aid",
    INSGAID: "aid_insurgents",
    GOVTINTV: "intervene_govt",
    INGSINTV: "intervene_rebels",
    PRESSURE: "pressure",
    TREATY: "treaty",
    TRADE: "trade",
}
ACTION_IDS = {name: action for action, name in ACTION_NAMES.items()}

#: The same verbs as the player sees them in the opponent log and the dialogs.
#: ``ACTION_NAMES`` above stays machine-readable because the model is asked for
#: one of those exact strings.
ACTION_DISPLAY_NAMES = {
    DESTAB: "Destabilization",
    ECONAID: "Economic aid",
    GOVTAID: "Military aid",
    INSGAID: "Aid to the insurgents",
    GOVTINTV: "Intervene for the government",
    INGSINTV: "Intervene for the rebels",
    PRESSURE: "Diplomatic pressure",
    TREATY: "Treaty",
    TRADE: "Trade",
}

#: The spellings a model may use for one of the verbs above.
ACTION_NAME_ALIASES = {"destabilize": DESTAB}

#: Actions that are read as a provocation by the other superpower.
PROVOCATIVE = (DESTAB, INSGAID, INGSINTV, PRESSURE)

#: How many country rows to send.  All 78 fit comfortably; the cap is a guard
#: against a modded world with hundreds of countries blowing the context.
MAX_COUNTRY_ROWS = 90
#: How many actions to accept from one plan.
MAX_ACTIONS_PER_TURN = 6
#: Consecutive failed model calls after which the opponent stops asking for the
#: rest of the game.  Every failed turn otherwise costs the player the full
#: timeout (and its retries) before the built-in AI is allowed to play.
MAX_CONSECUTIVE_FAILURES = 2
#: How many turns in a row a model may answer "do nothing" before that is
#: treated as a failure.  One pass is a legitimate move; a model that passes
#: every year is not playing, and the built-in AI should.
MAX_EMPTY_PLANS = 2
#: One turn's wall-clock allowance, as a multiple of the configured timeout,
#: shared by every request the turn makes.
TURN_DEADLINE_FACTOR = 1.5

#: What to do about each kind of failure, one clause for the log.
FAILURE_HINTS = {
    "key": "Check the key under AI \u2192 AI settings\u2026.",
    "filter": "Ask IT to allow the model's web address.",
    "certificate": "Set SSL_CERT_FILE to your organisation's root CA file.",
    "model": "Pick another model under AI \u2192 AI settings\u2026.",
    "busy": "Try again later.",
    "unreachable": "Check the network and the endpoint under AI \u2192 AI settings\u2026.",
    "unusable": "The model's answer could not be used.",
}

SYSTEM_PROMPT = """\
You are the strategic decision-maker of {country} during the Cold War, in a \
simulation based on Chris Crawford's "Balance of Power".

YOUR OBJECTIVE
Maximise your prestige score, which is
    score = sum over the 78 minor countries of ( their diplomatic opinion of you x that country's prestige value ) / 1024
The score that decides the game is the INCREASE since 1982, so you are racing \
{opponent} for the same countries.

HOW YOU SCORE
Diplomatic opinion rises when you help a government (economic aid, military aid, \
intervening on its side, a treaty, trade) and falls when you attack it \
(destabilization, aid to its insurgents, intervening for its rebels, pressure). \
Countries are worth more when they are both militarily funded and populous; a \
rich micro-state and a huge poor one are both worth little.

CONSTRAINTS
- You may only act on the minor countries listed.  You cannot act on yourself or \
on {opponent}.
- Every verb has six steps, 0 (none) to 5 (maximum).  Sending 0 repeals the policy.
- Aid and intervention are annual commitments that persist until you change them; \
your aid budget and your troops are finite and shared across all countries.
- Sending aid to insurgents or intervening for rebels requires troops supporting \
a government in a CONTIGUOUS country.  Without that staging area you may only \
send the lowest step.
- Provocative actions can trigger a crisis with {opponent}.  A crisis that \
escalates to DefCon 1 is a nuclear war: a total loss for you, however well you \
were doing.  Do not gamble the game on a crisis you do not need.

STYLE
Play to win.  Concentrate on countries that are valuable, winnable, and where \
{opponent} is weak.  Defend your clients when they are about to fall to the other \
side.  Do not spread a little aid over everything.

ANSWER FORMAT
Reply with JSON only, no prose around it:
{{"reasoning": "<one or two sentences>",
  "actions": [{{"action": "<verb>", "target": <country id>, "level": <0-5>}}]}}
Use at most {max_actions} actions.  An empty list is a legal answer.\
"""


class _Unplayable(LLMError):
    """A plan that cannot be enacted this turn; ``counts`` says if it is a fault."""

    def __init__(self, message, counts=True):
        super().__init__(message)
        self.counts = counts


class PolicyPlan(object):
    """What the opponent decided to do this turn."""

    def __init__(self, actions=None, reasoning="", source="unknown", detail="",
                 evidence=None):
        self.actions = actions or []
        self.reasoning = reasoning
        self.source = source
        self.detail = detail
        #: For a decision model: {question: JevAnswer}.  Jev returns no prose,
        #: so the log shows probabilities and confidence instead.
        self.evidence = evidence or {}
        #: How many actions the model asked for before validation, and how many
        #: of those were thrown away as invalid.  A model that asked for
        #: something and got nothing through has not played its turn.
        self.proposed = len(self.actions)
        self.rejected = 0

    def __len__(self):
        return len(self.actions)

    def __repr__(self):
        return "<PolicyPlan %s %d actions: %s>" % (
            self.source, len(self.actions), self.reasoning[:60])


# ---------------------------------------------------------------------------
# Legality: the model proposes, these decide
# ---------------------------------------------------------------------------

def action_ceiling(world, actor, target, action, max_intv, max_aid, max_econ):
    """Highest legal step for ``action`` towards ``target`` right now.

    Mirrors the ceilings ``compuAI`` applies, so the language model can never
    exceed what the built-in AI is allowed.  ``None`` means the verb is not
    available at all.
    """
    if action not in AVL_ACTIONS[world.level - 1]:
        return None
    if target.id < 2 or target is actor:
        return None
    opinion = actor.diplOpinion[target.id]
    if action == ECONAID:
        return min(econAidMax(opinion), max_econ)
    if action == GOVTAID:
        return min(govtAidMax(opinion), max_aid)
    if action == INSGAID:
        cap = min(insgAidMax(world, actor, target), max_aid)
        ratio = insgStrengthMax(target.strengthRatio)
        return min(cap, ratio)
    if action == GOVTINTV:
        return min(intvGovtMax(world.level, actor.treaty[target.id], opinion), max_intv)
    if action == INGSINTV:
        return min(intvInsgMax(world, actor, target), max_intv)
    if action == PRESSURE:
        return 5 if world.level >= 3 else 0
    if action == DESTAB:
        return 5 if world.level >= 2 else 0
    if action == TREATY:
        ceiling = treatyMax(world.level, actor.integrity + opinion - actor.pugnacity)
        # A treaty is never downgraded voluntarily.
        return max(ceiling, actor.treaty[target.id])
    if action == TRADE:
        ceiling = tradeMax(world.level, actor.integrity + opinion - actor.pugnacity)
        return max(ceiling, actor.trade[target.id])
    return None


def current_level(actor, target, action):
    if action == DESTAB:
        return actor.destab[target.id]
    if action == ECONAID:
        return actor.econAid[target.id]
    if action == GOVTAID:
        return actor.govtAid[target.id]
    if action == INSGAID:
        return actor.insgAid[target.id]
    if action == GOVTINTV:
        return actor.govtIntv[target.id]
    if action == INGSINTV:
        return actor.insgIntv[target.id]
    if action == PRESSURE:
        return actor.pressure[target.id]
    if action == TREATY:
        return actor.treaty[target.id]
    if action == TRADE:
        return actor.trade[target.id]
    return 0


def affordable_step(world, actor, target, action):
    """The highest step the actor can actually pay for, or None if illegal.

    The decision model used to be asked for a step with no idea what it could
    afford, so it routinely asked for 4 and 5 on a budget that allowed 1 and 2.
    ``apply`` then clamped or dropped the action, and the player's log showed a
    policy the opponent never carried out.  Handing the ceiling to the model
    removes both the waste and the lie.
    """
    budget = maxPolicy(actor)
    try:
        ceiling = action_ceiling(world, actor, target, action,
                                 budget[0], budget[1], economic_ceiling(world, actor))
    except (AttributeError, IndexError, KeyError, TypeError):
        return None
    if ceiling is None:
        return None
    return max(0, min(5, int(ceiling)))


def economic_ceiling(world, actor):
    """The same economic-aid ceiling ``compuAI`` derives from GNP and existing aid."""
    spent = sum(econConv(i) for i in actor.econAid)
    budget = (actor.GNP // 44) - 2 * spent
    ceiling = 5
    for i in range(4, -1, -1):
        if econConv(i + 1) > budget:
            ceiling = i
    return ceiling


# ---------------------------------------------------------------------------
# The briefing
# ---------------------------------------------------------------------------

def build_briefing(world, actor, opponent):
    """A compact, token-efficient description of the position."""
    budget = maxPolicy(actor)
    lines = []
    lines.append("YEAR %d. WORLD TENSION (nastiness) %d/127." % (world.year, world.nastiness))
    lines.append("US-SOVIET RELATIONS: %d (-127 hostile .. +127 friendly)."
                 % world.USA.diplOpinion[1])
    lines.append("")
    lines.append("YOU: %s, led by %s" % (Local.countryName(actor.id), actor.name))
    lines.append("  GNP %d, military spending %d, military manpower %d thousand."
                 % (actor.GNP, actor.gnpSpnd[2], actor.milMen))
    lines.append("  Military power %d, prestige value %d."
                 % (actor.milPower, actor.prestigeVal))
    lines.append("  Uncommitted aid budget step %d, uncommitted troops step %d."
                 % (budget[1], budget[0]))
    lines.append("  Treaty credibility (integrity) %d, pugnacity %d, adventurousness %d."
                 % (actor.integrity, actor.pugnacity, actor.adventurousness))
    lines.append("  Current score %d."
                 % (actor.score - actor.initScore))
    lines.append("OPPONENT: %s, led by %s, current score %d."
                 % (Local.countryName(opponent.id), opponent.name,
                    opponent.score - opponent.initScore))
    lines.append("")

    standing = []
    for action, name in sorted(ACTION_NAMES.items()):
        held = [(c.id, c.name) for c in world.country[2:]
                if current_level(actor, c, action) > 0]
        if held:
            standing.append("  %s: %s" % (name, ", ".join(
                "%s=%d" % (n, current_level(actor, world.country[i], action))
                for i, n in held[:14])))
    lines.append("YOUR STANDING POLICIES (level per country):")
    lines.extend(standing or ["  (none)"])
    lines.append("")

    lines.append("MINOR COUNTRIES")
    lines.append("columns: id name | your_opinion their_opinion | prestige | "
                 "stability(0=civil war..6=peaceful) | govt_popularity(0-20) | your_troops their_troops")
    rows = world.country[2:2 + MAX_COUNTRY_ROWS]
    for country in rows:
        lines.append("%d %s | %d %d | %d | %d | %d | %d %d" % (
            country.id,
            country.name.replace(" ", "_")[:18],
            actor.diplOpinion[country.id],
            opponent.diplOpinion[country.id],
            country.prestigeVal // 32,
            country.getInsurgency(),
            country.govtPopul,
            actor.govtIntv[country.id],
            opponent.govtIntv[country.id]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The decision-model briefing
# ---------------------------------------------------------------------------

#: How many countries to offer as candidate targets.  Jev bills per input token,
#: and a shortlist is also a better question than "pick one of 78".
FOCUS_SHORTLIST = 12
#: Relative floor for sampling a decision model's choice answer.  Options below
#: this share of the leader's probability are treated as noise rather than as a
#: live alternative; see ``JevAnswer.sample``.
DECISION_FLOOR = 0.25

#: Step labels for the score question.
LEVEL_CRITERIA = ("none", "minimal", "modest", "substantial", "heavy", "maximum")

#: One line per verb, written for the model rather than for the player.
VERB_BRIEF = {
    DESTAB: "covert action to bring down the government",
    ECONAID: "money into the economy; buys goodwill in proportion to need",
    GOVTAID: "weapons for the government; strengthens it against its rebels",
    INSGAID: "weapons for the insurgents; provocative, and cheap for its effect",
    GOVTINTV: "our own troops fight for the government; risky",
    INGSINTV: "our own troops fight for the rebels; the most provocative option",
    PRESSURE: "intimidation; pushes the country towards us and raises its army spending",
    TREATY: "a formal commitment to defend it; raises our standing, binds us",
    TRADE: "a trade agreement; a diplomatic statement and nothing more",
}


def _candidate_countries(world, actor, opponent, limit=FOCUS_SHORTLIST):
    """Countries worth offering the model as a focus.

    Ranked by what winning them is worth, weighted by how far they are from
    being ours already, so the shortlist is not simply the richest twelve.
    """
    ranked = []
    for country in world.country[2:]:
        mine = actor.diplOpinion[country.id]
        theirs = opponent.diplOpinion[country.id]
        swing = (theirs - mine) / 2.0
        worth = country.prestigeVal / 64.0
        urgency = (6 - country.getInsurgency()) * 2.0  # 6 is peaceful, 0 civil war
        ranked.append((worth + swing + urgency, country))
    ranked.sort(key=lambda item: -item[0])
    return [country for _, country in ranked[:limit]]


def build_decision_state(world, actor, opponent, focus=None):
    """The ``state`` object handed to the decision model.

    A record rather than a wall of text: Jev reads nested fields, and keeping the
    structure means the model can be asked precise questions about it.
    """
    budget = maxPolicy(actor)
    standing = {}
    for action, name in sorted(ACTION_NAMES.items()):
        held = ["%s=%d" % (c.name, current_level(actor, c, action))
                for c in world.country[2:] if current_level(actor, c, action) > 0]
        if held:
            standing[name] = held[:12]

    state = {
        "role": "decision-maker for %s" % actor.name,
        "opponent": opponent.name,
        "year": world.year,
        "world_tension_0_127": world.nastiness,
        "superpower_relations_minus127_to_127": world.USA.diplOpinion[1],
        "your_score": actor.score - actor.initScore,
        "opponent_score": opponent.score - opponent.initScore,
        "your_uncommitted_aid_step_0_5": budget[1],
        "your_uncommitted_troop_step_0_5": budget[0],
        "your_treaty_credibility_0_127": actor.integrity,
        "how_you_are_seen_0_127": actor.pugnacity,
        "your_standing_policies": standing,
        "rules": {
            "goal": "raise the total of every minor country's opinion of you times "
                    "its worth; the two superpowers do not count towards it, and "
                    "you are racing the opponent for the same countries",
            "aid_is_annual": "aid and troops persist until you change them; "
                             "sending none repeals the policy",
            "provocation": "aid to insurgents, intervention for rebels and "
                           "destabilization can trigger a crisis that may end in "
                           "nuclear war, which is a total loss for you",
            "staging": "insurgency aid and rebel intervention need troops "
                       "supporting a government in a country bordering the target",
        },
    }
    # The choice question's own criteria describe the candidate countries in
    # full, so repeating all 78 of them here would cost tokens for nothing.
    # The first version of this did exactly that: 18.5k input tokens for two
    # calls.  A short neighbourhood line gives global context cheaply.
    leaders = sorted(world.country[2:], key=lambda c: -c.prestigeVal)[:6]
    state["the_most_valuable_countries"] = [
        "%s (worth %d, opinion of you %d, of the opponent %d)"
        % (Local.countryName(c.id), c.prestigeVal // 64, actor.diplOpinion[c.id],
           opponent.diplOpinion[c.id])
        for c in leaders]
    if focus is not None:
        state["focus_country"] = {
            "id": focus.id,
            "name": Local.countryName(focus.id),
            "worth": focus.prestigeVal // 64,
            "opinion_of_you": actor.diplOpinion[focus.id],
            "opinion_of_opponent": opponent.diplOpinion[focus.id],
            "stability_0_civil_war_6_peaceful": focus.getInsurgency(),
            "government_popularity_0_20": focus.govtPopul,
            "your_troops_0_5": actor.govtIntv[focus.id],
            "their_troops_0_5": opponent.insgIntv[focus.id],
            "borders_a_country_you_occupy": bool(
                any(k.contig[focus.id] and actor.govtIntv[k.id] > 0
                    for k in world.country[2:]) or actor.contig[focus.id]),
            "your_current_policy_step": current_level(actor, focus, GOVTAID),
        }
    return state


def build_focus_questions(world, actor, opponent):
    """The first decision of the turn: where, and whether to act twice."""
    shortlist = _candidate_countries(world, actor, opponent)
    criteria = {}
    for country in shortlist:
        here = current_level(actor, country, GOVTAID)
        room = affordable_step(world, actor, country, GOVTAID)
        if room is None:
            head = "no aid is possible there"
        elif room > here:
            head = "aid there is %d/5 now, up to %d affordable" % (here, room)
        elif here:
            head = "your aid there is already at its limit (%d)" % here
        else:
            head = "no aid can go there now: your influence is too low or the budget is spent"
        criteria[str(country.id)] = (
            "%s: worth %d, opinion of you %d, of the opponent %d, stability %d/6 (0 civil war, 6 peaceful), "
            "your troops %d, theirs %d, %s"
            % (Local.countryName(country.id), country.prestigeVal // 64,
               actor.diplOpinion[country.id], opponent.diplOpinion[country.id],
               country.getInsurgency(), actor.govtIntv[country.id],
               opponent.govtIntv[country.id], head))
    questions = {
        "focus": {
            "type": "choice",
            "instructions": "Which single country should %s concentrate its "
                            "diplomatic effort on this year, to raise the sum of "
                            "opinion times worth fastest? Prefer a country where "
                            "your influence is behind the opponent's and where you "
                            "still have room to spend." % actor.name,
            "criteria": criteria,
        },
        "act_again": {
            "type": "noul",
            "instructions": "Is a second, separate country worth acting on this "
                            "year as well, given the finite aid and troop budget?",
        },
    }
    return questions, shortlist


def build_posture_questions(world, actor, opponent, focus):
    """The second decision: what to do there, and how much.

    A verb that cannot be carried out in this country right now — because the
    actor's influence there is too low, the treaty forbids it, or the aid and
    troop budgets are committed elsewhere — is left out of the question
    altogether.  Offering it only invites an answer that ``apply`` then discards,
    which used to make the opponent's log describe moves it never made.  When
    nothing at all is affordable the whole list comes back, annotated, so the
    model still answers and the plan legitimately comes out empty.
    """
    available = [a for a in sorted(ACTION_NAMES) if a in AVL_ACTIONS[world.level - 1]]
    usable, blocked = [], []
    for action in available:
        here = current_level(actor, focus, action)
        room = affordable_step(world, actor, focus, action)
        if room is None:
            continue
        if room > here:
            usable.append((action, here, room))
        else:
            blocked.append((action, here, room))
    entries = usable or blocked
    criteria = {}
    for action, here, room in entries:
        line = "%s (currently at step %d towards this country" % (
            VERB_BRIEF[action], here)
        if room > here:
            line += "; you can afford at most step %d there this year)" % room
        elif here:
            line += "; already at the highest step open to you there, so a "\
                    "higher one cannot happen)"
        else:
            line += "; not open to you there at all this year, because your "\
                    "influence is too low or the budget is committed elsewhere)"
        criteria[ACTION_NAMES[action]] = line
    questions = {
        "posture": {
            "type": "choice",
            "instructions": "What should %s do about %s this year?"
                            % (Local.countryName(actor.id), Local.countryName(focus.id)),
            "criteria": criteria,
        },
        "level": {
            "type": "score",
            "instructions": "How far should that policy go? None repeals the "
                            "existing policy; maximum commits the most resources "
                            "and provokes the most. Do not exceed what the "
                            "criteria say you can afford.",
            "criteria": list(LEVEL_CRITERIA),
        },
    }
    return questions


# ---------------------------------------------------------------------------
# The opponent
# ---------------------------------------------------------------------------

class LLMOpponent(object):
    """Turns the computer superpower's move over to a language model."""

    def __init__(self, config=None, client=None, notify=None, record=None,
                 execute=None):
        self.config = config or LLMConfig()
        self.client = client or LLMClient(self.config)
        #: The decision model (Jev) and the text model (advisors) are different
        #: APIs; only one of these is used for the opponent's move.
        self.jev = JevClient(self.config)
        self.backend = self.config.resolved_backend()
        #: Optional runner that executes a blocking callable off the UI thread
        #: (see Async.run_blocking).  Defaults to calling it inline.
        self.execute = execute or (lambda fn, timeout=None: fn())
        #: Called with a short string while we wait (drives the status bar).
        self.notify = notify
        #: Called with the last plan, for the UI log.
        self.record = record
        self.history = []
        #: Every plan this game, newest last: (year, actions, reasoning).
        self.turn_log = []
        self.last_plan = None
        self.last_error = ""
        #: Evidence behind the last decision-model plan: question id -> JevAnswer,
        #: plus the option drawn and the id->name labels used to render the log.
        self.last_evidence = None
        self.last_taken = {}
        self.last_labels = {}
        #: How the human has resolved crises so far.  A model deciding whether to
        #: contest the next move should know whether this player folds or stands;
        #: otherwise every crisis is judged in isolation and the opponent never
        #: learns anything about the person it is playing.
        self.human_record = {"backed_down": 0, "stood_firm": 0}
        self.stats = {"turns": 0, "llm": 0, "fallback": 0, "actions": 0}
        self._budget_warned = False
        #: The circuit breaker.  Plans and verdicts are counted separately: a
        #: verdict call that happens to succeed between two failed plans must
        #: not reset the plan count, or a plan that fails every turn never
        #: trips it.  ``disabled`` stops the opponent asking at all;
        #: ``verdicts_disabled`` stops only the crisis judgements.
        self.consecutive_failures = 0          # plans
        self.verdict_failures = 0
        self.disabled = False
        self.verdicts_disabled = False
        #: Why the last turn was played by the built-in AI: ``(kind, sentence)``.
        self.last_fallback = None
        self._empty_streak = 0
        self._said_kind = None
        self.last_apply = {"held": 0, "rejected": 0, "clamped": 0}
        #: One call count for the whole game, opponent and advisors together
        #: (the advisors' configuration is a copy of this one and shares it).
        self.config.game_budget = SharedBudget(owner=self)

    def reset_failures(self):
        """Close the breaker again (the player changed the settings)."""
        self.consecutive_failures = 0
        self.verdict_failures = 0
        self.disabled = False
        self.verdicts_disabled = False
        self._budget_warned = False
        self._empty_streak = 0
        self._said_kind = None

    def _note_failure(self, actor_name=None, reason=""):
        """Count a failed plan; trip the breaker on the second in a row."""
        self.consecutive_failures += 1
        if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES and not self.disabled:
            self.disabled = True
            if actor_name:
                self._say("%s's model %s; the built-in AI plays the rest of "
                          "this game." % (actor_name, reason or "is not answering"))

    def _note_verdict_failure(self):
        self.verdict_failures += 1
        if self.verdict_failures >= MAX_CONSECUTIVE_FAILURES:
            self.verdicts_disabled = True

    def _run(self, fn, deadline):
        """Run a blocking call off the UI thread, inside the turn's deadline.

        The UI waits a few seconds longer than the call is allowed to run, so
        the call's own deadline normally fires first.  If the UI does give up
        (a stalled read, say) the worker is told to stop trying anything else.
        """
        span = max(1.0, deadline.remaining()) + 3.0
        try:
            return self.execute(fn, span)
        except TimeoutError:
            deadline.cancel()
            raise

    def _new_deadline(self):
        return Deadline(max(1.0, self.config.timeout) * TURN_DEADLINE_FACTOR)

    def _fallback(self, exc, actor):
        """Record why the built-in AI is playing this turn, and tell the player once."""
        self.last_error = str(exc) or type(exc).__name__
        self.stats["fallback"] += 1
        if isinstance(exc, LLMNotConfigured):
            # No key is a setting, not a fault: the status bar and the opponent
            # log's header already say the built-in AI is playing.
            return
        kind = failure_kind(exc)
        phrase = failure_phrase(exc)
        self.last_fallback = (kind, phrase)
        if kind == "budget":
            # A spent budget is a limit, not a fault: it costs nothing to
            # re-check and must not trip the breaker.  Said once, then silent.
            if not self._budget_warned:
                self._budget_warned = True
                self._say("%s's model budget is used up; the built-in AI takes "
                          "over." % actor.name)
                self._log_fallback("The model's call budget for this game is used "
                                   "up, so the built-in AI plays the rest of it.")
            return
        was_disabled = self.disabled
        self._note_failure(actor.name, "is not answering (%s)" % phrase)
        hint = FAILURE_HINTS.get(kind, "")
        detail = _redact(self.last_error, self.config.api_key)[:160]
        self._log_fallback("The model %s, so the built-in AI played this turn. %s "
                           "(%s)" % (phrase, hint, detail))
        if self.disabled and not was_disabled:
            return                      # the breaker's own message was just said
        if not self.disabled and self._said_kind != kind:
            self._said_kind = kind
            self._say("%s's model %s; the built-in AI takes over."
                      % (actor.name, phrase))

    def _log_fallback(self, text):
        if self.record:
            try:
                self.record(PolicyPlan([], text, source="fallback"))
            except Exception:
                pass

    # -- public -------------------------------------------------------------

    @property
    def offline(self):
        return self.config.offline or self.config.model == MOCK_MODEL

    def take_turn(self, world, actor, opponent):
        """Plan and enact this year's policies.  Returns True if we handled it.

        Returning False means "I could not, use the heuristic AI" — the caller
        then runs ``compuAI`` as usual.
        """
        self.stats["turns"] += 1
        if self.disabled:
            # The breaker has tripped: no request, no wait, no repeated message.
            self.stats["fallback"] += 1
            return False
        deadline = self._new_deadline()
        logged = len(self.turn_log)
        try:
            plan = self.plan(world, actor, opponent, deadline=deadline)
            proposed = plan.proposed
            attempted = list(plan.actions)
            applied = self.apply(world, actor, plan)
            if plan.source in ("llm", "jev"):
                self._check_played(plan, proposed, attempted, applied)
        except Exception as exc:
            # Any failure at all - transport, a malformed answer, a plan that
            # does not parse, a bug in the briefing - is the built-in AI's cue.
            # The module promises the player never loses a turn, so this is
            # deliberately not limited to LLMError.
            del self.turn_log[logged:]      # a plan that did not happen is not history
            if isinstance(exc, _Unplayable) and not exc.counts:
                self.last_error = str(exc)
                self.stats["fallback"] += 1
                self._log_fallback("What the model asked for did not fit the "
                                   "budget or the rules this year, so the "
                                   "built-in AI played the turn.")
                return False
            self._fallback(exc, actor)
            return False
        self.consecutive_failures = 0
        self.last_plan = plan
        if self.record:
            self.record(plan)
        # The plan now holds only what was enacted, so the recorded line cannot
        # promise a policy the budget refused.
        plan.reasoning = self._summarise(plan, self.last_evidence,
                                         self.last_labels, self.last_taken)
        if self.turn_log:
            year, _, _ = self.turn_log[-1]
            if year == world.year:
                self.turn_log[-1] = (year, list(plan.actions), plan.reasoning)
        self.stats["actions"] += len(applied)
        self.stats["llm"] += 1
        return True

    def _check_played(self, plan, proposed, attempted, applied):
        """Decide whether a validated plan counts as a turn the model played.

        A model that proposed actions of which none survived validation has
        not played; neither has one that says "do nothing" turn after turn.
        Either way the built-in AI must move, or the opponent sits idle all
        game.  Only invalid proposals count towards the breaker: when the
        actions were legal but the budget was already spent, that is the
        position's doing and not a fault of the model.
        """
        if applied:
            self._empty_streak = 0
            return
        if proposed == 0:
            self._empty_streak += 1
            if self._empty_streak > MAX_EMPTY_PLANS:
                raise LLMError("the model answered with nothing usable: it has "
                               "proposed no policy for %d turns running"
                               % self._empty_streak)
            return
        if self.last_apply["held"]:
            return                      # it chose to leave a policy where it is
        if self.last_apply["rejected"] >= len(attempted):
            raise LLMError("the model's plan contained nothing usable: every "
                           "action it proposed was illegal")
        # Legal, but the budget or the ceiling left no room for any of it.
        raise _Unplayable("the model's actions all exceeded what the budget allows",
                          counts=False)

    def verdicts(self, world, actor, opponent, candidates):
        """Ask the model which of the human's moves to turn into a crisis.

        ``candidates`` is a list of ``(news, stake)`` pairs, one per provocative
        move the human made this turn.  All of them go into a *single* request:
        a decision model answers every question against one state, so however
        many moves the human made this costs one call per turn.

        Returns ``{news: (escalate, description)}``; an empty dict means the
        model has no opinion and the caller should fall back to the heuristics.

        The question is deliberately a ``noul`` — a single credence — and not a
        ``choice`` between "contest" and "let it stand".  Both shapes were tried
        against the live model on a turn with three provocative moves: the choice
        form collapsed to roughly 50/50 on every move, and even ranked the
        mildest move above the most provocative one, while the ``noul`` form gave
        a stable reading that separated them.  If this is ever changed back, it
        needs measurements to justify it.
        """
        if not candidates:
            return {}
        if (self.backend != "decisions" or self.offline or self.disabled
                or self.verdicts_disabled):
            return {}
        if not self.config.usable:
            # No key: the heuristics judge, silently, as they do offline.
            return {}
        # ``None`` means unlimited; only a budget that is really spent stops us.
        left = self.jev.budget_left()
        if left is not None and left <= 0:
            return {}

        state = build_decision_state(world, actor, opponent)
        state["the_opponent_has_just_done_these_things"] = [
            "%s (%s) moved %s in %s from step %d to %d; it costs you %d of "
            "standing and is worth %d of theirs"
            % (Local.countryName(news.actor.id), news.actor.leaderName,
               ACTION_NAMES.get(news.action, news.action),
               Local.countryName(news.target.id),
               news.old, news.new, stake, news.target.prestigeVal // 64)
            for news, stake in candidates]
        state["what_a_crisis_means"] = (
            "Escalating opens a confrontation that runs down a nine-rung ladder. "
            "Either side may back down or push, and at the bottom is a nuclear "
            "exchange that is a total loss for you. A human who is pushed may "
            "also back down, which wins the point outright.")
        record = self.human_record
        state["how_the_opponent_has_handled_crises_so_far"] = (
            "they have backed down %d times and stood firm %d times"
            % (record.get("backed_down", 0), record.get("stood_firm", 0)))
        questions = {}
        index_of = {}
        for index, (news, _stake) in enumerate(candidates):
            key = "escalate_%d" % index
            # Keyed by the news object itself rather than by id(): id() is only
            # unique among live objects and is a footgun to cache.
            index_of[index] = news
            questions[key] = {
                "type": "noul",
                "instructions": "The opponent's move %d: %s in %s, step %d to %d. "
                                "Do you contest it and open a crisis?"
                                % (index, ACTION_NAMES.get(news.action, news.action),
                                   Local.countryName(news.target.id),
                                   news.old, news.new),
            }
        deadline = self._new_deadline()
        try:
            answers = self._run(lambda: self.jev.decide(state, questions,
                                                        deadline=deadline), deadline)
        except Exception as exc:
            if failure_kind(exc) != "budget":
                self._note_verdict_failure()
            raise
        self.verdict_failures = 0
        verdicts = {}
        for index, news in index_of.items():
            answer = answers.get("escalate_%d" % index)
            if answer is None:
                continue
            # A sentence for the reasoning window, not ``describe()``: that
            # one is written for the log and reads "yes with probability 62%",
            # which is not what a player should be shown next to a country name.
            chance = max(0.0, min(1.0, float(getattr(answer, "noul", 0.0))))
            escalate = bool(answer.sample())
            verdicts[news] = (escalate,
                              ("contest it, %.0f%% likely" % (chance * 100))
                              if escalate else
                              ("let it stand (%.0f%% chance of contesting)"
                               % (chance * 100)))
        return verdicts

    def memory_summary(self, limit=8):
        """A compact record of this game, so the model is not a goldfish.

        Only the model's own moves are summarised; outcomes it can already see
        in the board.  Kept to a few lines so the prompt does not grow without
        bound over a nine-turn game.
        """
        if not self.turn_log:
            return ""
        lines = ["YOUR MOVES SO FAR (most recent last)"]
        for year, actions, _ in self.turn_log[-limit:]:
            if not actions:
                lines.append("  %d: stood pat" % year)
                continue
            described = ", ".join(
                "%s->%s(%d)" % (ACTION_NAMES.get(a, "?"), t, lvl)
                for a, t, lvl in actions[:6])
            lines.append("  %d: %s" % (year, described))
        return "\n".join(lines)

    def plan(self, world, actor, opponent, deadline=None):
        deadline = deadline or self._new_deadline()
        self.last_evidence = None
        self.last_taken = {}
        self.last_labels = {}
        if not self.offline and not self.config.usable:
            # Both backends need a key.  Raised here, before either is asked, so
            # that take_turn sees one kind of "no key" whichever backend the
            # model id selects (the decisions client only knows JevError).
            raise LLMNotConfigured("no API key configured")
        if self.backend == "decisions" and not self.offline:
            return self._plan_decisions(world, actor, opponent, deadline)
        return self._plan_chat(world, actor, opponent, deadline)

    def _plan_decisions(self, world, actor, opponent, deadline=None):
        """Ask the decision model, in two well-posed rounds.

        Round one picks the country; round two picks what to do about it.  They
        are separate calls because a decision model answers every question
        against the *same* state, and "what should we do" is only a sensible
        question once the country is known.
        """
        deadline = deadline or self._new_deadline()
        self._say("%s is deliberating\u2026" % actor.name)
        questions, shortlist = build_focus_questions(world, actor, opponent)
        state = build_decision_state(world, actor, opponent)
        answers = self._run(lambda: self.jev.decide(state, questions,
                                                    deadline=deadline), deadline)
        evidence = dict(answers)

        focus_answer = answers.get("focus")
        if focus_answer is None:
            raise JevError("the decision model did not answer the focus question")
        # The game plays the sampled option, not the argmax: Jev hands back a
        # whole distribution and drawing from it keeps the opponent from being
        # predictable.  Record which option was drawn so the log can be honest
        # about it when the draw is not the favourite.
        focus_key = focus_answer.sample(floor=DECISION_FLOOR)
        try:
            focus_id = int(focus_key)
        except (TypeError, ValueError):
            focus_id = int(shortlist[0].id)
        if not 2 <= focus_id < len(world.country):
            focus_id = int(shortlist[0].id)
        focus = world.country[focus_id]

        # A second action only when the model says the budget stretches.
        second = None
        act_again = answers.get("act_again")
        second_wanted = bool(act_again.sample()) if act_again is not None else False
        if second_wanted:
            remaining = [c for c in shortlist if c.id != focus_id]
            if remaining:
                second = remaining[0]

        posture_questions = build_posture_questions(world, actor, opponent, focus)
        state2 = build_decision_state(world, actor, opponent, focus=focus)
        answers2 = self._run(lambda: self.jev.decide(state2, posture_questions,
                                                     deadline=deadline), deadline)
        evidence.update(answers2)

        self.last_evidence = evidence
        self.last_labels = dict((str(c.id), Local.countryName(c.id))
                                for c in world.country)
        posture_answer = evidence.get("posture")
        # Drawn exactly once: the verb that is logged and the verb that is played
        # have to be the same draw, or the log describes a move nobody made.
        posture_name = (posture_answer.sample(floor=DECISION_FLOOR)
                        if posture_answer is not None else None)
        self.last_taken = {
            "focus": focus_key,
            "act_again": "yes" if second_wanted else "no",
            "posture": posture_name,
        }
        plan = self._plan_from_answers(world, actor, focus, second, evidence,
                                       posture_name)
        summary = self._summarise(plan, evidence, self.last_labels, self.last_taken)
        plan.reasoning = summary
        self.turn_log.append((world.year, list(plan.actions), summary))
        self.history = []          # nothing to carry; the state carries it
        return plan

    def _plan_from_answers(self, world, actor, focus, second, evidence,
                           posture_name=None):
        """Turn typed answers into policy changes, then let the ceilings decide.

        ``posture_name`` is the verb already drawn by the caller; passing it in
        rather than drawing again keeps the logged move and the played move one
        and the same.
        """
        actions = []
        level = evidence.get("level")
        if posture_name is None:
            posture = evidence.get("posture")
            posture_name = (posture.sample(floor=DECISION_FLOOR)
                            if posture is not None else None)
        action = ACTION_IDS.get(posture_name)
        if action is None and posture_name is not None:
            action = ACTION_IDS.get(str(posture_name).strip().lower())
        if action is not None:
            step = int(round(level.score)) if level is not None else 2
            step = max(0, min(5, step))
            actions.append((action, focus.id, step))
            if second is not None:
                # Same posture, one notch lower on the second country: the
                # budget is finite and the model was not asked about it again.
                actions.append((action, second.id, max(0, step - 1)))
        plan = PolicyPlan(actions, "", source="jev", evidence=evidence)
        plan.reasoning = self._summarise(plan, evidence, self.last_labels,
                                         self.last_taken)
        return plan

    @staticmethod
    def _summarise(plan, evidence, labels=None, taken=None):
        """The opponent-log line for a move.

        The log is read by the player, so every line is a sentence with country
        names in it: the country the opponent concentrated on, whether it acted
        on a second country, what it did, and how far it went.  The answers are
        probability distributions that the game samples, so the option played is
        often not the model's favourite, and the budget can still refuse a step.
        The line is therefore built from what was enacted, and it names the
        favourite only as the alternative it was.
        """
        if not evidence:
            return plan.reasoning
        labels = labels or {}
        taken = taken or {}
        parts = []
        step = LLMOpponent._step_taken(evidence)
        focus = LLMOpponent._choice_line(evidence, taken, labels, "focus", "Country chosen")
        if focus:
            parts.append(focus)
        if evidence.get("act_again") is not None:
            second = str(taken.get("act_again", "")).strip().lower() in ("yes", "true", "1")
            parts.append("Second country this year: %s." % ("yes" if second else "no"))
        if evidence.get("posture") is not None:
            verb = LLMOpponent._verb_label(LLMOpponent._verb_taken(evidence, taken))
            line = "Action: %s" % verb
            if step is not None:
                line += ", step %d" % step
            parts.append(line + ".")
        elif step is not None:
            parts.append("Step: %d." % step)
        if plan.actions:
            parts.append("Did: " + ", ".join(
                "%s in %s, step %d"
                % (LLMOpponent._verb_label(a), labels.get(str(t), "country %s" % t), lvl)
                for a, t, lvl in plan.actions) + ".")
        else:
            parts.append("Did: nothing (its aid and troop budgets were already "
                         "committed).")
        return " ".join(parts)

    @staticmethod
    def _verb_label(action):
        """A policy verb as the player reads it.

        Accepts either spelling because the two ends differ: a question answer
        carries the machine name the model was asked for ("military_aid"), while
        an enacted action carries the verb's constant (a country id-like int).
        """
        if action in ACTION_DISPLAY_NAMES:
            return ACTION_DISPLAY_NAMES[action]
        action_id = ACTION_IDS.get(str(action).strip().lower())
        if action_id in ACTION_DISPLAY_NAMES:
            return ACTION_DISPLAY_NAMES[action_id]
        return ACTION_DISPLAY_NAMES.get(ACTION_NAME_ALIASES.get(
            str(action).strip().lower()), str(action))

    @staticmethod
    def _verb_taken(evidence, taken):
        """The verb the game actually played, not the model's favourite."""
        name = taken.get("posture")
        if name in (None, ""):
            answer = evidence.get("posture")
            name = getattr(answer, "choice", None) if answer is not None else None
            if name in (None, "") and answer is not None:
                try:
                    name = answer.best()
                except (AttributeError, TypeError):
                    name = None
        return name

    @staticmethod
    def _choice_line(evidence, taken, labels, key, lead):
        """One sentence about a country choice and the runner-up.

        The engine samples the model's distribution, so the country played is
        sometimes not the most likely one.  When that happens the sentence says
        so instead of crediting the opponent with a choice it did not make.
        """
        answer = evidence.get(key)
        if answer is None:
            return ""
        taken_key = taken.get(key)
        try:
            best = answer.best()
        except (AttributeError, TypeError):
            best = None
        lead_key = best if best is not None else getattr(answer, "choice", None)
        if lead_key in (None, ""):
            lead_key = taken_key
        if lead_key in (None, ""):
            return ""
        share = LLMOpponent._share(answer, lead_key, None)
        runner = LLMOpponent._runner_up(answer, lead_key)
        text = "%s: %s" % (lead, LLMOpponent._country_label(lead_key, labels))
        if share is not None:
            text += " (%d%% likely" % round(share * 100)
        if runner is not None:
            if share is None:
                text += " (next best %s" % LLMOpponent._country_label(runner, labels)
            else:
                text += "; next best %s, %d%%" % (
                    LLMOpponent._country_label(runner, labels),
                    round(LLMOpponent._share(answer, runner, 0.0) * 100))
        if share is not None or runner is not None:
            text += ")"
        if taken_key not in (None, "") and str(taken_key) != str(lead_key):
            # The engine drew an option that was not the most likely one: the
            # sentence must say so, or it credits the opponent with a choice it
            # did not make.
            text = "%s: %s" % (lead, LLMOpponent._country_label(taken_key, labels))
            taken_share = LLMOpponent._share(answer, taken_key, None)
            if taken_share is not None:
                text += " (%d%% likely)" % round(taken_share * 100)
            return text + ". The model preferred %s." % LLMOpponent._country_label(
                lead_key, labels)
        return text + "."

    @staticmethod
    def _runner_up(answer, main):
        """The second most likely option, if the answer has probabilities."""
        probabilities = getattr(answer, "probabilities", None) or {}
        ranked = sorted(((k, v) for k, v in probabilities.items()
                         if str(k) != str(main)), key=lambda item: -item[1])
        return ranked[0][0] if ranked else None

    @staticmethod
    def _share(answer, key, default):
        probabilities = getattr(answer, "probabilities", None) or {}
        try:
            return float(probabilities.get(str(key),
                                           probabilities.get(key, default)))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _country_label(key, labels):
        """The country's name when a world supplied one, else its id."""
        if key in (None, ""):
            return "?"
        return labels.get(str(key)) or "country %s" % key

    @staticmethod
    def _step_taken(evidence):
        """The step the model asked for, as a whole number, if it answered."""
        answer = evidence.get("level")
        if answer is None:
            return None
        try:
            return int(round(float(getattr(answer, "score", 0.0))))
        except (TypeError, ValueError, AttributeError):
            return None

    def _plan_chat(self, world, actor, opponent, deadline=None):
        deadline = deadline or self._new_deadline()
        briefing = build_briefing(world, actor, opponent)
        memory = self.memory_summary()
        if memory:
            briefing = briefing + "\n\n" + memory
            # The window is the point of the summary; drop the raw turns it
            # replaces so the two do not say the same thing twice.
            self.history = self.history[-1:]
        if self.offline or not self.config.usable:
            if not self.config.usable and not self.offline:
                raise LLMNotConfigured("no API key configured")
            return self._mock_plan(world, actor, opponent, briefing)

        self._say("%s is deliberating\u2026" % actor.name)
        system = SYSTEM_PROMPT.format(
            country=actor.name, opponent=opponent.name,
            max_actions=MAX_ACTIONS_PER_TURN)
        messages = [{"role": "system", "content": system}]
        # A short memory of the last two turns keeps the model coherent without
        # letting the context grow without bound over a nine-turn game.
        for entry in self.history[-2:]:
            messages.append(entry)
        messages.append({"role": "user", "content": briefing})
        # chat_chain returns text; the JSON lives inside it (and is often wrapped
        # in prose), so it goes through the same extractor as any other answer.
        raw = self._run(
            lambda: self.client.chat_chain(messages,
                                           response_format=POLICY_SCHEMA,
                                           deadline=deadline),
            deadline)
        answer = extract_json(raw)
        plan = self._parse(answer, world, actor)
        self.history.append({"role": "assistant",
                             "content": json.dumps({"reasoning": plan.reasoning,
                                                    "actions": plan.actions})})
        self.turn_log.append((world.year, list(plan.actions), plan.reasoning))
        return plan

    # -- parsing and validation --------------------------------------------

    def _parse(self, payload, world, actor):
        if not isinstance(payload, dict):
            raise LLMError("the model did not return a JSON object")
        reasoning = str(payload.get("reasoning") or "")[:400]
        raw = payload.get("actions")
        if raw is None:
            raw = []
        if not isinstance(raw, list):
            raise LLMError("'actions' was not a list")
        actions = []
        asked = raw[:MAX_ACTIONS_PER_TURN]
        for item in asked:
            if not isinstance(item, dict):
                continue
            name = str(item.get("action", "")).strip().lower()
            action = ACTION_IDS.get(name)
            if action is None:
                action = ACTION_NAME_ALIASES.get(name)
            if action is None:
                continue
            try:
                target_id = int(item.get("target"))
                level = int(item.get("level"))
            except (TypeError, ValueError, OverflowError):
                continue
            if not 2 <= target_id < len(world.country):
                continue
            actions.append((action, target_id, max(0, min(5, level))))
        if asked and not actions:
            raise LLMError("the model's plan contained nothing usable: none of "
                           "its %d proposed actions named a real verb and country"
                           % len(asked))
        plan = PolicyPlan(actions, reasoning, source="llm")
        plan.proposed = len(asked)
        plan.rejected = len(asked) - len(actions)
        return plan

    def apply(self, world, actor, plan):
        """Enact a plan, clamping every step to what is actually legal.

        Ceilings are recomputed before each action because spending on one
        country reduces what is left for the next — exactly as ``compuAI``
        behaves.  Returns what was really enacted, in order, so the log can show
        the player the opponent's actual move rather than its intention.
        """
        from GameLogic.Globals import doPolicy
        enacted = []
        held = rejected = clamped = 0
        for action, target_id, level in plan.actions:
            target = world.country[target_id]
            budget = maxPolicy(actor)
            ceiling = action_ceiling(world, actor, target, action,
                                     budget[0], budget[1], economic_ceiling(world, actor))
            if ceiling is None:
                rejected += 1
                continue
            requested = level
            level = min(level, ceiling)
            if action in (TREATY, TRADE):
                # A commitment is never withdrawn on the model's say-so: neither
                # the heuristic AI nor the human's dialog can lower one, and a
                # level-0 request would otherwise tear up a standing treaty.
                level = max(level, current_level(actor, target, action))
            if level == current_level(actor, target, action):
                if requested == level:
                    held += 1           # it asked for what is already there
                else:
                    clamped += 1        # the rules left no room for what it asked
                continue
            doPolicy(world, actor, target, action, level)
            enacted.append((action, target_id, level))
        self.last_apply = {"held": held, "rejected": rejected, "clamped": clamped}
        plan.actions = enacted
        return enacted

    # -- offline backend ----------------------------------------------------

    def _mock_plan(self, world, actor, opponent, briefing):
        """A deterministic planner, used with no network or no API key.

        It runs through the same parse/validate/apply path as a real answer, so
        the level remains playable — and testable — entirely offline.
        """
        budget = maxPolicy(actor)
        max_intv, max_aid = budget[0], budget[1]
        max_econ = economic_ceiling(world, actor)
        scored = []
        for country in world.country[2:]:
            mine = actor.diplOpinion[country.id]
            theirs = opponent.diplOpinion[country.id]
            worth = country.prestigeVal // 64
            scored.append((mine * 2 - theirs + worth, country))
        scored.sort(key=lambda item: item[0], reverse=True)

        actions = []
        # Help the countries we are winning, hurt the ones they are winning.
        for _, country in scored[:3]:
            if len(actions) >= MAX_ACTIONS_PER_TURN - 1:
                break
            ceiling = action_ceiling(world, actor, country, GOVTAID,
                                     max_intv, max_aid, max_econ)
            if ceiling and ceiling > current_level(actor, country, GOVTAID):
                actions.append((GOVTAID, country.id, min(3, ceiling)))
        for _, country in scored[-3:]:
            if len(actions) >= MAX_ACTIONS_PER_TURN:
                break
            if country.getInsurgency() <= 4:  # not peaceful (6 is peaceful)
                ceiling = action_ceiling(world, actor, country, INSGAID,
                                         max_intv, max_aid, max_econ)
                if ceiling and ceiling > current_level(actor, country, INSGAID):
                    actions.append((INSGAID, country.id, min(2, ceiling)))
        return PolicyPlan(actions, "Built-in AI: it aided the countries it was "
                                   "winning and the insurgents it could reach.",
                          source="mock")

    # -- plumbing -----------------------------------------------------------

    def _say(self, text):
        if self.notify:
            try:
                self.notify(text)
            except Exception:
                pass

    def status_line(self):
        """One line for the status bar: what is playing the other side."""
        if self.config.offline or self.config.model == MOCK_MODEL:
            return "Opponent: built-in AI"
        if not self.config.api_key:
            return "Opponent: built-in AI (no API key)"
        if self.disabled:
            return "Opponent: built-in AI (model not answering)"
        if self.backend == "decisions":
            left = self.jev.budget_left()
            if left is not None and left <= 0:
                return "Opponent: built-in AI (model budget spent)"
            return "Opponent: %s (%s)" % (self.config.model, self.jev.spend_report())
        left = self.client.budget_left()
        if left is not None and left <= 0:
            return "Opponent: built-in AI (model budget spent)"
        return "Opponent: %s" % self.config.model
