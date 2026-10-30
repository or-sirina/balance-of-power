from constants import *
from math import sqrt
import Local

class News:

    localEventImpt = {0: 5, 1: 14, 2: 10, 3: 2} # importance for different actions inside countries
    intlEventImpt = {   # importance for international policies
        DESTAB: 4,
        ECONAID: 3,
        GOVTAID: 5,
        INSGAID: 5,
        GOVTINTV: 10,
        INGSINTV: 10,
        TREATY: 5,
        TRADE: 3,
    }
    #: Pseudo ``parseValue`` mode used to render each verb's step labels.
    #: Mode 16 maps to the trade-policy step list in Local._modeUnits.
    actionToUnitMode = (3, 2, 0, 0, 1, 1, 4, 5, 16)

    def __init__(self, target, action, old, new, actor, host, crisisVal,
                 text=None, importance=None):
        super(News, self).__init__()
        #: A headline supplied verbatim, used by the historical event deck.
        #: Generated events go through the template engine; scripted ones do
        #: not, because their wording is the whole point.
        self.customText = text
        self.target = target
        self.actor = actor
        self.host = host
        self.action = action
        self.old, self.new = old, new
        self.crisisVal = crisisVal
        self.isQuestioned = False

        # local events
        if actor == target:
            if action in self.localEventImpt:
                self.importance = self.localEventImpt[action]
            else: self.importance = 5
        # international events
        else:
            if action not in self.intlEventImpt:    #pressure event - special formula
                # InsrtNews: ``Pressur: IF New>Old THEN Import:=2 ELSE Import:=12``.
                # Easing pressure (or a war headline, where old == new) is the
                # big story; applying it is routine.  This had the two swapped.
                self.importance = 2 if new > old else 12
            else: self.importance = self.intlEventImpt[action]
        
        self.importance *= (1 + abs(new - old))
        if old > new: self.importance -= 1
        if action == WORLD_EVENT:
            self.importance = importance if importance is not None else 40
        else:
            self.importance = int(sqrt((sqrt(actor.prestigeVal * target.prestigeVal) + 1) * self.importance))
        if self.importance < 1: self.importance = 1
        self.setStrings()

    def isEventWithNoValues(self):
        return self.action == WORLD_EVENT or self.actor == self.target \
            or (self.target.id < 2 and self.action == 0) \
            or (self.actor.id >= 2 and self.target.id >= 2 and self.action == 6)

    def setStrings(self):
        if self.customText:
            self.text = self.customText
            return
        self.text = Local.getNewsHeadline(self.actor, self.host, self.target, self.action, self.old, self.new)

    #: ``MAIN_PANEL`` string index for each policy verb's display name.
    #: Verbs 0-7 are contiguous at 16-23; trade policy was appended at 30 so
    #: that adding it did not renumber any existing string.
    TYPE_NAME_INDEX = (16, 17, 18, 19, 20, 21, 22, 23, 30)

    def getTypeName(self):
        if self.action == WORLD_EVENT:
            return Local.strings[Local.MAIN_PANEL][31]
        # International events
        if self.actor != self.target:
            # finlandization
            if self.target.id < 2 and self.action == 0:
                return Local.strings[Local.CRISIS_FILTER][16]
            # war - continue or surrender
            elif self.actor.id > 1 and self.target.id > 1 and self.action == 6:
                return Local.strings[Local.CRISIS_FILTER][16 + self.old]
            if 0 <= self.action < len(self.TYPE_NAME_INDEX):
                return Local.strings[Local.MAIN_PANEL][self.TYPE_NAME_INDEX[self.action]]
            return ""
        # Internal events
        index = 13 + self.action
        filters = Local.strings[Local.CRISIS_FILTER]
        return filters[index] if 0 <= index < len(filters) else ""

    def getActionValue(self, useOldValue):
        if self.isEventWithNoValues(): return ""
        return Local.parseValue(self.actionToUnitMode[self.action], self.old if useOldValue else self.new)