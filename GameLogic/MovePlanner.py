from .Globals import *
from random import randint
from copy import copy
from constants import *
from constants import LEVEL_LLM, WORLD_EVENT, is_multipolar

def run_computer_move(mainWindow, world):
    """The opposing superpower's turn.

    At the fifth level this is delegated to a language model, which may decline
    (no key, no network, a bad answer) — in which case the ordinary heuristic AI
    plays the turn instead.  The player never loses a turn to a broken API.
    """
    human = world.country[world.human]
    computer = world.country[world.cmptr]
    if world.level == LEVEL_LLM:
        opponent = getattr(mainWindow, "llm_opponent", None)
        if opponent is not None:
            if opponent.take_turn(world, computer, human):
                return
        else:
            mainWindow.setStatus(0)
    compuAI(world, human, computer)


def mainMove(mainWindow, world):
    # Calculate events inside countries
    mainWindow.setStatus(2)
    developCountries(world)
    # Main opponent's move
    if not world.twoPFlag:
        mainWindow.setStatus(0)
        run_computer_move(mainWindow, world)
    # Minor country move if multipolar difficulty is set
    if is_multipolar(world.level):
        mainWindow.setStatus(1)
        minorAI(world)
    # Nastiness decay
    world.nastiness -= 4
    if world.nastiness < 0: world.nastiness = 0
    # Superpower pugnacity, adventuroussness and integrity adjustments
    for c,i in zip(world.country[:2], range(2)):
        c.pugnacity -= 4
        # MainMove has no floor here, but a negative pugnacity is meaningless
        # (the invariant everywhere else is 0..127), so keep it at zero.
        if c.pugnacity < 0: c.pugnacity = 0
        c.adventurousness = c.pugnacity + world.nastiness \
            - world.country[1-i].pugnacity - c.gnpFrac[2] + 32
        if c.adventurousness < 1: c.adventurousness = 1
        c.integrity += 5
        if c.integrity > 127: c.integrity = 127
        c.updateScore(world)
    if world.year == GAME_BASE_YEAR:
        for i in world.country[:2]: i.initScore = i.score
        for i in world.country:
            i.oldGovtStrength = i.govtStrength
            i.oldInsgStrength = i.insgStrength
            i.oldGovtPopul = i.govtPopul
            i.oldFinlProb = copy(i.finlProb)
    # Update scores and history
    mainWindow.setStatus(26)
    for i in world.country[:2]:
        i.oldScore = i.score
        i.historyScore.append(i.score - i.initScore)
    for i in world.country:
        i.history.update()    
        

def continueNextTurn(mainWindow, world):
    """
    This part of the turn is executed at the end of the turn after all crises
    have been resolved and all policies have been made.
    """
    #TODO do policies
    if world.twoPFlag:
        mainWindow.controlPanel.nextTurnButton.setEnabled(False)
    # The turn's headlines are answered (or ignored) by now, so they are dropped
    # before the new year's are generated -- except the historical events that
    # ``prePlanMove`` filed for this year.  Wiping those as well meant the player
    # never saw a single one in the News window.
    events = [n for n in world.news if n.action == WORLD_EVENT]
    world.news.clear()
    world.news.extend(events)
    # A finished game is not played on (the autosave/refresh below still runs).
    if not world.winFlag:
        if world.year > GAME_BASE_YEAR:
            for i in world.country[2:]:
                # Minor country diplomatic and policy-wise adjustments towards the superpowers.
                for s in world.country[:2]:
                    minorRej(world, world.level, i, s)
                    # Main.p ReactNews: ``25*((256*Econ) div GNP) div (GPopular+1)``.
                    # (The port used to divide the product, which keeps a fraction the
                    # original throws away.)  GNP is never below 1.
                    x = tdiv(25 * tdiv(256 * econConv(s.econAid[i.id]), max(1, i.GNP)), i.govtPopul + 1) \
                                - 32 * s.destab[i.id]                                           \
                                + tdiv(s.govtAid[i.id] * i.milPressure, 8)                      \
                                - (12 * s.insgAid[i.id])                                        \
                                + tdiv(s.govtIntv[i.id] * i.milPressure, 4)                     \
                                - (64 * s.insgIntv[i.id])                                       \
                                - (16 * s.pressure[i.id])                                       \
                                + tdiv(tdiv(s.treaty[i.id] * s.integrity, 128) * i.milPressure, 8)
                    x = tdiv(x, 8)
                    # ``ChgDipAff(i,j,x)`` with i the minor country: the read side is
                    # the minor's own row, which is what the score sums.
                    changeDiplOpinion(i, s, x)
                # If playing on multipolar level, make adjustments towards other minor countries, too
                if is_multipolar(world.level):
                    # Minor countries only (``FOR j:=3 TO NoCntry``).  The loop used
                    # to run over all eighty, so each superpower's opinion got a
                    # second, partial contribution on top of the full formula above.
                    for j in world.country[2:]:
                        x = tdiv(j.govtAid[i.id] * i.milPressure, 8)                       \
                                    - (12 * j.insgAid[i.id])                               \
                                    + tdiv(j.govtIntv[i.id] * i.milPressure, 4)            \
                                    - (64 * j.insgIntv[i.id])
                        x = tdiv(x, 8)
                        changeDiplOpinion(i, j, x)
        # Pascal's NextTurn runs the whole of MainMove -- AI move, development, score
        # and history -- and only THEN checks the year (``IF Year=1997 THEN WinFlag``).
        # Skipping it on the last year left the final year unsimulated, the score one
        # turn stale and ``historyScore`` one entry short.
        mainMove(mainWindow, world)
        if world.year == GAME_END_YEAR:
            world.winFlag = True
            mainWindow.endGame()
    if not world.twoPFlag: mainWindow.controlPanel.nextTurnButton.setEnabled(True)
    mainWindow.controlPanel.drawScores()
    if not world.winFlag: mainWindow.setStatus(-1)
    mainWindow.controlPanel.yearLabel.setText(str(world.year))
    mainWindow.mapView.scene().mapPainter.recalculateMapBuffer()
    mainWindow.mapView.resetMapView()
    # Autosave on beginning of the turn
    if mainWindow.menu.options[0].isChecked():
        mainWindow.saveWorld()
    # End-of-turn hook.  One-player games reach this function straight from
    # ``reactNews`` while two-player games go through MainWindow.finish_turn;
    # routing the window's own bookkeeping (undo point, network broadcast, UI
    # refresh) through here means both paths get it exactly once.
    on_completed = getattr(mainWindow, "on_turn_completed", None)
    if on_completed is not None:
        on_completed()

#: Error in the tension estimate at intelligence level 0, in nastiness units.
ESTIMATE_ERROR_BASE = 34
#: How much each intelligence level removes from that error.
ESTIMATE_ERROR_STEP = 6
#: Never better than this, however much is spent.
ESTIMATE_ERROR_FLOOR = 3


def estimate_error(level):
    return max(ESTIMATE_ERROR_FLOOR, ESTIMATE_ERROR_BASE - ESTIMATE_ERROR_STEP * level)


def updateEstimates(world):
    """Refresh each side's *belief* about tension and the opponent.

    The player never sees ``world.nastiness`` any more; the DEFCON indicator and
    the advisors work from these numbers.  Intelligence narrows the error, which
    is what makes it worth paying for.
    """
    for side in (0, 1):
        error = estimate_error(world.intel[side])
        belief = world.nastiness + randint(-error, error)
        world.knownNastiness[side] = max(0, min(127, belief))
        opponent = world.country[1 - side]
        belief = opponent.pugnacity + randint(-error, error)
        world.knownPugnacity[side] = max(0, min(127, belief))


def prePlanMove(world):
    """Preparations made on the beginning of the turn."""
    world.year += 1
    # The historical event deck fires here, so both players meet the new year
    # with the same news on the table.
    from GameLogic.HistoricalEvents import apply_events
    # Last year's event headlines have been seen; only this year's stay on file
    # (``continueNextTurn`` keeps them through its news clear).
    world.news[:] = [n for n in world.news if n.action != WORLD_EVENT]
    headlines = apply_events(world)
    world.lastEvent = headlines[-1] if headlines else ""
    updateEstimates(world)
    for c in world.country:
        c.oldGovtStrength, c.oldInsgStrength, c.oldGovtPopul = c.govtStrength, c.insgStrength, c.govtPopul
        c.oldGovtAid = c.govtAid.copy()
        c.oldInsgAid = c.insgAid.copy()
        c.oldGovtIntv = c.govtIntv.copy()
        c.oldInsgIntv = c.insgIntv.copy()
        if c.id < 2:
            c.oldEconAid = c.econAid.copy()
            c.oldDestab = c.destab.copy()
            c.oldTreaty = c.treaty.copy()
            c.oldPressure = c.pressure.copy()
            c.oldTrade = c.trade.copy()
        for i in range(2):
            c.revlGain[i] = c.coupGain[i] = c.finlGain[i] = 0
            c.oldFinlProb[i] = c.finlProb[i]
        if c.govtStrength == 0: c.govtStrength = 1
        if c.insgStrength > c.govtStrength: c.insgStrength = c.govtStrength
        tmp = c.insgStrength
        x = (6400 * tmp) // c.govtStrength
        if x < 1: x = 1
        if x > 6400: x = 6400
        tmp = x
        c.sqrtStrength = int(sqrt(tmp))

        # Check for USA-USSR direct combat
        if((world.USA.govtIntv[c.id] > 0 and world.USSR.insgIntv[c.id] > 0)
            or (world.USA.insgIntv[c.id] > 0 and world.USSR.govtIntv[c.id] > 0)):
            world.USA.diplOpinion[1] = world.USSR.diplOpinion[0] = -127
            world.nastiness = 127
            world.USA.pugnacity = world.USSR.pugnacity = 127
        
        # Check for minor country direct combat
        if is_multipolar(world.level):
            for j in world.country[2:]:
                if c.govtIntv[j.id] > 0:
                    for k in world.country:
                        if k.insgIntv[j.id] > 0:
                            changeDiplOpinion(k, c, -tdiv(world.nastiness, 8))
                            changeDiplOpinion(c, k, -tdiv(world.nastiness, 8))
                if c.insgIntv[j.id] > 0:
                    for k in world.country:
                        if k.govtIntv[j.id] > 0:
                            changeDiplOpinion(k, c, -tdiv(world.nastiness, 8))
                            changeDiplOpinion(c, k, -tdiv(world.nastiness, 8))
                
def minorRej(world, level, i, superpower):
    """Check if minor country i can break some ties with the given superpower"""
    x = superpower.diplOpinion[i.id] + 2 * superpower.pugnacity
    # break treaty
    value = treatyMax(level, x + superpower.integrity)
    treatz = superpower.treaty[i.id]
    if value < treatz:
        world.addNews(i, superpower, i, 7, treatz, value, True)
        treatz = value
    # refuse intervention
    intvGovtz, value = superpower.govtIntv[i.id], intvGovtMax(level, treatz, x)
    if value < intvGovtz:
        superpower.totalIntv += (-intvConv(intvGovtz) + intvConv(value))
        world.addNews(superpower, i, i, 4, intvGovtz, value, True)
        superpower.govtIntv[i.id] = value
    # refuse economic aid
    value = econAidMax(x)
    if superpower.econAid[i.id] > value:
        world.addNews(superpower, i, i, 1, superpower.econAid[i.id], value, True)
        superpower.econAid[i.id] = value
    # refuse military aid
    miltAidz, value = superpower.govtAid[i.id], govtAidMax(x)
    if value < miltAidz:
        i.totalGovtAid += (-mAidConv(miltAidz) + mAidConv(value))
        superpower.totalGovtAid += (mAidConv(miltAidz) - mAidConv(value))
        world.addNews(superpower, i, i, 2, miltAidz, value, True)
        superpower.govtAid[i.id] = value
    # scale back trade agreements the country no longer wants
    tradez = superpower.trade[i.id]
    value = tradeMax(level, x + superpower.integrity)
    if value < tradez:
        # Same shape as the other refusals: the superpower is the actor and the
        # minor country the object, so this renders as a policy headline.
        world.addNews(superpower, i, i, 8, tradez, value, True)
        superpower.trade[i.id] = value
    superpower.treaty[i.id] = treatz 

def arf1(who, superpower):
    tmp = intvConv(superpower.govtIntv[who])
    return (tmp * superpower.milPower) // superpower.milMen

def arf2(who, superpower):
    tmp = intvConv(superpower.insgIntv[who])
    return (tmp * superpower.milPower) // superpower.milMen

def doRevolution(world, c):
    """Triggers revolution major event in teh country c"""
    c.hasRevolution = True
    c.generateNewLeader()
    d = c.govtWing
    c.govtWing = c.insgWing
    c.insgWing = d
    if world.USA.insgIntv[c.id] + world.USSR.insgIntv[c.id] > 0:
        if world.USA.insgIntv[c.id] > world.USSR.insgIntv[c.id]:
            c.govtWing = tdiv(world.USA.govtWing + c.govtWing, 2)
        else: c.govtWing = tdiv(world.USSR.govtWing + c.govtWing, 2)
    c.govtPopul = 10 + (128 - abs(c.govtWing)) // 8
    c.govtStrength, c.insgStrength = c.insgStrength, 1
    c.insgPower, c.strengthRatio = 1, c.govtStrength // c.insgStrength
    old, new = c.revolutionNewsValues()
    world.addNews(c, c, c, 1, old, new, False)
    # Pascal sets ``GovtAid[i] := 0`` here, which also wipes what the country
    # itself gives out; the ledger is rebuilt from the arrays after the swap
    # below instead (deliberate deviation, see Globals.recalcTotals).
    for k in world.country:
        if k == c: continue
        if k.id < 2:
            superpower = k
            otherSuperpower = world.country[1 - k.id]
            x = 128 - should(superpower.treaty[c.id])
            superpower.integrity = (superpower.integrity * x) // 128
            # A revolution against a level-5 treaty multiplies credibility by
            # zero, and the floor of 1 that every other path applies was missing
            # here: the superpower ended up with 0 credibility and stayed there.
            if superpower.integrity < 1: superpower.integrity = 1
            x = c.insgWing - superpower.govtWing
            y = c.govtWing - superpower.govtWing
            # PlanMove.p Revolution: the ideological term is |insurgents| - |new
            # government| (it was a sum, which can never be negative), and the
            # OTHER superpower's aid counts against, not for.
            x = tdiv(abs(x) - abs(y), 2)
            x += 8 * (superpower.insgAid[c.id] + 2 * superpower.insgIntv[c.id]              \
                - superpower.govtAid[c.id] - 2 * superpower.govtIntv[c.id])
            x -= 8 * (otherSuperpower.insgAid[c.id] + 2 * otherSuperpower.insgIntv[c.id]    \
                    - otherSuperpower.govtAid[c.id] - 2 * otherSuperpower.govtIntv[c.id])
            if x > 127: x = 127
            elif x < -127: x = -127
            #revl gain
            # A new government repudiates the old one's dealings with the
            # superpower that backed it: treaties, aid and trade all lapse.
            superpower.treaty[c.id] = superpower.econAid[c.id] = 0
            superpower.trade[c.id] = 0
        else: x = 8 * (k.insgAid[c.id] + 2 * k.insgIntv[c.id] - k.govtAid[c.id] - 2 * k.govtIntv[c.id])
        if x > 127: x = 127
        elif x < -127: x = -127
        c.diplOpinion[k.id] = k.diplOpinion[c.id] = x
        x = k.govtAid[c.id]
        k.govtAid[c.id] = k.insgAid[c.id]
        k.insgAid[c.id] = x
        x = k.govtIntv[c.id]
        k.govtIntv[c.id] = k.insgIntv[c.id]
        k.insgIntv[c.id] = x
        if k.id < 2:
            for j in range(5):
                if intvGovtMax(world.level, j, k.diplOpinion[c.id]) < k.govtIntv[c.id]:
                    k.treaty[c.id] = j + 1
    recalcTotals(world)

def doFinlandize(world, c):
    """Triggers finlandization major event in teh country c"""
    if world.level < 3: return
    y = c.milPower - c.insgPower
    for superpower in world.country[:2]:
        otherSuperpower = world.country[1 - superpower.id]
        x = intvInsgMax(world, superpower, c);
        superpower.powerProjection = (intvConv(x) * superpower.milPower) // superpower.milMen
        x = otherSuperpower.treaty[c.id]
        x = (should(x) * otherSuperpower.milPower) // 128
        superpower.selfPower = y + (x * otherSuperpower.integrity) // 128
        if superpower.selfPower < 1: superpower.selfPower = 1
        tmp = tdiv((superpower.adventurousness - superpower.diplOpinion[c.id]) * superpower.powerProjection \
            * (superpower.pressure[c.id] + 4), superpower.selfPower)
        if tmp < 0: tmp = 0
        elif tmp > 2048: tmp = 2048
        c.finlProb[superpower.id] = tmp // 8
    x,y = c.finlProb
    # Finlandize
    if x > 127 or y > 127:
        if x > y: superpower, otherSuperpower = world.USA, world.USSR
        else: superpower, otherSuperpower = world.USSR, world.USA
        c.hasFinland[superpower.id] = True
        c.govtWing += tdiv(superpower.govtWing - c.govtWing, 4)
        if c.govtWing * c.insgWing > 0: c.insgWing = -c.govtWing
        c.finlGain[superpower.id] = (32 * c.prestigeVal) // 1024
        c.finlGain[otherSuperpower.id] = tdiv(-32 * c.prestigeVal, 1024)
        changeDiplOpinion(c, superpower, 32)
        changeDiplOpinion(c, otherSuperpower, -32)
        world.addNews(c, superpower, c, 0, 0, 0, True)
        # Recalculate finlandization probabilities
        for s in world.country[:2]:
            # Everything here is the loop's own superpower ``s`` (PlanMove.p
            # DoFiniz, second loop); the winner's pressure, self-power and slot
            # used to be written into both entries.
            tmp = tdiv((s.adventurousness - s.diplOpinion[c.id]) * s.powerProjection \
                * (s.pressure[c.id] + 4), s.selfPower)
            if tmp < 0: tmp = 0
            elif tmp > 2048: tmp = 2048
            c.finlProb[s.id] = tmp // 16

def developCountries(world):
    """
    Calculate internal parameters (military power, economy, population) and check
    for major events inside countries.
    """
    for c in world.country:
        c.hasFinland = [False, False]
        c.hasCoup = c.hasRevolution = False
        c.localNewsAtWarWith = None
        c.localNewsSurrender = None
        x = c.milMen
        tmp = (c.gnpSpnd[2] + c.totalGovtAid) // 2
        if tmp < 1: tmp = 1
        y = arf1(c.id, world.USA) + arf1(c.id, world.USSR)
        c.milPower = ((4 * tmp * x) // (tmp + x)) + y

        # Minor country war fighting
        if c.id > 1 and is_multipolar(world.level):
            for target in world.country[2:]:
                if c.diplOpinion[target.id] == -127:
                    c.milPower -= (target.milPower // 4)
                    c.GNP -= (target.milPower // 4)
                    if c.GNP < 1: c.GNP = 1
                    # Surrender
                    if c.milPower < 1:
                        for k in range(len(world.country)):
                            c.diplOpinion[k] = (-120 if target.diplOpinion[k] <= -127 else target.diplOpinion[k])
                        c.govtWing, c.insgWing = target.govtWing, -target.govtWing
                        # Headline (6, 2, 1) as in PlanMove.p.  When the victor
                        # was handled earlier this turn its "fight to the
                        # death" line is withdrawn so the two don't contradict.
                        if c.id > target.id:
                            world.news[:] = [n for n in world.news
                                             if not (n.actor is target and n.target is c
                                                     and n.action == 6
                                                     and n.old == 1 and n.new == 1)]
                        world.addNews(c, target, c, 6, 2, 1, False)
                        c.localNewsSurrender = target
                        c.localNewsAtWarWith = None
                        c.diplOpinion[target.id] = target.diplOpinion[c.id] = 0
                        c.diplOpinion[c.id] = 127
                    # War continues
                    else:
                        c.localNewsAtWarWith = target
                        world.addNews(c, target, c, 6, 1, 1, True)
                        # The enemy hates us back (``DipAff[j,i] := -127``); the
                        # port wrote the already-true ``c -> target`` slot.
                        target.diplOpinion[c.id] = -127

        # Check if revolution might happen
        x = ((((256 - c.maturity) * c.population // 256) * c.sqrtStrength) // 80)
        tmp = sum([2 * mAidConv(k.insgAid[c.id]) for k in world.country])
        if tmp < (x // 8) + 1: tmp = (x // 8) + 1
        y = arf2(c.id, world.USA) + arf2(c.id, world.USSR)
        c.insgPower = ((4 * tmp * x) // (tmp + x)) + y
        if c.id < 2: c.insgPower = 1
        c.milPower -= (c.insgPower // 4)
        if c.milPower < 1: c.milPower = 1
        c.insgPower -= (c.milPower // 4)
        if c.insgPower < 1: c.insgPower = 1
        c.govtStrength, c.insgStrength = c.milPower, c.insgPower
        c.strengthRatio = c.govtStrength // c.insgStrength
        if c.insgStrength == 1 and c.govtStrength < 8192: c.strengthRatio *= 4
        if c.strengthRatio < 1: doRevolution(world, c)

        # Economic adjustments
        consPressure, invtPressure = (20 - c.govtPopul) * 10, (80 - c.gnpFrac[1]) * 2
        if consPressure < 1: consPressure = 1
        if invtPressure < 1: invtPressure = 1
        c.milPressure = c.sqrtStrength + sum(c.finlProb)
        if c.milPressure < 1: c.milPressure = 1
        _sum, pot = consPressure + invtPressure + c.milPressure, 0
        for i in range(3):
            if c.gnpFrac[i] > 16:
                c.gnpFrac[i] -= 8
                pot += 8
        c.gnpFrac[1] += ((invtPressure * pot) // _sum)
        c.gnpFrac[2] += ((c.milPressure * pot) // _sum)
        c.gnpFrac[0] = 255 - c.gnpFrac[1] - c.gnpFrac[2]
        oldConsSpend = (c.gnpSpnd[0] * 255) // c.population
        x = econConv(world.USA.econAid[c.id]) + econConv(world.USSR.econAid[c.id])
        pseudoGNP = c.GNP + x
        tmp = pseudoGNP * 2 * (c.gnpFrac[1] - 30)
        c.GNP += tdiv(tmp, 1000)
        pseudoGNP = c.GNP + x
        x = 30 - (oldConsSpend // 40)
        if x < 1: x = 1
        
        # Population growth
        tmp = c.population * x
        if tmp < 1000: tmp = 1000
        c.population += (tmp // 1000)
        c.milMen = (c.population * c.draftFrac) // 256
        for i in range(2): c.gnpSpnd[i] = (c.gnpFrac[i] * pseudoGNP) // 256
        # PlanMove.p: ``IF InvtSpnd[i]<1 THEN InvtSpnd[i]:=1`` -- the *spending*, not
        # the fraction (the port tested gnpFrac, a different quantity, so the
        # floor never did what it was written for).
        if c.gnpSpnd[1] < 1: c.gnpSpnd[1] = 1
        c.gnpSpnd[2] = (pseudoGNP - c.gnpSpnd[1] - c.gnpSpnd[0]) * 10
        if c.gnpSpnd[2] < 1: c.gnpSpnd[2] = 1
        if c.GNP < 1: c.GNP = 1

        # Fix negative available resource bug
        if c.id < 2:
            x = (c.gnpSpnd[2] // 8) + c.totalGovtAid
            while x < 0 and c.gnpFrac[0] > 0:
                c.gnpFrac[0] -= 1
                c.gnpFrac[2] += 1
                c.gnpSpnd[0] = (c.gnpFrac[0] * pseudoGNP) // 256
                # PlanMove.p: MiltSpnd := (PseudGNP - ConsSpnd - InvtSpnd) * 10.
                # This used the *fractions* (0-255) where the *spending* belongs,
                # which inflated the military budget about fivefold.
                c.gnpSpnd[2] = (pseudoGNP - c.gnpSpnd[0] - c.gnpSpnd[1]) * 10
                x = (c.gnpSpnd[2] // 8) + c.totalGovtAid
        
        # Changes in govt popularity
        tmp = (c.gnpFrac[0] * pseudoGNP) // c.population
        delta = tdiv((tmp - oldConsSpend) * 100, oldConsSpend + 1)
        tmp = delta + (abs(c.govtWing) // 64) - 3
        c.govtPopul += tmp
        # PlanMove.p only floors popularity (``IF GPopular[i]<0``); there is no
        # ceiling of 20 for minor countries, only the superpowers' forced 20.
        if c.govtPopul < 0: c.govtPopul = 0
        if c.id < 2: c.govtPopul = 20 # Superpower govts have always 100% approval rate
        # Check for coup d'etat
        if (c.govtPopul <= world.USA.destab[c.id] + world.USSR.destab[c.id] and world.level > 1):
            c.hasCoup = True
            c.generateNewLeader()
            x = c.govtWing
            c.govtWing = c.insgWing
            c.insgWing = x
            c.govtPopul = 10 + (128 - abs(c.govtWing)) // 8
            c.govtStrength -= (c.govtStrength // 8)
            old, new = c.coupNewsValues()
            world.addNews(c, c, c, 2, old, new, False)
            for s in world.country[:2]:
                x = should(s.treaty[c.id]) - (c.maturity // 2)
                if x > 128: x = 128
                elif x < 0: x = 0
                s.integrity = (s.integrity * (128 - x)) // 128
                if s.integrity < 1: s.integrity = 1
                x, y = c.insgWing - s.govtWing, c.govtWing - s.govtWing
                x = tdiv(abs(x) - abs(y), 2)
                c.coupGain[s.id] = tdiv(x * c.prestigeVal, 1024)
                changeDiplOpinion(c, s, x)
                minorRej(world, world.level, c, s)
        c.random = randint(-32767,32767)
        x = (6400 * c.insgStrength) // c.govtStrength
        if x < 1: x = 1
        elif x > 6400: x = 6400
        tmp = x
        c.sqrtStrength = int(sqrt(tmp))
        if c.id > 1: doFinlandize(world, c)
        for s in world.country[:2]: s.pressure[c.id] = s.destab[c.id] = 0
        for j in world.country:
            x, y = insgAidMax(world, j, c), intvInsgMax(world, j, c)
            # The ceiling lowers the policy; the donor gets the money / men back.
            # (The original, and this port until now, clamped without crediting
            # the donor, so its ledger drifted: see Globals.recalcTotals.)
            if j.insgAid[c.id] > x:
                j.totalGovtAid += mAidConv(j.insgAid[c.id]) - mAidConv(x)
                j.insgAid[c.id] = x
            if j.insgIntv[c.id] > y:
                j.totalIntv -= intvConv(j.insgIntv[c.id]) - intvConv(y)
                j.insgIntv[c.id] = y
            if j.id < 2: minorRej(world, world.level, c, j)
        c.generateLocalNews()
        
def compuAI(world, human, computer):
    """The built-in superpower AI.  Also sets its own intelligence budget."""
    # A frightened superpower spends more on finding out what is going on.
    # Written without max()/min() on purpose: this function assigns to a local
    # named ``max`` further down, which shadows the builtin for the whole body.
    level = world.nastiness // 26
    if level > 5: level = 5
    if level < 0: level = 0
    world.intel[computer.id] = level
    """
    Main superpower AI routine. Both human and computer arguments
    have to be Superpower objects.

    """
    policies = maxPolicy(computer)
    maxIntv, maxAid, maxEcon = policies[0], policies[1], 5
    _sum = sum([econConv(i) for i in computer.econAid])
    y = (computer.GNP // 44) - 2 * _sum
    for i in range(4, -1, -1):
        if econConv(i + 1) > y: maxEcon = i
    # Enact policies towards minor countries
    for c in world.country[2:]:
        humanFinlProb = c.finlProb[human.id]
        dAij = computer.diplOpinion[c.id]
        obligation = dAij + should(computer.treaty[c.id]) - human.diplOpinion[c.id]
        if obligation < 0: obligation = tdiv(obligation * world.nastiness, 32)
        if obligation > 128: obligation = 128
        if obligation == 0: obligation = 1
        for k in range(9):
            # Trade policy is a Multipolar-level verb only.
            if k == TRADE and TRADE not in AVL_ACTIONS[world.level - 1]:
                continue
            # economic aid
            if k == ECONAID:
                need, max, old = tdiv(22 - c.govtPopul, 3), econAidMax(dAij), computer.econAid[c.id]
                if need < 0: need = 0
                if max > maxEcon: max = maxEcon
                if world.level == 1: need = 0
            # military aid
            elif k == GOVTAID:
                need, max, old = (c.sqrtStrength + humanFinlProb) // 8, govtAidMax(dAij), computer.govtAid[c.id]
                if max > maxAid: max = maxAid
            # insurgency aid
            elif k == INSGAID:
                need, max, old = -10, insgAidMax(world, computer, c), computer.insgAid[c.id]
                if max > maxAid: max = maxAid
                y = insgStrengthMax(c.strengthRatio)
                if y < max: max = y
            # intervene for govt
            elif k == GOVTINTV:
                need, max, old = (c.sqrtStrength + humanFinlProb) // 8, intvGovtMax(world.level, computer.treaty[c.id], dAij),\
                    computer.govtIntv[c.id]
                _sum = 0
                # ``FOR i:=3 TO NoCntry``: neighbours that are minor countries.
                # Looping over all eighty counted the human superpower as one.
                for i in world.country[2:]:
                    if c.id != i.id and i.contig[c.id] and not i.contig[computer.id] and computer.diplOpinion[i.id] < 0:
                        _sum += (128 - computer.diplOpinion[i.id])
                need += (_sum // 64)
                if max > maxIntv: max = maxIntv
            # intervene for insurgents
            elif k == INGSINTV:
                old, new, max = computer.insgIntv[c.id], 0, 5
                if dAij < ((world.nastiness // 2) - 64):
                    max = intvInsgMax(world, computer, c)
                    powerProjection = (intvConv(max) * computer.milPower) // computer.milMen
                    if max > maxIntv: max = maxIntv
                    if powerProjection > c.milPower:
                        new = max
                        x = gimpt(world, computer, INGSINTV, c, old, new, 0)
                        if x > tdiv(randint(-32768, 32767), 1024): new = old
            # diplomatic pressure
            elif k == PRESSURE:
                x = -tdiv(144 - c.finlProb[computer.id], 16)
                if x > 0 or x < -5: x = 0
                need, max, old = x, 5, 0
                if world.level < 3: need = 0
            # treaty
            elif k == TREATY:
                old = computer.treaty[c.id]
                x = 1 + (humanFinlProb // 16) - (c.sqrtStrength // 24) - tdiv(20 - c.govtPopul, 8)
                if x < 0: x = 0
                if world.level < 3: x = 0
                need = old + x
                max = treatyMax(world.level, computer.integrity + dAij - computer.pugnacity)
                if max < old: max = old
            # trade policy (Multipolar only) — a diplomatic statement, so the
            # AI pursues it where it already has goodwill and a weak client.
            elif k == TRADE:
                old = computer.trade[c.id]
                x = 1 + (humanFinlProb // 24) - (c.sqrtStrength // 32) - tdiv(20 - c.govtPopul, 10)
                if x < 0: x = 0
                need = old + x
                max = tradeMax(world.level, computer.integrity + dAij - computer.pugnacity)
                if max < old: max = old
            # destabilization
            elif k == DESTAB:
                need, max, old = tdiv(c.govtPopul - 20, 2), 5, computer.destab[c.id]
                if need > 0 or c.govtPopul > 5: need = 0
                if world.level == 1: need = 0
            # continue k-loop
            if k != INGSINTV:
                if k not in (TREATY, TRADE, PRESSURE, GOVTINTV):
                    need = tdiv(need * obligation, 128)
                if need > max: need = max
                elif need < 0: need = 0
                new = need
                if new > old:
                    while gimpt(world, computer, k, c, old, new, 0) > abs(tdiv(randint(-32768, 32767), 512)) and new > old:
                        new -= 1
            # Persistent statecraft is never downgraded voluntarily.
            if new < old and k in (TREATY, TRADE): new = old
            if new != old:
                doPolicy(world, computer, c, k, new)
                policies = maxPolicy(computer)
                maxIntv, maxAid = policies


def minorAI(world):
    """
    Minor country AI routine. Does all the considerations for every in-game minor country.
    """
    weightArray = []
    for c in world.country[2:]:
        weightArray.clear()
        infl = influence(world.USA, c) - influence(world.USSR, c)
        for k in world.country:
            if c.id != k.id and c.minorSphere[k.id] and c.diplOpinion[k.id] != -127:
                # Zero out all policies
                for policy, i in zip([c.govtAid, c.insgAid, c.govtIntv, c.insgIntv], range(2,6)):
                    if policy[k.id] > 0: doPolicy(world, c, k, i, 0)
        strengthRatio = c.strengthRatio
        for k in world.country[2:]:
            if c.diplOpinion[k.id] == -127:
                strengthRatio = 0
                break
        resourceFrac = getMaxLevel((64,128,256,512), strengthRatio) * 10
        # explore foreign policy options
        if resourceFrac > 0:
            resourceFrac += ((world.USA.adventurousness + world.USSR.adventurousness + world.nastiness) // 8)
            for k in world.country[2:]:
                if not c.minorSphere[k.id] or k == c: continue
                # PlanMove.p: LongSum -= DipAff[k',j] * DipAff[i,k'] over every
                # country k' -- how the others regard the target, weighted by how
                # the actor regards them.  The indices were transposed.
                _sum = sum([-(j.diplOpinion[k.id] * c.diplOpinion[j.id]) for j in world.country])
                weight = abs(tdiv(c.diplOpinion[k.id] * _sum, 16383))
                x = k.dMess - world.avgDMess
                weight += (x * infl)
                if weight < 1: weight = 1
                weightArray.append({"id": k, "weight": weight})
        # sort all possible country-targets by their importance to the actor
        # Heaviest first (the original's insertion sort keeps WeightArr descending,
        # so the biggest targets are served before the resources run out).
        weightArray = sorted(weightArray, key=lambda k: k['weight'], reverse=True)
        _sum = sum([i["weight"] for i in weightArray])
        # iterate through possibilities
        for i in weightArray:
            who, weight = i["id"], i["weight"]
            # calculate how many weapons can be sent
            weapons = ((weight - 1) * resourceFrac * c.gnpSpnd[2]) // (_sum * 100)
            newWeapons = getMaxLevel((1,5,20,50,100), weapons)
            maxStuff = getMaxLevel((256,128,64,16,4), who.strengthRatio, lt=True)
            # calculate how many troops can be sent
            troops = ((weight - 1) * resourceFrac * c.milMen) // (_sum * 100)
            newTroops = getMaxLevel((1,5,20,50,100), troops)

            # positive relationship - help the government
            if c.diplOpinion[who.id] > 0:
                tmp = govtAidMax(who.diplOpinion[c.id])
                if tmp > maxStuff: tmp = maxStuff
                if newWeapons > tmp: newWeapons = tmp
                doPolicy(world, c, who, GOVTAID, newWeapons)
                tmp = intvGovtMax(world.level, 5, who.diplOpinion[c.id])
                if tmp > maxStuff: tmp = maxStuff
                if newTroops > tmp: newTroops = tmp
                doPolicy(world, c, who, GOVTINTV, newTroops)
            # negative relationship - help the insurgents
            else:
                tmp = insgAidMax(world, c, who)
                if tmp > maxStuff: tmp = maxStuff
                if newWeapons > tmp: newWeapons = tmp
                doPolicy(world, c, who, INSGAID, newWeapons)
                tmp = intvInsgMax(world, c, who)
                if tmp > maxStuff: tmp = maxStuff
                if newTroops > tmp: newTroops = tmp
                doPolicy(world, c, who, INGSINTV, newTroops)
