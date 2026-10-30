from GameLogic.Globals import *
from constants import CRISIS_RISK_SCALE
from GameLogic.MovePlanner import continueNextTurn
from random import randint
import Local
from constants import WORLD_EVENT

def getAdvisorOpinion(world, news, bias, **kwargs):
    """
    Get advisor opinion whether the news should be a matter of international escalation
    or not. bias is an integer between 1 and 4 - represents different advisor's opinion.
    """
    if "reversed" in kwargs and kwargs["reversed"]: factor = -1
    else: factor = 1
    x = factor * gimpt(world, news.actor, news.action, news.target, news.old, news.new, bias)
    x = tdiv(x, 8)
    x += 1
    if x < -15: x = -15
    elif x > 16: x = 16
    # ``x`` runs from -15 (the move is a disaster for us) to +16 (we can walk it
    # back at will), and ADVISORY is a 32-entry table running from "they will
    # ream us on this one" to "nuke 'em".  Indexing it with ``x - 1`` threw the
    # whole scale away: negative indexes wrap in Python, so the cautious end of
    # the table came back as the most belligerent advice in it, neutrality came
    # back as "Nuke 'em!", and every advisor whose judgement landed in the same
    # range said the same wrong thing.  The offset is the table's own zero.
    return Local.strings[Local.ADVISORY][x + 15]

def reactNews(mainWindow, world):
    """Superpower AI decides which policies it reacts to"""
    # A model-backed opponent gets to make this judgement itself.  It is the one
    # place where the computer chooses whether to *open* a confrontation rather
    # than merely how to fight one, and a decision model is unusually good at it:
    # it weighs the stake, the risk of the ladder, and whether the human looks
    # like someone who will fold.
    _llm_judge_provocations(mainWindow, world)

    for n in world.news:
        # Revolutions, coups, wars and the like are headlines about a country's
        # own affairs (actor is target).  ReactNews skips them
        # (``IF Subject[i]<>Object[i]``); they must never be "questioned".
        if n.actor is n.target:
            continue
        if n.action in (INGSINTV,INSGAID,DESTAB,PRESSURE) and n.actor.id < 2:
            world.nastiness += (n.new - n.old)
            if world.nastiness < 1: world.nastiness = 1
            elif world.nastiness > 127: world.nastiness = 127
        # Computer-human crisis
        if n.actor.id == world.human and n.new > n.old and not world.twoPFlag and not n.crisisVal:
            if n.isQuestioned:
                continue          # already decided (by the model, above)
            x = -gimpt(world, n.actor, n.action, n.target, n.old, n.new, 0)
            y,z = world.crisis.usaImpt, world.crisis.ussrImpt
            if world.cmptr == 0: z = y
            if z < 0: x = 256
            n.isQuestioned = (x < abs(tdiv(randint(-32768, 32767), 1024)))
        # Computer questions minor countries
        elif n.actor.id > 1 and n.new > n.old and not world.twoPFlag \
            and influence(world.country[world.cmptr], n.actor) > 3:
            x = -gimpt(world, n.actor, n.action, n.target, n.old, n.new, 0)
            y,z = world.crisis.usaImpt, world.crisis.ussrImpt
            if world.cmptr == 0: z = y
            if z > abs(tdiv(randint(-32768, 32767), 1024)): computerCrisis(world, n)
        
    # Begin process of questioning by the computer
    for n in world.news:
        if n.isQuestioned:
            world.beingQuestioned = True
            mainWindow.newsWindow.showUp()
            #doCrisis(mainWindow.newsWindow, world, n)
            return
    continueNextTurn(mainWindow, world)

def _note(mainWindow, text):
    """Record a line in the opponent log, if this window has one.

    Headless harnesses drive ``reactNews`` with a stub window, so a missing
    logger must not be fatal.
    """
    logger = getattr(mainWindow, "llm_note", None)
    if logger is not None:
        logger(text)


def _record_human_resolve(mainWindow, stood_firm):
    """Remember how the human resolved a crisis, for the model to read.

    A decision model judging whether to contest the *next* move ought to know
    whether this player folds or stands.  Without it every crisis is judged in
    isolation and the opponent never learns anything about the person it is
    playing - which is exactly the "trading" behaviour the level is meant to
    show.
    """
    opponent = getattr(mainWindow, "llm_opponent", None)
    record = getattr(opponent, "human_record", None) if opponent is not None else None
    if not record:
        return
    record["stood_firm" if stood_firm else "backed_down"] += 1


def _llm_judge_provocations(mainWindow, world):
    """Let the model opponent decide which of the human's moves to contest.

    Falls back silently to the original heuristic whenever there is no model
    opponent, the model is unreachable, or it returns nothing usable — the
    original behaviour is the floor, not the target.
    """
    opponent = getattr(mainWindow, "llm_opponent", None)
    if opponent is None or world.twoPFlag:
        return
    candidates = []
    for n in world.news:
        if n.actor.id != world.human or n.new <= n.old or n.crisisVal:
            continue
        if n.isQuestioned:
            continue
        # ``gimpt`` is what fills in the crisis stake tables the model is shown,
        # so the same call the heuristic makes has to happen either way.
        stake = gimpt(world, n.actor, n.action, n.target, n.old, n.new, 0)
        value = world.crisis.usaImpt if world.cmptr == 0 else world.crisis.ussrImpt
        candidates.append((n, value))
    if not candidates:
        return
    try:
        verdicts = opponent.verdicts(world, world.country[world.cmptr],
                                     world.country[world.human], candidates)
    except Exception as exc:                      # network, schema, budget
        _note(mainWindow, "The opponent could not judge your moves; "
                         "the built-in AI decided instead. (%s)" % exc)
        return
    if not verdicts:
        return
    lines = []
    for news, _stake in candidates:
        verdict = verdicts.get(news)
        if verdict is None:
            continue
        escalate, described = verdict
        news.isQuestioned = bool(escalate)
        if escalate:
            lines.append("%s in %s: %s"
                         % (Local.strings[Local.LABEL_POLICY][news.action],
                            Local.strings[Local.DATA_COUNTRIES + news.target.id][Local.CTRY_NAME],
                            described))
    if lines:
        _note(mainWindow, "Contested moves: " + "; ".join(lines))


def hangLoose(newsWindow, world, loser, winner, victim):
    """
    `loser` backs down in the crisis between superpowers.
    Both `loser` and `winner` are assumed to be Superpower objects,
    whereas `victim` is a Country object.
    """
    crisis = world.crisis
    n = crisis.whichHead
    n.isQuestioned = False
    if crisis.level < 8:
        # No penalty for early withdrawal
        winner.pugnacity += ((130 - winner.pugnacity) // 4)
        x = loser.treaty[victim.id]
        t = impt(loser, victim, n.action, n.old, n.new)
        loser.integrity -= 2 * tdiv(should(x) * t, 256)
        if loser.integrity < 1: loser.integrity = 1
        elif loser.integrity > 127: loser.integrity = 127
        y = gimpt(world, crisis.who, n.action, n.target,
            n.old, n.new, 0)
        t,z = crisis.usaImpt, crisis.ussrImpt
        x,y = (abs(t) // crisis.level) + (abs(z) // crisis.level) + 8 - crisis.level, 0
        for c in world.country[2:]:
            z,y = x // 32, y + x % 32
            if y > 32: z, y = z + 1, y - 32
            changeDiplOpinion(c, loser, -z)
            changeDiplOpinion(c, winner, z)
    if crisis.level % 2 == 1:
        x = n.new
        n.new = n.old
        n.old = x
        n.crisisVal = True
        # An odd rung is the actor's own turn to concede, whoever the actor is
        # (CrisisU.p HangLoose: ``IF odd(CrisisLevel) ... DoPolicy(Who,...)``).
        # This used to revert only the computer's moves, so a human who backed
        # down on the first rung kept the very policy they had just conceded.
        doPolicy(world, n.actor, n.target, n.action, n.new, crisis=True)
    else: n.crisisVal = True
    x = 9 - crisis.level
    if x > victim.dMess: x = victim.dMess
    if loser.id == 0: x = -x
    changeDMess(world, victim, x)
    newsWindow.reactionLine.setText(Local.generateReactionLine(loser, crisis.level, False, True))
    newsWindow.question.setEnabled(False)
    newsWindow.backDown.setText(Local.strings[Local.CRISIS_BD_BUTTON][1])

def hangTough(newsWindow, world, actor):
    """
    `actor` toughens the crisis between the two superpowers.
    `actor` is a participant in the crisis, thus a Superpower object.
    """
    crisis = world.crisis
    n = crisis.whichHead
    victim = crisis.victim
    crisis.level -= 1
    if crisis.level < 7:
        newsWindow.setWindowTitle(Local.strings[Local.CRISIS_FILTER][21 if crisis.level < 5 else 20])
    x = actor.treaty[victim.id]
    y = impt(actor, victim, n.action, n.old, n.new)
    actor.integrity += tdiv(should(x) * y, 256)
    if actor.integrity < 1: actor.integrity = 1
    elif actor.integrity > 127: actor.integrity = 127
    changeDiplOpinion(world.country[world.cmptr], world.country[world.human], crisis.level - 9)
    x = 0
    if crisis.level == 2: x = 16
    elif crisis.level == 3: x = 8
    elif crisis.level == 4: x = 2
    if world.USA.diplOpinion[1] > 0: x = 0
    else: x = (x * (-world.USA.diplOpinion[1])) // 64
    y = tdiv(randint(-32768, 32767), 128)
    # Accidental nuclear war has been triggered - end of the game
    if x > abs(y): crisis.level, world.ANWFlag = 1, True
    world.nastiness += 9 - crisis.level
    if world.nastiness > 127: world.nastiness = 127
    # End of the game, nuclear war has been ignited
    if crisis.level == 1:
        world.NWFlag = True
        # A deliberate war has an author; an accidental launch has none (the
        # end-of-game text uses this to say who actually pulled the trigger).
        if not world.ANWFlag: world.warStarter = actor.id
        newsWindow.reactionLine.setText("")
        newsWindow.setVisible(False)
        world.beingQuestioned = False
        #world.quitFlag = True
        newsWindow.parent.endGame()
    newsWindow.reactionLine.setText(Local.generateReactionLine(actor, crisis.level, False, False))

#: Policies a minor country can carry out (CompuAI/MinorAI: military aid, aid to
#: insurgents, intervention for either side).  Every other verb has no policy
#: table for a minor actor.
_MINOR_POLICIES = (GOVTAID, INSGAID, GOVTINTV, INGSINTV)


def crisisEligible(news):
    """Can this headline possibly be turned into a crisis?

    A crisis ends by re-enacting the old value with :func:`doPolicy`, so the
    headline has to be a policy somebody actually has: not a revolution, a coup,
    a war or surrender, a finlandization, or a historical event (those are
    about a country's own affairs, or have no policy table at all - ``doPolicy``
    on one raised TypeError), and a minor country has only four of the nine.
    """
    actor, target, action = news.actor, news.target, news.action
    if actor is target or action == WORLD_EVENT or not (0 <= action <= 8):
        return False
    if actor.id > 1 and action not in _MINOR_POLICIES:
        return False
    return True


def canQuestion(world, news):
    """May the human press "Question" on this headline?  (Globals.p ``Headline``.)

    The original enables the button for exactly two cases: the computer
    superpower's own move, which is not directed at itself and has not been
    settled yet; or a minor country's increase (never one aimed at itself) when
    the human has more than a little influence there.  Anything else - the
    human's own moves, revolutions, surrenders, events - is not a crisis.
    """
    if news.crisisVal or news.new <= news.old or not crisisEligible(news):
        return False
    actor = news.actor
    if actor.id < 2:
        return actor.id == world.cmptr
    return influence(world.country[world.human], actor) > 3


def _open_crisis_panel(newsWindow, world, headline):
    """Put the opening state of a crisis on screen (title, buttons, advisers)."""
    c = world.crisis
    newsWindow.setWindowTitle(Local.strings[Local.CRISIS_FILTER][19])
    newsWindow.reactionLine.setText(Local.generateReactionLine(
        world.country[1-c.who.id], c.level, False, False))
    newsWindow.backDown.setEnabled(True)
    newsWindow.backDown.setText(Local.strings[Local.CRISIS_BD_BUTTON][0])
    newsWindow.question.setEnabled(True)
    newsWindow.setLocked(True)
    if c.who.id == world.human:
        # Create advisory panel
        for i in range(4):
            newsWindow.advice[i].setText(getAdvisorOpinion(world, headline, i + 1, reversed=True))
            newsWindow.picture[i].setVisible(True)
        newsWindow.newsHline.setText(headline.text)
        newsWindow.setVisible(True)


def _show_penalties(newsWindow, world, headline):
    """The "prestige at risk" block and the label of the Question button."""
    c = world.crisis
    if not c.backDown and c.level > 1:
        c.sumLoser = c.sumWinner = 0
        # CrisisU.p computes the penalty sums only below DEFCON 8 ("no penalty
        # for early withdrawal"); above it both stay zero and so does the display.
        if c.level < 8:
            c.hloss = gimpt(world, c.who, headline.action, c.victim, headline.old, headline.new, 0)
            c.y, c.z = c.usaImpt, c.ussrImpt
            c.x = (abs(c.y) // c.level) + (abs(c.z) // c.level) + 8 - c.level
            c.y = 0
            # Calculate the penalty
            for i in world.country[2:]:
                c.Usez, c.y = c.x // 32, c.y + c.x % 32
                if c.y > 32: c.Usez, c.y = c.Usez + 1, c.y - 32
                c.Usex = -c.Usez
                c.daow = i.diplOpinion[world.cmptr]
                c.daol = i.diplOpinion[world.human]
                if c.daol + c.Usex > 127: c.Usex = 127 - c.daol
                if c.daol + c.Usex < -127: c.Usex = -127 - c.daol
                if c.daow + c.Usez > 127: c.Usez = 127 - c.daow
                if c.daow + c.Usez < -127: c.Usez = -127 - c.daow
                c.sumWinner += (c.Usez * i.prestigeVal)
                c.sumLoser += (c.Usex * i.prestigeVal)
            if c.sumLoser > 8132352: c.sumLoser =  8132352
            elif c.sumLoser < -8132352: c.sumLoser = -8132352
        c.hloss, c.cgain = -tdiv(c.sumLoser, 1024), -tdiv(c.sumWinner, 1024)
        # Prestige at risk
        newsWindow.setRiskValuesVisible(True)
        newsWindow.leftInfoVal[0].setText(str(c.hloss))
        c.y = CRISIS_RISK_SCALE[world.level - 1]
        c.x = gimpt(world, c.who, headline.action, c.victim, headline.old, headline.new, 0)
        c.hloss, c.cgain = c.usaImpt, c.ussrImpt
        c.x = abs(tdiv(c.hloss + tdiv(c.rand1, c.y), 16))
        if c.x > 7: c.x = 7
        newsWindow.leftInfoVal[1].setText(Local.strings[Local.CRISIS_RISK][c.x])
        c.x = abs(tdiv(c.cgain + tdiv(c.rand2, c.y), 16))
        if c.x > 7: c.x = 7
        newsWindow.leftInfoVal[2].setText(Local.strings[Local.CRISIS_RISK][c.x])
    newsWindow.question.setText(Local.strings[Local.CRISIS_SUPER_BUTTON][c.level-1])


def resumeCrisis(newsWindow, world):
    """Redraw a crisis that was already under way when the window was lost.

    A saved game (or a closed-and-reopened window) can hold a crisis with
    ``hasBegun`` set.  ``doCrisis`` skips its opening on such a crisis -- which
    is right for the next rung -- so the panel stayed blank with the Back Down
    button dead; and calling it again would let the computer move a second time.
    This restores the display only; nobody moves.
    """
    c = world.crisis
    headline = c.whichHead
    if headline is None:
        return False
    if c.who.id < 2:
        _open_crisis_panel(newsWindow, world, headline)
        if c.level < 7:
            newsWindow.setWindowTitle(Local.strings[Local.CRISIS_FILTER][21 if c.level < 5 else 20])
        _show_penalties(newsWindow, world, headline)
    else:
        newsWindow.setWindowTitle(Local.strings[Local.CRISIS_FILTER][19])
        newsWindow.newsHline.setText(headline.text)
        newsWindow.backDown.setEnabled(True)
        newsWindow.backDown.setText(Local.strings[Local.CRISIS_BD_BUTTON][0])
        newsWindow.question.setEnabled(c.level > 1)
        newsWindow.setLocked(True)
        newsWindow.reactionLine.setText(Local.generateReactionLine(c.who, c.level, True, False))
        newsWindow.question.setText(Local.strings[Local.CRISIS_MINOR_BUTTON][max(0, c.level - 1)])
    newsWindow.setVisible(True)
    return True


def doCrisis(newsWindow, world, headline):
    """Main human vs superpower AI crisis routine"""
    c = world.crisis
    if not crisisEligible(headline):
        # Never start a crisis over a headline that has no policy to revert.
        headline.isQuestioned = False
        return
    if not c.hasBegun:
        c.resetCrisisData()
        c.hasBegun, c.whichHead, c.who = True, headline, headline.actor
        c.victim, c.level, c.backDown = headline.target, 9, False
        c.rand1, c.rand2 = randint(-32767,32767), randint(-32767,32767)
        c.aggrFlag = c.who.id == world.cmptr
        if c.aggrFlag:
            c.x = 1 if world.human == 0 else -1     # USA +1, USSR -1 (Init: IF Human=1 THEN x:=1)
            changeDMess(world, c.victim, c.x)
        _open_crisis_panel(newsWindow, world, headline)

    # Computer considerations
    if c.aggrFlag and not world.twoPFlag:
        c.x = gimpt(world, c.who, headline.action, c.victim, headline.old, headline.new, 0)
        c.hloss, c.cgain = c.usaImpt, c.ussrImpt
        if c.who.id == world.human: c.x = -c.x
        # Decide to toughen the crisis
        if c.x < 4 * c.level - 36 + abs(tdiv(randint(-32768, 32767), 1024)):
            hangTough(newsWindow, world, world.country[world.cmptr])
        # Decide to back down
        else:
            c.backDown, c.hasBegun, headline.crisisVal = True, False, True
            hangLoose(newsWindow, world, world.country[world.cmptr],
                world.country[world.human], c.victim)
    # Calculate possible penalties for withdrawal
    _show_penalties(newsWindow, world, headline)
    c.aggrFlag = True

def minorTough(newsWindow, world):
    """
    Toughen the human vs minor country AI crisis.
    Can be executed by both of the parties.
    """
    c = world.crisis
    c.level -= 1
    x = (128 >> c.level) if c.level > 1 else 0     # CASE has no entry for level 1
    # Worsen diplomatic relations
    changeDiplOpinion(c.who, world.country[world.human], -x)
    newsWindow.reactionLine.setText(Local.generateReactionLine(c.who, c.level, True, False))

    # Minor countries will never escalate into nuclear war
    if c.level < 2:
        c.backDown, c.hasBegun = True, False
        newsWindow.reactionLine.setText(Local.generateReactionLine(c.who, c.level, True, True))
        newsWindow.question.setEnabled(False)
        newsWindow.backDown.setText(Local.strings[Local.CRISIS_BD_BUTTON][1])
    newsWindow.question.setText(Local.strings[Local.CRISIS_MINOR_BUTTON][c.level-1])

def minorCrisis(newsWindow, world, news):
    """Main human vs minor country AI crisis routine"""
    c = world.crisis
    # If crisis hasn't begun yet, start it now
    if not c.hasBegun:
        c.resetCrisisData()
        c.hasBegun, c.whichHead = True, news
        c.who, c.victim, c.level = news.actor, news.target, 9
        c.backDown = False
        c.x = (1, -1)[world.human]
        # MinorCrisis opens by moving the victim into the human's sphere.
        changeDMess(world, c.victim, c.x)
        newsWindow.setLocked(True)
        newsWindow.backDown.setEnabled(True)
    # The original divides by 8 (and the computer's version already did here).
    # MinorCrisis: ``Influence(Human, Who)`` -- the country making the move, not the
    # country it is aimed at.
    c.x = (abs(c.victim.dMess - world.avgDMess) * influence(world.country[world.human], c.who)) // 8
    c.y = 1 << ((9 - c.level) // 2)
    # Minor AI toughens the crisis
    if c.x * c.y < 4 * c.level - 36 + abs(tdiv(randint(-32768, 32767), c.y * 256)):
        minorTough(newsWindow, world)
    # Minor AI backs down
    else:
        c.backDown, c.hasBegun, c.whichHead.crisisVal = True, False, True
        doPolicy(world, c.who, c.victim, news.action, news.old, crisis=True)
        newsWindow.reactionLine.setText(Local.generateReactionLine(c.who, c.level, True, True))
        newsWindow.question.setEnabled(False)
        newsWindow.backDown.setText(Local.strings[Local.CRISIS_BD_BUTTON][1])

def tough(world):
    """
    Toughen superpower AI vs minor country AI crisis.
    Can be executed by both of the parties.
    """
    c = world.crisis
    c.level -= 1
    x = (128 >> c.level) if c.level > 1 else 0     # CASE has no entry for level 1
    changeDiplOpinion(c.who, world.country[world.cmptr], -x)

def computerCrisis(world, news):
    """Main superpower AI vs minor country AI crisis routine"""
    c = world.crisis
    if not crisisEligible(news):
        return
    # CmptrCrisis starts with ``BackDown := FALSE``.  The flag lives on the shared
    # Crisis object here, so a back-down in an earlier crisis (this turn's or
    # last turn's) used to survive into this one: the loop below then never ran
    # and the minor country "backed down" without ever having been challenged.
    c.backDown = False
    c.hasBegun = False
    c.whichHead = news
    c.who, c.victim = news.actor, news.target
    c.level, c.x = 9, (1,-1)[world.cmptr]
    changeDMess(world, c.victim, c.x)
    while True:
        c.x = (abs(c.victim.dMess - world.avgDMess) * influence(world.country[world.cmptr], c.who)) // 8
        c.y = 1 << ((9 - c.level) // 2)
        # Minor country toughens the crisis.
        # (The subtraction used to bind tighter than the addition, turning the
        # threshold into ``4*level - 36*rand`` — usually hugely negative, so the
        # minor country toughened the crisis almost every time.)
        if c.x * c.y < 4 * c.level - 36 + abs(tdiv(randint(-32768, 32767), c.y * 256)):
            tough(world)
        # Minor country back down
        else:
            c.backDown, news.crisisVal = True, True
            doPolicy(world, c.who, c.victim, news.action, news.old, crisis=True)
        # Superpower considerations
        if not c.backDown and c.level > 1:
            c.x = gimpt(world, c.who, news.action, c.victim, news.old, news.new, 0)
            c.y, c.z = c.usaImpt, c.ussrImpt
            if world.cmptr == 0: c.z = c.y
            # Toughen the crisis
            if c.z > 4 * c.level - 36 + abs(tdiv(randint(-32768, 32767), 1024)):
                tough(world)
            # Back down
            else: c.backDown = news.crisisVal = True
        if not (not c.backDown and c.level > 1): return

def doCHumanLoose(newsWindow, world, news):
    """
    Human player decides to back down (in a crisis of any type).
    Action performed on clicking the 'back down' button in the NewsWindow.
    """
    c = world.crisis
    if c.who is None or not crisisEligible(news):
        # No crisis on a headline that cannot be one (see crisisEligible), and
        # none was ever started on it: there is nothing to back down from.
        return
    # Crisis against superpower AI
    if c.who.id < 2:
        # First click - do the back down
        if not c.backDown:
            c.backDown, c.hasBegun = True, False
            hangLoose(newsWindow, world, world.country[world.human],
                world.country[world.cmptr], news.target)
            if world.twoPFlag: world.changeSides()
            _record_human_resolve(newsWindow.parent, False)
        # Click one more time to exit
        else:
            newsWindow.setLocked(False)
            if world.beingQuestioned:
                if len(newsWindow.news) == 0:
                    world.beingQuestioned = False
                    newsWindow.setVisible(False)
                    continueNextTurn(newsWindow.parent, world)
                else: doCrisis(newsWindow, world, newsWindow.news[0])
    # Crisis against minor country
    else:
        # First click - do the back down
        if not c.backDown:
            c.backDown, c.hasBegun = True, False
            newsWindow.reactionLine.setText(Local.generateReactionLine(world.country[world.human],
                c.level, True, True))
            newsWindow.question.setEnabled(False)
            newsWindow.backDown.setText(Local.strings[Local.CRISIS_BD_BUTTON][1])
        # Click one more time to exit
        else:
            newsWindow.setLocked(False)
    #TODO draw scores


def doCHumanTough(newsWindow, world, news):
    """
    Human player toughens a crisis (of any type).
    Action performed on clicking the 'question' button in the NewsWindow.
    """
    c = world.crisis
    if not crisisEligible(news):
        return
    # Crisis against superpower AI
    if news.actor.id < 2:
        if (c.level < 9 and c.hasBegun) or (c.level == 9 and c.who.id == world.human and c.hasBegun):
            hangTough(newsWindow, world, world.country[world.human])
            _record_human_resolve(newsWindow.parent, True)
        if not world.ANWFlag and not world.NWFlag:
            doCrisis(newsWindow, world, news)
            # TODO display window
        if world.twoPFlag: world.changeSides()
    # Crisis against minor country
    else:
        if c.level < 9 and c.hasBegun:
            minorTough(newsWindow, world)
            if c.backDown:
                # The last rung was reached (MinorCrisis: ``UNTIL BackDown OR
                # CrisisLevel=1``): the crisis is over.  Calling minorCrisis now
                # found ``hasBegun`` cleared and opened a brand-new crisis.
                return
        minorCrisis(newsWindow, world, news)
        # TODO SHow window
