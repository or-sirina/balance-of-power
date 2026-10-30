import json
import random
import Paths
from GameLogic.Globals import getMaxLevel

MAP_MODE_NAME           = 0
TAG_RELATION            = 1
TAG_POLICY              = 2
FINL_PROB               = 3
TAG_INSURGENCY          = 4
TAG_SPHERE              = 5
LEGEND                  = 6
UNIT                    = 7
WINDOW_INFO             = 8
TAG_IDEOLOGY            = 9
TAG_STREMGTH            = 10
TAG_COUP_CHANCE         = 11
TAG_COUP_PACE           = 12
TAG_INSG_PACE           = 13
TAG_EVENT               = 14
CRISIS_FILTER           = 15
ADVISORY                = 16
LABEL_POLICY            = 17
WINDOW_HISTORY          = 18
WINDOW_HISTORY_LEGEND   = 19
WINDOW_NEWGAME          = 20
CRISIS_RISK             = 21
FINL_PACE               = 22
CRISIS_SUPER_BUTTON     = 23
CRISIS_MINOR_BUTTON     = 24
CRISIS_BD_BUTTON        = 25
CRISIS_STR              = 26
WINDOW_ECONOMY          = 27
EVENT                   = 28
MENU                    = 29
WINDOW_SCORES           = 30
WINDOW_ENDGAME          = 31
WINDOW_PROGINFO         = 32
WINDOW_POLICY           = 33
TAG_WARPEACE            = 34
MAIN_PANEL              = 35
DATA_LANGUAGES          = 36
DATA_COUNTRIES          = 37
# Groups added by the reviewed/extended version.  ``DATA_COUNTRIES`` is 37 and
# the 80 country records occupy indices 37..116, so anything new must be
# appended after them: 117 onwards.
LOCAL_NEWS              = 117
MULTIPLAYER             = 118
TENSION                 = 119
EVENTS                  = 120
CUSTOM                  = 121
#: Labels for the six trade-policy steps (0 = none ... 5 = full partnership).
TRADE                   = 122
#: One short caption per advisor, naming the factor that advisor weights most.
ADVISOR_BIAS            = 123
#: Captions for the controls added with the graphics pass (F1, F4, F6, F8):
#: year-card caption, relief switch, its hint, sound switch, its hint, legend.
GRAPHICS_EXTRA          = 124
#: The advisor-system switch (label, tooltip) and the two bench names.
ADVISOR_EXTRA           = 125
#: Background music: the switch, its hint, and the volume submenu.
MUSIC                   = 126
CTRY_NAME               = 0
CTRY_ADJECTIVE          = 1
CTRY_GENITIVE           = 2
CTRY_CAPITAL            = 3
CTRY_LEADER_TITLE       = 4
CTRY_LEADER_NAME        = 5
CTRY_INSG_LEFT          = 6
CTRY_INSG_RIGHT         = 7

def getLanguage(language):
    global strings
    with open(Paths.locale_file(language), encoding="utf-8") as f:
        return json.load(f)

strings = getLanguage("english")["data"]

#: For groups 0 and 1 the index is the policy verb (0-8, the ninth being trade);
#: for groups 2-5 it is the crisis level (0-9).
_howManyStrings = (
    (3,3,4,4,4,4,3,4,3),
    (3,4,3,4,3,4,2,4,3),
    (0,0,3,3,2,4,3,3,2,2),
    (0,0,3,2,3,3,3,2,3,2),
    (4,)*10,
    (4,)*10)
_startingAt = (
    (16,19,29,40,48,58,66,69,182),
    (81,22,33,44,52,62,84,73,185),
    (0,0,21,18,16,12,9,6,4,2),
    (0,0,41,39,36,36,31,29,26,24),
    (0,0,56,56,52,52,48,48,44,44),
    (60,)*10)
# units for different map modes or value types
_modeUnits = {
    6: FINL_PROB,
    7: FINL_PACE,
    9: TAG_SPHERE,
    10: TAG_INSURGENCY,
    11: TAG_COUP_CHANCE,
    12: TAG_EVENT,
    13: TAG_RELATION,
    14: TAG_WARPEACE,
    # Pseudo-mode for the trade-policy step labels.  Mode ids 0-14 have other
    # meanings and 15 is special-cased inside parseValue(), so 16 is free.
    16: TRADE,
}


def getNewsHeadline(actor, host, victim, action, old, new):
    global strings
    toReturn = ""
    # internal events
    if actor == host:
        if action == 1 and victim == actor: a,b = 0,3
        elif action == 0 and victim.id < 2: a,b, = 3,4
        elif action == 2 and victim == actor: a,b = 13,3
        elif action == 6 and old == 2: a,b = 7,3
        elif action == 6 and old == 1: a,b = 10,3
        elif action == 1 and victim.id < 2: a,b = 26,3
        elif action == 2 and victim.id < 2: a,b = 36,4
        elif action == 4 and victim.id < 2: a,b = 55,3
        elif action == 7 and victim.id < 2: a,b = 77,4
        elif action == 5: a,b = old,4
        else:
            # An internal combination with no template of its own.  Falling
            # through here used to raise UnboundLocalError and abort the AI's
            # whole turn, so degrade to a plain line instead.
            return strings[DATA_COUNTRIES + victim.id][CTRY_NAME]
        startingAt, howManyStrings = a, b
    # policy events
    else:
        group = 0 if new > old else 1
        if not 0 <= action < len(_startingAt[group]):
            return "%s \u2014 %s" % (strings[DATA_COUNTRIES + actor.id][CTRY_NAME],
                                     strings[DATA_COUNTRIES + victim.id][CTRY_NAME])
        startingAt, howManyStrings = _startingAt[group][action], _howManyStrings[group][action]

    # concatenate the headline composed with 2 or more subparts
    for i in range(startingAt, startingAt + howManyStrings):
        strPart = strings[EVENT][i].split("*")
        try:
            type = int(strPart[0])
        except (ValueError, IndexError):
            continue
        alternatives = strPart[1:]
        if not alternatives:
            continue
        # first character indicates which substring will be used as a subpart
        if type == 0: skip = random.randint(0, 3)
        elif type == 1: skip = new
        elif type == 3: skip = 0
        elif type == 4: skip = old
        else: skip = 0
        # A value can legitimately fall outside the number of alternatives the
        # localisation file provides (an intervention level with no phrasing, a
        # language edited by hand).  Clamp rather than raise: a missing sentence
        # must never abort a turn in the middle of the AI's move.
        if skip < 0:
            skip = 0
        elif skip >= len(alternatives):
            skip = len(alternatives) - 1
        # A reduction in trade is built from "<verb> ... with _" followed by the
        # new step's name ("a trade protocol."), which read as a sentence with
        # a missing word: "reduces commercial ties with Algeria a trade
        # protocol."  Join the two halves.
        if (actor != host and action == 8 and new <= old
                and i == startingAt + 2):
            toReturn += "; now"
        # append the part
        toReturn += alternatives[skip]
    # replace the special characters with other data
    victimStr, actorStr = strings[DATA_COUNTRIES + victim.id], strings[DATA_COUNTRIES + actor.id]
    toReturn = toReturn.replace("_", countryInProse(victim.id))
    toReturn = toReturn.replace("=", victimStr[CTRY_ADJECTIVE])
    toReturn = toReturn.replace("&", victimStr[CTRY_LEADER_TITLE])
    toReturn = toReturn.replace("{", victim.leaderName)
    toReturn = toReturn.replace("[", victim.oldLeaderName)
    toReturn = toReturn.replace("@", victimStr[CTRY_CAPITAL])
    toReturn = toReturn.replace("|", victimStr[CTRY_GENITIVE])
    toReturn = toReturn.replace("!", countryInProse(actor.id))
    # A headline may begin with a placeholder, so it can start with the article
    # or with a lower-cased word from the middle of a template.
    if toReturn[:1].islower():
        toReturn = toReturn[:1].upper() + toReturn[1:]
    toReturn = toReturn.replace(">", actorStr[CTRY_ADJECTIVE])
    toReturn = toReturn.replace("+", actorStr[CTRY_LEADER_TITLE])
    toReturn = toReturn.replace("}", actor.leaderName)
    toReturn = toReturn.replace("]", actor.oldLeaderName)
    toReturn = toReturn.replace("^", actorStr[CTRY_CAPITAL])
    toReturn = toReturn.replace("?", actorStr[CTRY_GENITIVE])
    if actor == host and action == 1 and victim == actor:
        # A revolution names the side that WON, which is now the government:
        # the old code indexed the country record with the headline's ``new``
        # value, so a revolution read "Panamanian troops" or "Panama troops"
        # according to an unrelated number.
        toReturn = toReturn.replace("%", victimStr[7 if victim.govtWing >= 0 else 6])
    else: toReturn = toReturn.replace("%", victimStr[7 if host.insgWing >= 0 else 6])
    return toReturn

def _generateTextStr(startingAt, howManyStrings):
    global strings
    toReturn = ""
    for i in range(startingAt, startingAt + howManyStrings):
        toReturn += random.choice(strings[CRISIS_STR][i].split("*"))
    return toReturn

def generateReactionLine(who, level, isMinor, isBDown):
    toReturn = ""
    # major crisis
    if not isMinor: 
        toReturn += _generateTextStr(who.id, 1)
        group = 2 if not isBDown else 3
    # minor crisis
    else: 
        # Ids 0 and 1 are the superpowers; every minor country (id >= 2) takes this
        # branch.  ``> 2`` sent the first minor country down the superpower path.
        if who.id > 1: group = 4 if not isBDown else 5
        else:
            return _generateTextStr(64 + who.id, 1) + _generateTextStr(66, 3)
    toReturn += _generateTextStr(_startingAt[group][level], _howManyStrings[group][level])
    return toReturn

def generateFirstHead(c):
    x,j = c.strengthRatio, 0
    while x > 1: x,j = x//2, j+1
    if j > 12: j = 12
    rank = (12-j) % 4
    i = (12 - j) // 4
    if j == 0: rank = 7 - 4 * c.strengthRatio
    i = 86 + (16 * i) + (4 * (3 & (c.random >> 8)))
    return getNewsHeadline(c, c, c, 5, i, rank)
    #return (i,rank)

def generateLastHead(c):
    if c.random > 0: i, x = 166, 13 * c.govtPopul
    else: i,x = 150, c.govtWing + 127
    if x > 255: x = 255
    i += ((x // 64) * 4)
    rank = (x % 64) // 16
    return getNewsHeadline(c, c, c, 5, i, rank)

def parseValue(mode, value):
    """
    Format a value for a given mode.

    """
    if mode in _modeUnits: g = _modeUnits[mode]
    elif 0 <= mode <= 5:
        return strings[TAG_POLICY][mode * 6 + value]
    elif mode == 8:
        return strings[TAG_RELATION][getMaxLevel((-100,-72,-44,-16,16,44,62,100), value)]
    else:
        # Mode 15 used to fall through to ``strings[g][value]`` with ``g``
        # never assigned (UnboundLocalError).  No caller produces it or any
        # other unknown mode today; degrade to an empty cell, not a crash.
        return ""
    return strings[g][value]

def countryName(country_id):
    """The country's own name, as the interface shows it.

    ``Country.name`` is the *leader* (Deng, Thatcher, Kohl), which is right for
    flavour but wrong wherever a country has to be identified unambiguously -
    a player looking for China should not have to know who runs it, and a list of
    moves shown as "aid to Deng" reads like a list of pen-pals.
    """
    try:
        return strings[DATA_COUNTRIES + int(country_id)][CTRY_NAME]
    except (IndexError, TypeError, ValueError):
        return str(country_id)


def countryInProse(country_id):
    """The country's name as a noun inside a sentence.

    English wants a definite article for the two superpowers and for almost
    nobody else, and a headline template cannot know which country it will be
    given.  Without this, generated news read "presents evidence that United
    States is bankrolling fighters in the Shining Path".
    """
    name = countryName(country_id)
    if int(country_id) in (0, 1):
        return "the %s" % name
    return name


def format(value):
    """
    Add thousands comma separator fot the given value.

    """
    return '{:,}'.format(value)

def formatValue(value, mode):
    # Military intervene
    if mode in (4,5): return format(value * 1000) + strings[UNIT][3]
    # Military aid
    elif mode in (2,3): return "$" + format(value * 10) + strings[UNIT][1]
    # Economic aid
    elif mode in (1,6): return "$" + format(value * 100) + strings[UNIT][1]
    # Population
    elif mode == 10: return format(value * 100000)
    # GNP
    elif mode == 11: return "$" + format(value * 100) + strings[UNIT][1]
    # GNP per capita
    elif mode == 12: return "$" + format(value)