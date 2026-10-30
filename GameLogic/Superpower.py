from .Country import Country
from .Globals import mAidConv, intvConv, tdiv

class Superpower(Country):
    """
    Class representing the Superpowers - playable countries that can enact variety
    of policies. Every superpower has also several additional properties:
    - historic, original and current in-game score,
    - pugnacity, adventuroussness and integrity parameters that affect AI behavior
      and how the superpower is seen by the international community.
    """

    def __init__(self, parent, id, leaderName, GNP, pop, milSpnd, govtWing, insgWing,
                govtStrength, insgStrength, gGrowth, pGrowth, govtStability, invtFrac,
                govtPopul, milMen, dMess, deaths):
        super().__init__(parent, id, leaderName, GNP, pop, milSpnd, govtWing, insgWing,
                govtStrength, insgStrength, gGrowth, pGrowth, govtStability, invtFrac,
                govtPopul, milMen, dMess, deaths)
        self.pugnacity = 0
        self.adventurousness = 0
        self.integrity = 0
        self.econAid = [0]*80
        self.destab = [0]*80
        self.treaty = [0]*80
        self.pressure = [0]*80
        #: Trade policy: a purely diplomatic verb, available at Multipolar level.
        self.trade = [0]*80
        self.oldEconAid = [0]*80
        self.oldDestab = [0]*80
        self.oldTreaty = [0]*80
        self.oldPressure = [0]*80
        self.oldTrade = [0]*80
        self.historyScore = []
        self.initScore, self.oldScore, self.score = 0, 0, 0

    def initPolicies(self, target, govtAid, insgAid, govtIntv, insgIntv,
                     econAid, treaty, trade=0):
        super().initPolicies(target, govtAid, insgAid, govtIntv, insgIntv)
        self.econAid[target] = econAid
        self.treaty[target] = treaty
        self.trade[target] = trade
    
    def setMaxPolicy(self):
        from .Globals import intel_cost
        budget = (self.gnpSpnd[2] // 8) + self.totalGovtAid - intel_cost(self)
        self.maxIntervene = self.maxMilAid = 5
        for i in range(4, -1, -1):
            if mAidConv(i + 1) > budget:
                self.maxMilAid = i
            if intvConv(i + 1) > (self.milMen // 4) - self.totalIntv:
                self.maxIntervene = i

    def prestige(self, world):
        """The opinion-weighted prestige sum, the score before objectives.

        Main.p ``CalcScores`` sums ``DipAff[i,1] * PrestVal[i]`` over the minor
        countries, i.e. each *minor country's* regard for the superpower (its
        own row), not the superpower's regard for the minor country.  The two
        start out different (Init.p derives the minor's row from both
        superpowers' opinions) and only become one number once ``ChgDipAff``
        touches the pair, so the distinction matters for who starts ahead.
        Pascal's ``div`` truncates toward zero.
        """
        return tdiv(sum([c.diplOpinion[self.id] * c.prestigeVal
                         for c in world.country[2:]]), 1024)

    def updateScore(self, world):
        # The 1990 Pascal is explicit -- ``FOR i:=3 TO NoCntry`` in CalcScores --
        # and it iterates the seventy-eight minor countries, excluding the two
        # superpowers.  Summing all eighty added a term for each superpower's own
        # prestige value, which is larger than the entire minor-country pool and
        # moves on its own during play, so the player's score changed for reasons
        # the manual does not describe.
        self.score = self.prestige(world)
        # Intermediate objectives pay into the same score.  The bonus has to be
        # read back from the world rather than added here, because this method
        # recomputes the score from scratch every time it is called: anything
        # added to ``score`` alone would be wiped out by the next call.
        try:
            from GameLogic.Objectives import bonus
            self.score += bonus(world, self.id)
        except (ImportError, AttributeError, IndexError, TypeError):
            # No objectives loaded, or a save from before they existed: the game
            # must still score normally.
            pass