import json
import Paths
from .Superpower import Superpower
from .Country import Country
from .Globals import mAidConv, intvConv, tdiv
from constants import GAME_START_YEAR, LEVEL_MULTIPOLAR, WORLD_EVENT, is_multipolar
from .News import News
from .Crisis import Crisis
import Local
from random import randint

class World:

    def __init__(self, level, twoPlayer, human):
        super(World, self).__init__()
        self.news = []
        self.country = []
        #self.crisis = Crisis()
        self.nastiness = 0
        self.sumDMess = 0
        self.avgDMess = 0
        self.crisis = Crisis()
        self.ANWFlag, self.NWFlag, self.winFlag = False, False, False
        #: Keys of the historical events that have already fired.
        self.firedEvents = []
        #: Headline of the most recent historical event, for the status bar.
        self.lastEvent = ""
        #: Intelligence budget per superpower, 0-5.  Costs aid money and buys
        #: a better estimate of what the other side is thinking.
        self.intel = [0, 0]
        #: What each side BELIEVES the world tension and the opponent's
        #: pugnacity are.  The truth stays in ``nastiness``; nobody reads it
        #: except the AI, which of course knows its own mind.
        self.knownNastiness = [0, 0]
        self.knownPugnacity = [0, 0]
        self.newGame(level, twoPlayer, human)
        self.beingQuestioned = False

    #: Fields that arrived after the first release, with the value a save from
    #: before them should be given.  Anything a loaded world can be missing has
    #: to appear here, or the game dies on start-up with an AttributeError --
    #: which is exactly what a save from an older build used to do.
    LATE_FIELDS = {
        "ANWFlag": False,
        "NWFlag": False,
        "winFlag": False,
        "beingQuestioned": False,
        "quitFlag": False,
        "firedEvents": list,
        "lastEvent": "",
        "intel": lambda: [0, 0],
    }

    def repair(self):
        """Give a world loaded from an older save the fields the code expects.

        Called for every world that enters the window, including new ones, so it
        must be a no-op when nothing is missing.  A default that is a list has to
        be built fresh per world, hence the callables: a shared mutable default
        would put every loaded game in the same intelligence budget.
        """
        for name, default in self.LATE_FIELDS.items():
            if hasattr(self, name):
                continue
            setattr(self, name, default() if callable(default) else default)
        # Saves from before the intelligence budget have no reading at all, and
        # a reading of zero would tell the player the world is calm when it may
        # be at DEFCON 2.  The honest default is the truth on the day the save
        # was written; nobody had spent anything to mislead themselves yet.
        if not getattr(self, "knownNastiness", None):
            self.knownNastiness = [int(getattr(self, "nastiness", 0))] * 2
        if not getattr(self, "knownPugnacity", None):
            pugnacity = 0
            countries = getattr(self, "country", None) or []
            if countries:
                pugnacity = int(getattr(countries[0], "pugnacity", 0))
            self.knownPugnacity = [pugnacity] * 2
        if not hasattr(self, "objectiveState"):
            self.objectiveState = None
        if not hasattr(self, "advisorGameId"):
            self.advisorGameId = None
        return self

    def loadWorldData(self):
        with open(Paths.data("world_data.json"), "r", encoding="utf-8") as f:
            contents = json.load(f)
        # load country basic data
        for i in contents:
            id = i["id"] - 1
            if id < 2:
                self.country.append(Superpower(self, id,
                    Local.strings[Local.DATA_COUNTRIES + id][Local.CTRY_LEADER_NAME],
                    i["gnp"], i["population"], i["milit_spend"], i["govtWing"], i["insgWing"],
                    i["govtStrength"], i["insgStrength"], i["ggrowth"], i["pgrowth"], i["govtStability"],
                    i["investFraction"], i["govtPopularity"], i["militaryMen"], i["dontMess"], i["deaths"]))
            else: self.country.append(Country(self, id,
                    Local.strings[Local.DATA_COUNTRIES + id][Local.CTRY_LEADER_NAME],
                    i["gnp"], i["population"], i["milit_spend"], i["govtWing"], i["insgWing"],
                    i["govtStrength"], i["insgStrength"], i["ggrowth"], i["pgrowth"], i["govtStability"],
                    i["investFraction"], i["govtPopularity"], i["militaryMen"], i["dontMess"], i["deaths"]))
            self.country[-1].languageGroup = i["language_group"]
            # load contingencies and minor influence spheres for the country
            for j in i["contiguous"]: self.country[id].addContingency(j - 1)
            for j in i["minor_sphere"]: self.country[id].addMinorSphere(j - 1)
            self.sumDMess += i["dontMess"]
        self.USA = self.country[0]
        self.USSR = self.country[1]
        # set USA and USSR policies towards countries, and the two superpowers'
        # own opinion rows (Init.p ``SetHDipAff`` / ``SetCDipAff``).  Both rows
        # have to be complete before any minor country's row is derived from
        # them: the old code derived each country's row while only the columns
        # up to its own id had been read, and (worse) re-derived the two
        # superpowers' rows from partial data, overwriting USSR->USA (-70) and
        # the rest of the data.
        for i in contents:
            id = i["id"] - 1
            for j,k in zip([i["usa_policy"], i["ussr_policy"]], range(2)):
                self.country[k].initPolicies(id, j[1], j[2], j[3], j[4], j[6], j[5])
                self.country[k].diplOpinion[id] = i["usa_opinion" if k == 0 else "ussr_opinion"]
        # Minor countries' rows (Init.p InitCountry, ``IF Cntry>2``): derived from
        # the two superpower rows, over every column including the superpowers'
        # own.  That makes ``DipAff[c,1]`` differ from the data value
        # ``DipAff[1,c]`` until the first ChgDipAff on the pair -- which is the
        # number the score reads (see Superpower.prestige).
        for c in self.country[2:]:
            c.recalcDiplOpinion(self)
        for i in contents:
            id = i["id"] - 1
            # set minor country opinions and policies (one-directional overrides,
            # as in Init.p: ``DipAff[3,4]:=60`` does not touch ``[4,3]``)
            for j in i["minor_opinion"]:
                self.country[id].diplOpinion[int(j) - 1] = i["minor_opinion"][j]
            # multipolar level - minor countries can enact policies
            if is_multipolar(self.level):
                for j in i["minor_policy"]:
                    x = i["minor_policy"][j]
                    self.country[id].initPolicies(int(j) - 1, x[0], x[1], x[2], x[3])

    def newGame(self, level, twoPlayer, human):
        self.level = level
        # Level 5 ("Adaptive") is Multipolar with a different brain behind the
        # opposing superpower; the README promises that without a key it plays
        # exactly like Multipolar.  Every other rule already goes through
        # ``is_multipolar``; the numbers below scale with the level NUMBER, so
        # they use the rules level -- otherwise level 5 started with more
        # tension, more pugnacity and a less random world than level 4.
        rules_level = min(level, LEVEL_MULTIPOLAR)
        level = rules_level
        self.human = human
        self.cmptr = 1 - human
        self.twoPFlag = twoPlayer
        self.year = GAME_START_YEAR
        self.sumDMess = 0
        self.loadWorldData()
        self.loadEncyclopedia()
        self.avgDMess = max(1, self.sumDMess // len(self.country))
        # Init.p: ``Nastiness:=8*Level+Random div 2048`` -- Random is signed and ``div``
        # truncates, so the draw is -16..15, not 0..15.
        self.nastiness = 8 * level + tdiv(randint(-32768, 32767), 2048)
        for i in range(2):
            who = self.country[i]
            who.pugnacity = 32 + (4 * level) + tdiv(randint(-32768, 32767), 4096)
        self.country[self.cmptr].pugnacity += (4 * level)
        # Init.p computes adventurousness only once BOTH pugnacities are final
        # (including the computer's extra 4*Level).  Doing it inside the loop
        # above read the other superpower's pugnacity before it existed.
        for i in range(2):
            who = self.country[i]
            # Init.p sets 128 as well (one above the 127 ceiling); the first
            # ``MainMove`` clamps it to 127, so it is kept as is.
            who.integrity = 128
            who.adventurousness = who.pugnacity + self.nastiness - who.gnpFrac[2] + 32 - self.country[1-i].pugnacity
            if who.adventurousness < 16: who.adventurousness = 16
        # At the start of a game both sides read the situation correctly.
        self.knownNastiness = [self.nastiness, self.nastiness]
        self.knownPugnacity = [self.country[0].pugnacity, self.country[1].pugnacity]
        for c in self.country:
            c.govtWing = self.randomAdjust(c.govtWing, -127, 127, 8192 >> level)
            c.govtStrength = self.randomAdjust(c.govtStrength, 1, 32767, 4096 >> level)
            c.maturity = self.randomAdjust(c.maturity, 0, 255, 8192 >> level)
            c.govtPopul = self.randomAdjust(c.govtPopul, 0, 20, 16384 >> level)
            for i in range(len(self.country)):
                x = c.govtAid[i]
                self.country[i].totalGovtAid += mAidConv(x)
                c.totalGovtAid -= mAidConv(x)
                x = c.insgAid[i]
                c.totalGovtAid -= mAidConv(x)
                x,y = c.govtIntv[i], c.insgIntv[i]
                c.totalIntv += intvConv(x) + intvConv(y)
            x = c.milMen
            tmp = (c.gnpSpnd[2] + c.totalGovtAid) // 2
            if tmp < 1: tmp = 1
            # Init.p: the force other countries have committed to *this* one,
            # IntvConv(IntvGovt[Who,i]) * MilPowr[Who] div MilMen[Who].  The
            # indices were crossed (this country's own power against its own
            # outbound intervention).  Superpowers only, until Multipolar.
            sources = self.country if is_multipolar(self.level) else self.country[:2]
            y = sum([(intvConv(s.govtIntv[c.id]) * s.milPower) // max(1, s.milMen) for s in sources])
            c.milPower = ((4 * tmp * x) // (tmp + x)) + y
            tmp = c.gnpSpnd[2] // 2
            c.prestigeVal = (16 * tmp * x) // (tmp + x)
            x = (((256 - c.maturity) * c.population)) // 2048
            tmp = sum([2 * mAidConv(c.insgAid[i.id]) for i in self.country])
            if tmp < (x // 8) + 1: tmp = (x // 8) + 1
            c.insgPower = (4 * tmp * x) // (tmp + x)

    def loadEncyclopedia(self):
        """
        The encyclopedia consists of 23 data sets, each data set consists of 80 values
        corresponding to each of the 80 countries in-game. The data are encoded as
        hexadecimal 2-byte integers (= 4 hex characters for each data entry), thus
        each data set is 320 ASCII characters long.

        """
        with open(Paths.data("encyclopedia_data.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        # split chunks of data
        for row in data:
            for i in range(len(self.country)):
                self.country[i].encyclopedia.append(int(row[i * 4 : (i + 1) * 4], base=16))
        

    def randomAdjust(self, value, min, max, divisor):
        x = value + tdiv(randint(-32768, 32767), divisor)
        if x < min: x = min
        elif x > max: x = max
        return x

    def addNews(self, actor, target, host, action, old, new, crisis,
                text=None, importance=None):
        """Add or update a headline.

        Policy headlines are merged when the same actor repeats the same action
        on the same target, so a turn does not fill up with duplicates.  A
        historical event is never merged: two events in one year may share an
        actor and a target, and both deserve their own line.
        """
        alreadyExists = False
        if action != WORLD_EVENT:
            for n in self.news:
                if n.actor == actor and n.target == target and action == n.action:
                    n.new = new
                    # InsrtNews: LoclCri := (New <= LoclOld).  The merged headline
                    # keeps the FIRST old value, so the move is a net increase (and
                    # still open to challenge) exactly when new > n.old; a later
                    # step down used to mark a net increase as already settled.
                    n.crisisVal = (new <= n.old)
                    n.setStrings()
                    alreadyExists = True
                    break
        if not alreadyExists:
            self.news.append(News(target, action, old, new, actor, host, crisis,
                                  text=text, importance=importance))
        self.news.sort(key = lambda x: x.importance, reverse=True)

    def changeSides(self):
        if self.human == 0: self.human, self.cmptr = 1, 0
        else: self.human, self.cmptr =  0, 1

    
