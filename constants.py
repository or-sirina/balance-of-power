"""
Game constants: map-mode ids, policy verbs, per-level availability, timeline.

The policy verbs and the per-level gating tables reproduce the 1990 Edition of
*Balance of Power* (see ``docs/ORIGINAL_MECHANICS.md``).  The nine verbs are

    0 Destabilization   3 Aid to insurgents   6 Diplomatic pressure
    1 Economic aid      4 Intervene (govt)    7 Treaty
    2 Military aid      5 Intervene (rebels)  8 Trade policy

Trade policy exists only at the Multipolar level, exactly as in the original.
"""

# --- map modes --------------------------------------------------------------
M_SPHINFL = 0
M_EVENTS = 1
M_PRESTIGE = 2
M_INSG = 3
M_GOVTSTAB = 4
M_FINLPROB_USA = 5
M_FINLPROB_USSR = 6
M_WAR = 7
M_DIPL_OUT = 8
M_GOVTAID_OUT = 9
M_INSGAID_OUT = 10
M_GOVTINTV_OUT = 11
M_INSGINTV_OUT = 12
M_ECONAID = 13
M_DESTAB = 14
M_PRESS = 15
M_TREATY = 16
M_DIPL_IN = 17
M_GOVTAID_IN = 18
M_INSGAID_IN = 19
M_GOVTINTV_IN = 20
M_INSGINTV_IN = 21
M_GNP = 22
M_GNPCAP = 23
M_POP = 33
M_MILMEN = 34

#: Trade policy map modes.  Appended after the encyclopedia modes (35..57) so
#: that no existing map-mode id changes meaning and old save files keep working.
M_TRADE_OUT = 58
M_TRADE_IN = 59

#: Number of map-mode actions the control panel and menus must carry.
MAP_MODE_COUNT = 60

# --- policy verbs -----------------------------------------------------------
DESTAB = 0
ECONAID = 1
GOVTAID = 2
INSGAID = 3
GOVTINTV = 4
INGSINTV = 5
PRESSURE = 6
TREATY = 7
TRADE = 8
#: Not a policy: a headline from the historical event deck.
WORLD_EVENT = 9

#: Which verbs each difficulty level offers.
#: Beginner gets the four "boots on the ground" options, Intermediate adds the
#: money and the spooks, Expert adds statecraft, Multipolar adds trade, and the
#: fifth level is Multipolar with the opposing superpower run by a language
#: model (see GameLogic.LLMOpponent).
AVL_ACTIONS = ((2, 3, 4, 5), (0, 1, 2, 3, 4, 5), tuple(range(8)), tuple(range(9)),
               tuple(range(9)))

#: Map modes that a level does not expose (the originals' secrecy rules).
INAVL_MAP_MODES = ((4, 5, 6, 7, 13, 14, 15, 16, M_TRADE_OUT, M_TRADE_IN),
                   (5, 6, 7, 15, 16, M_TRADE_OUT, M_TRADE_IN),
                   (7, M_TRADE_OUT, M_TRADE_IN),
                   tuple(),
                   tuple())

#: Close-up rows available at each level.  Row 12 is trade policy.
CLOSE_UP_AVL_DATA = (range(6), range(8), range(12), range(13), range(13))
CLOSE_UP_SUPERPWR = (range(2, 6, 1), range(2, 7, 1), range(2, 7, 1),
                     range(2, 7, 1), range(2, 7, 1))

#: Prestige-at-risk scaling per level, indexed by ``level - 1``.
CRISIS_RISK_SCALE = (2048, 1024, 512, 512, 512)

# --- difficulty levels ------------------------------------------------------
LEVEL_BEGINNER = 1
LEVEL_INTERMEDIATE = 2
LEVEL_EXPERT = 3
LEVEL_MULTIPOLAR = 4
#: Multipolar rules, but the computer superpower is an LLM.
LEVEL_LLM = 5
LEVEL_COUNT = 5


def is_multipolar(level):
    """True for the levels where minor countries run their own foreign policy.

    Level 5 is level 4 with a different brain behind the opposing superpower, so
    every rule that keys off "Multipolar" must accept both.
    """
    return level >= LEVEL_MULTIPOLAR

# --- units ------------------------------------------------------------------
ENCYCLOPEDIA_UNITS = (4, 6, 10, 7, 4, 4, 8, 8, 11, 11, 11, 11,
                      11, 11, 9, 9, 5, 5, 5, 5, 5, 5, 5)

# --- timeline ---------------------------------------------------------------
#: The year the world is built in.  Starting a game runs the first
#: ``prePlanMove`` at once, so the player first acts in 1982 and presses Next
#: turn eight times (1982-1989); the verdict comes in 1990.  The port's country
#: data, headlines and map are all late-Cold-War.
#:
#: Note for the record: the shipped 1990 Edition runs 1988-1997 and the first
#: edition 1985-1994; the port compressed the timeline.  Both bounds are
#: constants here so a scenario can be re-dated without touching game logic.
GAME_START_YEAR = 1981
#: The first year scored: the score baseline is taken when this year begins.
GAME_BASE_YEAR = 1982
#: The year in which peace is declared and the scores are compared.
GAME_END_YEAR = 1990

# default options
DEFAULT_OPTS = (True, True, False, "english.json", 0, 0, 0)
