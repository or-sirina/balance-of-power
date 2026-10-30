from math import sqrt
from constants import *

def tdiv(a, b):
    """Integer division that truncates toward zero, like Pascal's ``div``.

    Python's ``//`` floors, which differs for negative operands (-7 // 2 is -4,
    Pascal's -7 div 2 is -3).  Every site that mirrors a Pascal ``div`` whose
    operand can be negative goes through here.  Note the precedence trap this
    also avoids: Pascal's ``-A div B`` is ``-(A div B)`` whereas Python's
    ``-A // B`` is ``(-A) // B``; write ``-tdiv(A, B)``.
    """
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def econConv(val):
    return (0,1,2,5,10,20)[val]

def mAidConv(val):
    return (0,1,5,20,50,100)[val]

def intvConv(val):
    return (0,1,5,20,100,500)[val]

def getMaxLevel(tresholds, x, **kwargs):
    t = 0
    if "lt" in kwargs and kwargs["lt"]:
        for i in range(len(tresholds)):
            if x < tresholds[i]: t += 1
    else:
        for i in range(len(tresholds)):
            if x > tresholds[i]: t += 1
    return t 

def milMax(x):
    """Maximum level of military aid for the government"""
    return getMaxLevel((-40,-20,0,20,40), x)

def intvGovtMax(level, x, dipl):
    """Maximum level of intervention for the government"""
    # For Advanced or Multipolar level maximum level is determined
    # by the type of treaty signed with the target
    if level >= 3:
        if x == 3: return 2
        elif x == 4: return 4
        elif x == 5: return 5
        else: return 0
    # On the easier levels, return the value based on the diplomatic opinion
    else:
        return getMaxLevel((0,20,40,60,80), dipl)

def intvInsgMax(world, superpower, country):
    """Maximum level of insurgency intervention"""
    y = 2
    # If superpower and country are contiguous - always maximum level
    if superpower.contig[country.id]: return 5
    # If not - the maximum level depends on the troops relocated in the
    # neighboring countries.  ``k.id``, not ``country.id``: the ceiling comes
    # from the aid the *neighbour* gives its own government, which is what
    # ``InsgIMax`` reads in the original (``IntvGovt[SuprPowr,i]`` inside its
    # ``i`` loop) and what the sibling ``insgAidMax`` reads here.  Reading the
    # target's own slot gave every country without a staging area the same
    # number, so the rule did nothing at all.
    for k in world.country[2:]:
        if k.contig[country.id]:
            x = superpower.govtIntv[k.id]
            if x < 5: x += 1
            if x > y: y = x
    return y

#: Ceiling on aid to insurgents imposed by the war's own balance: you cannot
#: arm a rebellion that is already being beaten.  These are the thresholds
#: ``CompuAI`` uses in the original (``StrngRat`` in PlanMove.p: under 128 gives
#: step 1, under 64 step 2, under 32 step 3, under 8 step 4, under 2 step 5).
#: Both sides read this one table; the player's dialog used to use a laxer set
#: of its own, which let the player arm insurgents the computer could not.
INSG_STRENGTH_THRESHOLDS = (128, 64, 32, 8, 2)

#: The player's own dialog (Main.p ``SetPolicy``) uses a laxer set than CompuAI:
#: under 512 gives step 1, under 128 step 2, under 32 step 3, under 8 step 4,
#: under 2 step 5.  The original really has two tables; this one is the human's.
INSG_STRENGTH_THRESHOLDS_HUMAN = (512, 128, 32, 8, 2)


def insgStrengthMax(ratio, human=False):
    """Highest step of aid to insurgents this government/insurgency ratio allows.

    ``human=True`` selects the table the original's policy dialog uses; the
    default is the one the computer's AI reads.
    """
    table = INSG_STRENGTH_THRESHOLDS_HUMAN if human else INSG_STRENGTH_THRESHOLDS
    return getMaxLevel(table, ratio, lt=True)


def treatyMax(level, x):
    """Maximum level of treaty"""
    if level < 3: return 5
    return getMaxLevel((-60,0,40,60,100), x)

def tradeMax(level, x):
    """
    Maximum level of the trade policy.

    Trade is a purely diplomatic verb (1990 Edition, Multipolar level only) and
    is gated the same way as a treaty: a country will not deepen commercial ties
    with a superpower it distrusts.  The original manual only states the effect
    ("make a diplomatic statement that will affect relations"), so the ceiling
    is modelled on the treaty rule.
    """
    return getMaxLevel((-60,0,40,60,100), x)

def econAidMax(x):
    """Maximum level of economic aid"""
    return getMaxLevel((-60,-40,-20,0,20), x)

def govtAidMax(x):
    """Maximum level of government military aid"""
    return getMaxLevel((-40,-20,0,20,40), x)

def insgAidMax(world, superpower, minorpower):
    """Maximum level of insurgency aid"""
    max = 1
    # If superpower and country are contiguous - always maximum level
    if superpower.contig[minorpower.id]: return 5
    # If not - the maximum level depends on the troops relocated
    # in the neighboring countries
    for k in world.country[2:]:
        if k.contig[minorpower.id]:
            x = superpower.govtIntv[k.id]
            if x < 5: x += 1
            if x > max: max = x
    return max

#: mAidConv units charged per intelligence level, per year.
INTEL_COST_PER_LEVEL = 8


def intel_cost(country):
    """What this superpower is paying for intelligence this year.

    Charged from the same pool as military aid, so a player who wants to know
    what the other side is thinking has to give up something to find out.
    """
    if country.id > 1:
        return 0
    world = getattr(country, "parent", None)
    if world is None:
        return 0
    levels = getattr(world, "intel", None)
    if not levels:
        return 0
    return levels[country.id] * INTEL_COST_PER_LEVEL


def maxPolicy(giver):
    maxPolicies = [5, 5]
    sumIntv = giver.totalIntv
    sumAid = giver.totalGovtAid - intel_cost(giver)
    men = giver.milMen
    spnd = giver.gnpSpnd[2]
    for i in range(4, -1, -1):
        if mAidConv(i + 1) > ((spnd // 8) + sumAid): maxPolicies[1] = i
        if intvConv(i + 1) > ((men // 4) - sumIntv): maxPolicies[0] = i
    return maxPolicies

def recalcTotals(world):
    """Rebuild every country's aid and troop ledgers from the policy arrays.

    ``totalGovtAid`` is what a country receives in military aid minus what it
    gives out (to governments and to insurgents); ``totalIntv`` is the troops it
    has committed abroad.  ``doPolicy`` keeps them in step one change at a time.

    DELIBERATE DEVIATION FROM THE ORIGINAL: Pascal's ``Revolution`` zeroes the
    country's ledger and the end-of-turn ceilings on insurgent aid/intervention
    clamp the array without crediting the donor, so in the original the ledgers
    drift away from the arrays over a game (the donor is quietly charged for aid
    it no longer gives).  Here they are restored to the sum of the arrays
    whenever one of those paths touches them.
    """
    countries = world.country
    n = len(countries)
    received = [0] * n
    for donor in countries:
        for j in range(n):
            received[j] += mAidConv(donor.govtAid[j])
    for c in countries:
        c.totalGovtAid = received[c.id] - sum(
            mAidConv(c.govtAid[j]) + mAidConv(c.insgAid[j]) for j in range(n))
        c.totalIntv = sum(
            intvConv(c.govtIntv[j]) + intvConv(c.insgIntv[j]) for j in range(n))


def should(treaty):
    """How much obligation the given level of treaty creates"""
    return (0, 16, 32, 64, 96, 128)[treaty]

def changeDiplOpinion(i, j, delta):
    """Change diplomatic opinion between i and j by delta"""
    x = i.diplOpinion[j.id] + delta
    if x > 127: x = 127
    if x < -127: x = -127
    i.diplOpinion[j.id] = j.diplOpinion[i.id] = x

def changeDMess(world, c, howMuch):
    """Change sphere of influence of c by howMuch"""
    c.dMess += howMuch
    world.sumDMess += howMuch
    if world.sumDMess < 1: world.sumDMess = 1
    # NOTE: this used to assign to ``world.avdDMess`` (a typo), which created a
    # brand-new attribute and left ``avgDMess`` frozen at its start-of-game
    # value.  Every sphere-of-influence calculation reads ``avgDMess``, so the
    # typo quietly disabled the "who is winning the Third World" feedback loop.
    #
    # Kept integral (as ``World.newGame`` computes it) and clamped to at least
    # one: ``getSphOfInfluence`` divides by it and uses the result as a list
    # index, so a float or a zero here is a crash waiting to happen.
    world.avgDMess = max(1, world.sumDMess // len(world.country))

def influence(s, c):
    """Get influence paramter of the superpower 's' over country 'c'"""
    x = s.treaty[c.id]\
        + s.econAid[c.id]\
        + s.govtAid[c.id]\
        + s.trade[c.id]\
        + 2 * s.govtIntv[c.id]\
        - 2 * s.destab[c.id]\
        - 2 * s.insgAid[c.id]\
        - 4 * s.insgIntv[c.id]
    return (0 if x < 0 else x)

def hurt(target, action, old, new):
    x = 0
    if action == DESTAB:
        x = 16 * (new - old)
    elif action == ECONAID:
        x = -tdiv(tdiv(1024 * (econConv(new) - econConv(old)), target.GNP), target.govtPopul + 1)
    elif action == GOVTAID:
        x = tdiv((old - new) * target.milPressure, 4)
    elif action == INSGAID:
        x = 12 * (new - old)
    elif action == GOVTINTV:
        x = tdiv((old - new) * target.milPressure, 2)
    elif action == INGSINTV:
        x = 25 * (new - old)
    elif action == PRESSURE:
        x = 8 * new
    elif action == TREATY:
        x = tdiv((old - new) * target.milPressure, 4)
    elif action == TRADE:
        # Trade carries no resources, so its only weight is diplomatic, and the
        # 1990 manual calls it "a diplomatic statement" rather than a transfer.
        x = tdiv((old - new) * target.milPressure, 8)
    if action in (1,2,4,7,8) and x == 0: x = old - new
    if x > 127: x = 127
    if x < -127: x = -127
    return x

def impt(toWhom, target, action, old, new):
    """Get importance for 'toWhom' for the given international policy change"""
    return tdiv(hurt(target, action, old, new) * toWhom.diplOpinion[target.id], 128)

def gimpt(world, actor, action, target, old, new, bias):
    maxLongVal = 134144000
    for s in world.country[:2]:
        x = tdiv(s.diplOpinion[target.id], 4)
        if x == 0: x = 1
        y = (should(s.treaty[target.id]) // 4) + 1   # operand is never negative
        z = tdiv(target.dMess * 1280, world.sumDMess)
        if z > 32: z = 32
        if z < 1: z = 1
        if s.id == 1: z = 33 - z
        t = s.adventurousness // 2
        if t > 32: t = 32
        if t < 1: t = 1
        v = hurt(target, action, old, new)
        if ((actor.id == 1 - s.id) and action in (2, 4, 7) and s.diplOpinion[target.id] > 0):
            v = -v
        if bias == 1:
            x, y = x * int(sqrt(abs(x))), int(sqrt(y))
        elif bias == 2:
            y, z = y * int(sqrt(y)), int(sqrt(z))
        elif bias == 3:
            z, t = z * int(sqrt(z)), int(sqrt(t))
        elif bias == 4:
            t *= int(sqrt(t))
            x = int(sqrt(x)) if x > 0 else - int(sqrt(abs(x)))
        lx = tdiv(z * x * y * t * v, 64) * target.prestigeVal
        if s.id == 0: ly = lx
        else: lz = lx
        if lx > maxLongVal: lx = maxLongVal
        if lx < -maxLongVal: lx = -maxLongVal
        lx = tdiv(lx, 4096)
        if s.id == 0: world.crisis.usaImpt = lx
        else: world.crisis.ussrImpt = lx
    lx = ly + lz
    if lx > maxLongVal: lx = maxLongVal
    elif lx < -maxLongVal: lx = -maxLongVal
    return tdiv(lx, 4096)

def doPolicy(world, actor, target, action, new, **kwargs):
    """
    Enact a policy and calculate effects on available resources for the actor if applicable.
    This function does not calculate the effects of the given policy.

    """
    if actor.id < 2:
        policies = (actor.destab, actor.econAid, actor.govtAid,
            actor.insgAid, actor.govtIntv, actor.insgIntv, actor.pressure, actor.treaty,
            actor.trade)
    else: policies = (None, None, actor.govtAid, actor.insgAid, actor.govtIntv, actor.insgIntv,
        None, None, None)
    # Defensive: a verb this actor has no table for (a minor country "raising its
    # treaty level", a revolution headline treated as a policy, a historical
    # event) used to die here with a TypeError / IndexError in the middle of a
    # crisis.  Nothing to enact, so nothing happens.
    if not (0 <= action < len(policies)) or policies[action] is None:
        return
    old = policies[action][target.id]
    policies[action][target.id] = new
    if kwargs.get("crisis") is True:
        # A move undone by a crisis is back where it started: move the Close-Up's
        # start-of-year snapshot with it, or it shows an arrow for a change that
        # no longer exists.  The snapshots are display-only.
        snapshot = getattr(actor, ("oldDestab", "oldEconAid", "oldGovtAid", "oldInsgAid",
                                   "oldGovtIntv", "oldInsgIntv", "oldPressure", "oldTreaty",
                                   "oldTrade")[action], None)
        if snapshot is not None:
            snapshot[target.id] = new
    if action == 2:
        target.totalGovtAid = target.totalGovtAid - mAidConv(old) + mAidConv(new)
        actor.totalGovtAid = actor.totalGovtAid + mAidConv(old) - mAidConv(new)
    elif action == 3:
        actor.totalGovtAid = actor.totalGovtAid + mAidConv(old) - mAidConv(new)
    elif action in (4,5):
        actor.totalIntv = actor.totalIntv - intvConv(old) + intvConv(new)
    if old != new or actor.id == world.human:
        crisis = kwargs["crisis"] if "crisis" in kwargs else old > new
        world.addNews(actor, target, target, action, old, new, crisis)