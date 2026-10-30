"""What a superpower may do with one policy verb towards one country.

One pure function (no Qt) that the policy dialog, the Close-Up bracket and the
LAN host all read, so they cannot disagree.  The rules are Main.p ``SetPolicy``:

* a step may be *raised* only up to a ceiling made of several limits (the target's
  goodwill, treaty level, staging areas, the budget, the troops left);
* the step already held can always be kept, and any step below it taken (the
  original enables every control from step 0 up to the held one);
* treaty and trade can only be deepened, never lowered.

Only economic aid credits the amount already given back into the budget (the
original's ``EconConv(OldCntrl)`` term); military aid and both interventions need
the full cost of the new step free, exactly as in Main.p.
"""
from GameLogic.Globals import (econConv, mAidConv, intvConv, econAidMax, milMax,
                               insgAidMax, insgStrengthMax, intvGovtMax,
                               intvInsgMax, treatyMax, tradeMax, tdiv)
from constants import (DESTAB, ECONAID, GOVTAID, INSGAID, GOVTINTV, INGSINTV,
                       PRESSURE, TREATY, TRADE, AVL_ACTIONS)

#: Unit mode of the step labels (``Local.parseValue``) per verb.
UNIT_MODES = {DESTAB: 3, ECONAID: 2, GOVTAID: 0, INSGAID: 0, GOVTINTV: 1,
              INGSINTV: 1, PRESSURE: 4, TREATY: 5, TRADE: 16}


def _table(actor, verb):
    return {DESTAB: actor.destab, ECONAID: actor.econAid, GOVTAID: actor.govtAid,
            INSGAID: actor.insgAid, GOVTINTV: actor.govtIntv,
            INGSINTV: actor.insgIntv, PRESSURE: actor.pressure,
            TREATY: actor.treaty, TRADE: actor.trade}[verb]


class PolicyInfo(object):
    """Result of :func:`policy_info`."""

    def __init__(self, verb, old, mode):
        self.verb, self.old, self.mode = verb, old, mode
        #: (highest step this limit allows, why it stops there)
        self.limits = []
        #: The number shown as "Available" in the dialog (None for diplomatic verbs).
        self.avail = None
        #: Treaty/trade: steps below this cannot be taken.
        self.floor = 0

    def add(self, value, why):
        self.limits.append((max(0, min(5, value)), why))

    @property
    def ceiling(self):
        """Highest step one may *raise* to (the dialog's ``previewCeiling``)."""
        c = min([v for v, _ in self.limits] or [5])
        if self.verb in (TREATY, TRADE) and c < self.old:
            c = self.old
        return c

    def reason_for(self, step):
        """Why ``step`` cannot be chosen, or "" if it can."""
        if step in self.steps():
            return ""
        if step < self.floor:
            return "A treaty or trade level cannot be lowered."
        for value, why in self.limits:
            if step > value:
                return why
        return ""

    @property
    def reason(self):
        """Why the ceiling is where it is (the tightest limit), or ""."""
        if self.ceiling >= 5:
            return ""
        for value, why in self.limits:
            if value <= self.ceiling:
                return why
        return ""

    def steps(self):
        """Every step that may be chosen (raise, keep or lower)."""
        top = max(self.ceiling, self.old)
        return [i for i in range(self.floor, top + 1)]


def policy_info(world, actor, verb, target):
    """Compute the limits of ``verb`` from ``actor`` towards ``target``."""
    mode = UNIT_MODES[verb]
    old = _table(actor, verb)[target.id]
    info = PolicyInfo(verb, old, mode)
    x = actor.diplOpinion[target.id]
    held_note = ""
    if verb == ECONAID:
        info.add(econAidMax(x), "Their government won't accept more economic aid "
                 "(not enough goodwill).")
        # Main.p SetPolicy: sum over the minor countries; a step is allowed while
        # its cost does not exceed half of what is left plus what is already
        # being given here.
        total = sum([econConv(i) for i in actor.econAid[2:]])
        avl = (actor.GNP // 44) - (2 * total)
        info.avail = avl
        top = 5
        for i in range(4, -1, -1):
            if econConv(i + 1) > (tdiv(avl, 2) + econConv(old)): top = i
        info.add(top, "Not enough economic aid budget for a higher step.")
    elif verb == GOVTAID:
        info.add(milMax(x), "Their government won't accept more military aid "
                 "(not enough goodwill).")
        avl = actor.getAvailableAid()
        info.avail = avl
        top = 5
        for i in range(4, -1, -1):
            if mAidConv(i + 1) * 2 > avl: top = i
        info.add(top, "Not enough military aid budget: a higher step needs its "
                 "full cost free, the aid already given is not counted.")
    elif verb == INSGAID:
        # The player's table (Main.p SetPolicy), laxer than CompuAI's.
        info.add(insgStrengthMax(target.strengthRatio, human=True),
                 "The insurgents are too weak to be worth arming.")
        info.add(insgAidMax(world, actor, target),
                 "No staging area: you need troops in a neighbouring country "
                 "to arm these insurgents further.")
        avl = actor.getAvailableAid()
        info.avail = avl
        top = 5
        for i in range(4, -1, -1):
            if mAidConv(i + 1) * 2 > avl: top = i
        info.add(top, "Not enough military aid budget: a higher step needs its "
                 "full cost free, the aid already given is not counted.")
    elif verb == GOVTINTV:
        info.add(intvGovtMax(world.level, actor.treaty[target.id], x),
                 "Treaty level too low for more troops." if world.level >= 3
                 else "Their government won't accept more troops.")
        avl = actor.getAvailableMen()
        info.avail = avl
        top = 5
        for i in range(4, -1, -1):
            if intvConv(i + 1) > avl: top = i
        info.add(top, "Not enough troops left (%s thousand free); a higher step "
                 "needs its full number free." % max(0, avl))
    elif verb == INGSINTV:
        info.add(intvInsgMax(world, actor, target),
                 "No staging area: you need troops in a neighbouring country "
                 "to send more troops for the rebels.")
        avl = actor.getAvailableMen()
        info.avail = avl
        top = 5
        for i in range(4, -1, -1):
            if intvConv(i + 1) > avl: top = i
        info.add(top, "Not enough troops left (%s thousand free); a higher step "
                 "needs its full number free." % max(0, avl))
    elif verb == TREATY:
        info.add(treatyMax(world.level, actor.integrity + x - actor.pugnacity),
                 "Their government won't accept a closer treaty (not enough goodwill).")
        info.floor = old
    elif verb == TRADE:
        info.add(tradeMax(world.level, actor.integrity + x - actor.pugnacity),
                 "Their government won't accept closer trade (not enough goodwill).")
        info.floor = old
    return info


def allowed_steps(world, actor, verb, target):
    """The steps ``actor`` may set for ``verb`` towards ``target`` (list of int)."""
    return policy_info(world, actor, verb, target).steps()


def check_request(world, actor, verb, target_id, value):
    """Validate a policy request from a remote player: ``(ok, reason)``."""
    if not isinstance(verb, int) or verb not in AVL_ACTIONS[min(world.level, 5) - 1]:
        return False, "verb %r is not available at this level" % (verb,)
    if actor.id not in (0, 1):
        return False, "only a superpower sets policy"
    if not (2 <= target_id < len(world.country)):
        return False, "target %r is not a minor country" % (target_id,)
    info = policy_info(world, actor, verb, world.country[target_id])
    if value not in info.steps():
        return False, ("step %d of verb %d towards country %d is not allowed "
                       "(allowed %s)" % (value, verb, target_id, info.steps()))
    return True, ""
