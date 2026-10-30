"""
Head-to-head crises between the two superpowers when *both* are human.

The single-player escalation ladder lives in :mod:`GameLogic.CrisisHandler` and
is tightly bound to the news window and to the computer opponent.  When two
people play — over a LAN or hot-seat — the original rules never fire at all
(``reactNews`` deliberately skips the AI branches when ``twoPFlag`` is set), so
two players could provoke each other with total impunity.

This module supplies the missing half: a small, self-contained state machine
that both machines can drive identically.

The ladder
----------
1. A player enacts a provocative policy.
2. The *challenged* superpower is asked whether to contest it.  Declining means
   the policy simply stands.
3. If contested, the two sides alternate: each may **back down** (the policy is
   reverted and the player pays in prestige and world opinion) or **tough it
   out** (the crisis steps one rung down the ladder).
4. Reaching DEFCON 1 means a nuclear exchange, and everybody loses.  From
   DEFCON 2 the risk of an *accidental* launch is rolled, exactly as in the
   single-player game.

The summit
----------
The original game cut the summit conference, and the loss shows: with only
back-down-or-escalate, a crisis is a pure bluff and the side with the stronger
nerve always wins.  A third option restores the bargain.  From the escalation
phase either side may **propose a summit**, once per crisis.  The proposal is
that side's own yes; the other side answers it, and:

* two yeses freeze the crisis where it stands, cost nobody any face, and let the
  tension down a rung;
* a refusal costs the refuser face: credibility, standing with the unaligned
  world, and a reputation for belligerence.  The crisis then carries on.

That asymmetry is the whole point.  Escalating is no longer strictly dominant,
because a summit that the other side accepts is cheaper than winning, and a
summit you refuse is expensive even when you go on to win.

This is an addition, not a restoration: the mechanic is described in the
literature on the original but was not shipped in it.

Everything here is pure logic over the existing ``World``; no widgets, and no
randomness beyond the chance of accidental war, so the host and the guest stay
in step.
"""

from random import randint

from GameLogic.Globals import (changeDiplOpinion, changeDMess, doPolicy, gimpt,
                               impt, should, tdiv)
from GameLogic.News import News
from constants import (CRISIS_RISK_SCALE, DESTAB, ECONAID, GOVTAID, GOVTINTV,
                       INGSINTV, INSGAID, PRESSURE, TRADE, TREATY)

#: The crisis starts here and counts down to 1 (nuclear war).
MAX_LEVEL = 9
#: Number of crises resolved per turn before the rest are dropped.  Without a
#: cap a busy turn turns into an interrogation.
MAX_CRISES_PER_TURN = 3

#: Actions that are always worth contesting when they go up.
_HOSTILE = (DESTAB, INSGAID, INGSINTV)
#: Actions worth contesting only when the step is large.
_ENCROACHING = (GOVTAID, GOVTINTV, ECONAID, TREATY, PRESSURE, TRADE)

#: What a refused summit costs the side that refused.
SUMMIT_REFUSAL_INTEGRITY = 12
SUMMIT_REFUSAL_OPINION = 2
SUMMIT_REFUSAL_PUGNACITY = 6
#: What a summit that both sides attend buys: a rung of relief.
SUMMIT_RELIEF_NASTINESS = 12
SUMMIT_RELIEF_PUGNACITY = 6


def contestable_news(world, limit=MAX_CRISES_PER_TURN):
    """Return the headlines the challenged player should be asked about.

    Only increases matter: a player withdrawing aid is not a provocation.
    """
    candidates = []
    for n in world.news:
        if n.crisisVal or n.new <= n.old:
            continue
        if n.actor.id >= 2 or n.actor.id == n.target.id:
            continue
        if n.target.id < 2:
            continue
        challenged = world.country[1 - n.actor.id]
        if challenged.id == n.target.id:
            continue
        stake = _stake(world, n, challenged)
        if stake <= 0:
            continue
        if n.action in _HOSTILE:
            worth_it = True
        elif n.action in _ENCROACHING:
            worth_it = (n.new - n.old) >= 2 or n.action == PRESSURE
        else:
            worth_it = False
        if not worth_it:
            continue
        candidates.append((n.importance, stake, n))
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [n for _, _, n in candidates[:limit]]


def _stake(world, news, superpower):
    """How much ``superpower`` cares about ``news``, in prestige terms."""
    gimpt(world, news.actor, news.action, news.target, news.old, news.new, 0)
    raw = world.crisis.usaImpt if superpower.id == 0 else world.crisis.ussrImpt
    return raw


def prestige_at_risk(world, news, loser, level):
    """What ``loser`` would pay in prestige by backing down at ``level``.

    The figure the one-player news window shows as "Prestige at risk"
    (``CrisisHandler._show_penalties``, from CrisisU.p): the shift of the
    unaligned countries' opinion that backing down would cause, weighted by
    their prestige.  Nothing is at risk above DEFCON 8, as in the original.
    """
    if level >= 8:
        return 0
    gimpt(world, news.actor, news.action, news.target, news.old, news.new, 0)
    shift = (abs(world.crisis.usaImpt) // level
             + abs(world.crisis.ussrImpt) // level + 8 - level)
    total, carried = 0, 0
    for country in world.country[2:]:
        step = shift // 32
        carried += shift % 32
        if carried > 32:
            step, carried = step + 1, carried - 32
        lose = -step
        if country.diplOpinion[loser.id] + lose < -127:
            lose = -127 - country.diplOpinion[loser.id]
        total += lose * country.prestigeVal
    total = max(-8132352, min(8132352, total))
    return -tdiv(total, 1024)


class CrisisDuel:
    """One escalation between two human superpowers."""

    #: The decision phases.
    PHASE_CHALLENGE = "challenge"   # the challenged side decides to contest
    PHASE_ESCALATE = "escalate"     # one of the two decides back down / tough
    PHASE_SUMMIT = "summit"         # the other side accepts or refuses

    #: The verbs open to the decider in each phase.  The window and the network
    #: payload are both driven from this, so a new option needs adding in one
    #: place only.
    CHOICES_CHALLENGE = ("accept", "contest")
    CHOICES_ESCALATE = ("back_down", "tough", "summit")
    CHOICES_SUMMIT = ("yes", "no")

    def __init__(self, world, news):
        self.world = world
        self.news = news
        self.actor = news.actor
        self.challenged = world.country[1 - news.actor.id]
        self.victim = news.target
        self.level = MAX_LEVEL
        self.phase = self.PHASE_CHALLENGE
        self.decider = self.challenged
        self.resolved = False
        self.nuclear = False
        self.accepted = False
        self.reverted = False
        self.outcome = ""
        self.log = []
        #: Who proposed the summit, and the answers so far, by side id.
        self.summit_by = None
        self.summit = {}
        #: Sides that have already used their one summit proposal in this crisis.
        self.summit_used = set()

    # -- description --------------------------------------------------------

    def choices(self):
        """The verbs the current decider may use, or an empty tuple if done."""
        if self.resolved:
            return ()
        if self.phase == self.PHASE_CHALLENGE:
            return self.CHOICES_CHALLENGE
        if self.phase == self.PHASE_SUMMIT:
            return self.CHOICES_SUMMIT
        if self.decider.id in self.summit_used:
            # One proposal per side per crisis: a refused summit may not be
            # re-proposed over and over (each refusal costs the refuser).
            return tuple(c for c in self.CHOICES_ESCALATE if c != "summit")
        return self.CHOICES_ESCALATE

    def _refresh_stakes(self):
        """Recompute what each side stands to win or lose on this headline.

        ``gimpt`` is what fills ``world.crisis.usaImpt/ussrImpt``; reading them
        without calling it first gave whatever the *previous* headline (or an
        advisor's query, or an AI consideration) had left there.
        """
        news = self.news
        gimpt(self.world, news.actor, news.action, news.target, news.old, news.new, 0)

    def prompt(self):
        """A JSON-able description of what the current decider must answer."""
        if self.resolved:
            return None
        self._refresh_stakes()
        return {
            "phase": self.phase,
            "level": self.level,
            "decider": self.decider.id,
            "actor": self.actor.id,
            "challenged": self.challenged.id,
            "victim": self.victim.id,
            "action": self.news.action,
            "old": self.news.old,
            "new": self.news.new,
            "headline": self.news.text,
            "usaRisk": self._risk(0),
            "ussrRisk": self._risk(1),
            "choices": list(self.choices()),
            "summitBy": None if self.summit_by is None else self.summit_by.id,
        }

    def _risk(self, side):
        """0..7 indicator of how much is at stake, mirroring the original."""
        world = self.world
        self._refresh_stakes()
        value = world.crisis.usaImpt if side == 0 else world.crisis.ussrImpt
        span = CRISIS_RISK_SCALE[max(0, min(len(CRISIS_RISK_SCALE) - 1, world.level - 1))]
        index = abs(tdiv(value, span))
        return 7 if index > 7 else index

    def advisors(self, side):
        """Return the four advisor verdicts for one side, as localised strings."""
        from GameLogic.CrisisHandler import getAdvisorOpinion
        reversed_ = (side != self.news.actor.id)
        return [getAdvisorOpinion(self.world, self.news, i + 1, reversed=reversed_)
                for i in range(4)]

    # -- decisions ----------------------------------------------------------

    def decide(self, choice):
        """Apply the current decider's choice; returns True if the duel ended.

        ``choice`` is one of the verbs from :meth:`choices`.  A plain bool is
        still accepted for the two original phases, so callers and saved
        payloads that only knew back-down-or-tough-it-out keep working.
        """
        if self.resolved:
            return True
        verb = self._verb(choice)
        if self.phase == self.PHASE_CHALLENGE:
            self._decide_challenge(verb == "contest")
        elif self.phase == self.PHASE_SUMMIT:
            self._decide_summit(verb == "yes")
        elif verb == "summit":
            if "summit" not in self.choices():
                raise ValueError("a summit has already been proposed by %s" % self.decider.name)
            self._propose_summit()
        else:
            self._decide_escalation(verb == "tough")
        return self.resolved

    def _verb(self, choice):
        """Normalise a bool or a string into one of this phase's verbs."""
        if isinstance(choice, str):
            verb = choice.strip().lower()
            if verb in self.choices() or verb in ("summit", "yes", "no"):
                return verb
            raise ValueError("unknown crisis choice %r" % (choice,))
        if self.phase == self.PHASE_CHALLENGE:
            return "contest" if choice else "accept"
        if self.phase == self.PHASE_SUMMIT:
            return "yes" if choice else "no"
        return "tough" if choice else "back_down"

    def _decide_challenge(self, contest):
        if not contest:
            # The move stands unchallenged.
            self.accepted = True
            self.resolved = True
            self.outcome = "accepted"
            return
        self.phase = self.PHASE_ESCALATE
        self.decider = self.actor
        # CrisisU.p opens the crisis (``IF AggrFlag``) by moving the victim a step
        # towards the side that questioned the move: USA +1, USSR -1.
        changeDMess(self.world, self.victim, 1 if self.challenged.id == 0 else -1)
        self.log.append(("%s contests the move" % self.challenged.name, self.level))

    def _decide_escalation(self, tough):
        if not tough:
            self._back_down(self.decider)
            self.resolved = True
            self.outcome = "backed_down"
            return

        self.level -= 1
        # CrisisU.p HangTough: ``Nastiness := Nastiness + 9 - CrisisLevel`` with the
        # level already stepped down -- a first toughening costs 1, DEFCON 2 costs 7.
        # (This used to be a flat 4 per rung, which is far too much for the early
        # ones and too little for the last.)
        self.world.nastiness = min(127, self.world.nastiness + 9 - self.level)
        # CrisisU.p HangTough also pays out integrity for standing firm over a
        # treaty-protected victim, and sours the superpowers' relations by
        # ``9 - level`` (which is what the accidental-war roll below reads).
        # The two-human duel used to skip both.
        news = self.news
        treaty = self.decider.treaty[self.victim.id]
        stake = impt(self.decider, self.victim, news.action, news.old, news.new)
        self.decider.integrity = max(1, min(127, self.decider.integrity
                                            + tdiv(should(treaty) * stake, 256)))
        changeDiplOpinion(self.world.USA, self.world.USSR, self.level - 9)
        self.log.append(("%s raises the stakes" % self.decider.name, self.level))

        # Accidental launch: only from DEFCON 4 downwards, and only if the two
        # sides already distrust each other.
        if self.level <= 4:
            trust = self.world.USA.diplOpinion[1]
            risk = 0
            if self.level == 2:
                risk = 16
            elif self.level == 3:
                risk = 8
            elif self.level == 4:
                risk = 2
            if trust > 0:
                risk = 0
            else:
                risk = (risk * (-trust)) // 64
            if risk > abs(tdiv(randint(-32768, 32767), 128)):
                self.level = 1
                self.world.ANWFlag = True
                self.log.append(("an accidental launch", self.level))

        if self.level <= 1:
            self.nuclear = True
            self.world.NWFlag = True
            # Set here, not only in finish(): the host broadcasts its state right
            # after the decision and the guest would otherwise keep the old value.
            self.world.nastiness = 127
            self.resolved = True
            self.outcome = "nuclear"
            return
        self.decider = self.actor if self.decider is self.challenged else self.challenged

    # -- the summit ---------------------------------------------------------

    def _propose_summit(self):
        """Open a summit: the proposer's own yes is given, the other side answers.

        Each side may propose once per crisis, and never answers its own
        proposal.  Two yeses (the proposer's and the other side's) hold the
        summit; a refusal is paid for by the refuser alone.
        """
        self.phase = self.PHASE_SUMMIT
        self.summit_by = self.decider
        self.summit_used.add(self.decider.id)
        # Proposing is the proposer's own yes; only the other side answers (the
        # proposer used to be asked to answer their own proposal, and could
        # refuse it, or just be charged for it).
        self.summit = {self.decider.id: True}
        self.log.append(("%s proposes a summit" % self.decider.name, self.level))
        self.decider = self.world.country[1 - self.summit_by.id]

    def _decide_summit(self, agree):
        self.summit[self.decider.id] = bool(agree)
        other = self.world.country[1 - self.decider.id]
        if other.id not in self.summit:
            self.decider = other
            return
        self._resolve_summit()

    def _resolve_summit(self):
        world = self.world
        refusers = [world.country[i] for i in (0, 1) if not self.summit.get(i)]
        if not refusers:
            # Both sides came.  Nothing is given up, and the crisis stands down
            # a rung: this is meant to be the cheaper way out for both of them.
            self.resolved = True
            self.outcome = "summit"
            self.level = min(MAX_LEVEL, self.level + 1)
            world.nastiness = max(1, world.nastiness - SUMMIT_RELIEF_NASTINESS)
            for side in (world.USA, world.USSR):
                side.pugnacity = max(0, side.pugnacity - SUMMIT_RELIEF_PUGNACITY)
            self.log.append(("both sides agree to a summit", self.level))
            return

        # Somebody left the other sitting alone in the room, and pays for it.
        for side in refusers:
            side.integrity = max(1, side.integrity - SUMMIT_REFUSAL_INTEGRITY)
            side.pugnacity = min(127, side.pugnacity + SUMMIT_REFUSAL_PUGNACITY)
            for country in world.country[2:]:
                changeDiplOpinion(country, side, -SUMMIT_REFUSAL_OPINION)
            self.log.append(("%s refuses the summit" % side.name, self.level))
        self.summit = {}
        self.phase = self.PHASE_ESCALATE
        # The decision that was interrupted by the summit proposal is still owed
        # by whoever proposed it.  ``self.actor`` is only right when the proposer
        # happened to be the actor; the deciders alternate every rung.
        self.decider = self.summit_by if self.summit_by is not None else self.actor

    # -- consequences -------------------------------------------------------

    def _back_down(self, loser):
        """``loser`` withdraws; the policy is reverted and prestige changes hands."""
        world = self.world
        winner = self.challenged if loser is self.actor else self.actor
        # The stakes and the loser's weight are read from the headline as it stood
        # when the crisis began.  Reverting the policy first rewrites the headline
        # in place (``addNews`` merges into it, ``new`` becomes ``old``), which
        # zeroed both and made an aggressor's withdrawal cost nothing; and the
        # impact figures were whatever the last query had left behind.
        self._refresh_stakes()
        weight = impt(loser, self.victim, self.news.action, self.news.old, self.news.new)
        if loser is self.actor:
            # The aggressor withdraws: undo the policy entirely.
            self._revert_policy()
        if self.level < 8:
            winner.pugnacity = min(127, winner.pugnacity + (130 - winner.pugnacity) // 4)
            treaty = loser.treaty[self.victim.id]
            loser.integrity -= 2 * tdiv(should(treaty) * weight, 256)
            loser.integrity = max(1, min(127, loser.integrity))
            shift = (abs(world.crisis.usaImpt) // self.level
                     + abs(world.crisis.ussrImpt) // self.level
                     + 8 - self.level)
            # The remainder is accumulated inside the loop (CrisisU.p HangLoose:
            # ``y := y + (x mod 32)`` from y = 0).  Seeding it with the first
            # remainder as well counted that remainder twice.
            base = shift // 32
            carried = 0
            for country in world.country[2:]:
                carried += shift % 32
                step = base
                if carried > 32:
                    step, carried = step + 1, carried - 32
                changeDiplOpinion(country, loser, -step)
                changeDiplOpinion(country, winner, step)
        # The victim drifts into the winner's sphere.
        drift = 9 - self.level
        if drift > self.victim.dMess:
            drift = self.victim.dMess
        if loser.id == 0:
            drift = -drift
        changeDMess(world, self.victim, drift)
        self.log.append(("%s backs down" % loser.name, self.level))

    def _revert_policy(self):
        if self.reverted:
            return
        self.reverted = True
        doPolicy(self.world, self.actor, self.victim, self.news.action,
                 self.news.old, crisis=True)

    def finish(self):
        """Bookkeeping once the duel is over."""
        self.news.crisisVal = True
        if self.nuclear:
            self.world.nastiness = 127
        return self.outcome


class _StubNews(object):
    """A headline reconstructed from a wire payload, for display only.

    The advisor machinery reads ``actor``/``target`` as ``Country`` objects, so
    the stub resolves them against the local mirror of the world.
    """

    def __init__(self, world, payload):
        self.action = payload["action"]
        self.old = payload["old"]
        self.new = payload["new"]
        self.crisisVal = True
        self.actor = world.country[int(payload.get("actor", 0))]
        self.target = world.country[int(payload.get("victim", 0))]
        self.host = self.target


class CrisisPrompt(object):
    """Everything a dialog needs to describe a crisis decision.

    Built either from a local :class:`CrisisDuel` (host and hot-seat) or from a
    payload that arrived over the network (guest), so the same window serves
    both.
    """

    def __init__(self, world, payload, news=None):
        self.world = world
        self.payload = payload
        self.news = news or _StubNews(world, payload)
        self.level = int(payload.get("level", MAX_LEVEL))
        self.phase = payload.get("phase", CrisisDuel.PHASE_CHALLENGE)
        self.headline = payload.get("headline", "")
        self.actor = world.country[int(payload.get("actor", 0))]
        self.challenged = world.country[int(payload.get("challenged", 1))]
        self.decider = world.country[int(payload.get("decider", 1))]
        self.victim = world.country[int(payload.get("victim", 0))]
        by = payload.get("summitBy")
        self.summit_by = world.country[int(by)] if by is not None else None
        # A payload from an older peer carries no choices; derive them from the
        # phase so a mixed-version LAN game still works.
        choices = payload.get("choices")
        if choices:
            self.choices = tuple(choices)
        elif self.is_challenge_phase:
            self.choices = CrisisDuel.CHOICES_CHALLENGE
        elif self.is_summit_phase:
            self.choices = CrisisDuel.CHOICES_SUMMIT
        else:
            self.choices = CrisisDuel.CHOICES_ESCALATE

    @classmethod
    def from_duel(cls, duel):
        return cls(duel.world, duel.prompt(), duel.news)

    # -- display helpers ----------------------------------------------------

    @property
    def is_challenge_phase(self):
        return self.phase == CrisisDuel.PHASE_CHALLENGE

    @property
    def is_summit_phase(self):
        return self.phase == CrisisDuel.PHASE_SUMMIT

    @property
    def proposed_summit(self):
        """True when this side is being asked to answer its own proposal."""
        return self.summit_by is not None and self.summit_by.id == self.decider.id

    def advisors(self):
        from GameLogic.CrisisHandler import getAdvisorOpinion
        reversed_ = self.decider.id != self.news.actor.id
        return [getAdvisorOpinion(self.world, self.news, i + 1, reversed=reversed_)
                for i in range(4)]

    def risk(self, side):
        world = self.world
        # Same as CrisisDuel._risk: the figures must belong to THIS headline.
        news = self.news
        gimpt(world, news.actor, news.action, news.target, news.old, news.new, 0)
        value = world.crisis.usaImpt if side == 0 else world.crisis.ussrImpt
        span = CRISIS_RISK_SCALE[max(0, min(len(CRISIS_RISK_SCALE) - 1, world.level - 1))]
        index = abs(tdiv(int(value), span))
        return 7 if index > 7 else index

    def prestige_at_risk(self):
        """Prestige the deciding side loses by backing down now (0 when none)."""
        if self.is_challenge_phase:
            return 0
        return prestige_at_risk(self.world, self.news, self.decider, self.level)

    def action_label(self):
        import Local
        return Local.strings[Local.LABEL_POLICY][self.news.action]

    def value_change(self):
        import Local
        from GameLogic.News import News
        mode = News.actionToUnitMode[self.news.action]
        return (Local.parseValue(mode, self.news.old),
                Local.parseValue(mode, self.news.new))

    def question_text(self):
        """The label of the forward button — escalate, or accept the summit."""
        import Local
        strings = Local.strings[Local.MULTIPLAYER]
        if self.is_challenge_phase:
            return strings[36]
        if self.is_summit_phase:
            return strings[53]
        buttons = Local.strings[Local.CRISIS_SUPER_BUTTON]
        return buttons[max(0, min(len(buttons) - 1, self.level - 1))]

    def accept_text(self):
        import Local
        return Local.strings[Local.MULTIPLAYER][37]

    def back_down_text(self):
        """The label of the yielding button: let it stand, back down, or refuse."""
        import Local
        if self.is_summit_phase:
            return Local.strings[Local.MULTIPLAYER][54]
        return Local.strings[Local.CRISIS_BD_BUTTON][0]

    def proposal_text(self):
        """The third button: only offered in the escalation phase."""
        import Local
        return Local.strings[Local.MULTIPLAYER][52]

    def summit_note_text(self):
        """One line explaining where the summit stands, or '' if there is none."""
        import Local
        strings = Local.strings[Local.MULTIPLAYER]
        if not self.is_summit_phase:
            return ""
        if self.proposed_summit:
            return strings[56]
        who = Local.strings[Local.DATA_COUNTRIES + self.summit_by.id][Local.CTRY_NAME] \
            if self.summit_by is not None else ""
        return "%s \u2014 %s" % (strings[57], strings[55]) if who else strings[55]

    def context_text(self):
        """One line naming the move, the two sides and the change of level."""
        import Local
        actor = Local.strings[Local.DATA_COUNTRIES + self.actor.id][Local.CTRY_NAME]
        victim = Local.strings[Local.DATA_COUNTRIES + self.victim.id][Local.CTRY_NAME]
        action = Local.strings[Local.LABEL_POLICY][self.news.action]
        try:
            old = Local.parseValue(News.actionToUnitMode[self.news.action], self.news.old)
            new = Local.parseValue(News.actionToUnitMode[self.news.action], self.news.new)
            change = " (%s \u2192 %s)" % (old, new)
        except Exception:
            change = ""
        return "%s: %s against %s%s" % (actor, action, victim, change)

    def title(self):
        import Local
        strings = Local.strings[Local.MULTIPLAYER]
        if self.is_challenge_phase:
            return strings[38]
        if self.is_summit_phase:
            return "%s \u2014 %s" % (strings[61], strings[58])
        return strings[42]
