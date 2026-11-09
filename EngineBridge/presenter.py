"""Explicit in-memory presenter for the original single-player rule functions.

These small ports replace only widget operations. CrisisHandler and MovePlanner
remain responsible for every decision, random draw, policy and score change.
"""

from types import SimpleNamespace

from GameLogic import CrisisHandler, MovePlanner, Objectives


class Field:
    def __init__(self):
        self.text = ""
        self.enabled = True
        self.visible = True

    def setText(self, text):
        self.text = str(text)

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)

    def setVisible(self, visible):
        self.visible = bool(visible)

    def isChecked(self):
        return False


class NewsPresenter:
    def __init__(self, parent):
        self.parent = parent
        self.reactionLine = Field()
        self.question = Field()
        self.backDown = Field()
        self.newsHline = Field()
        self.advice = [Field() for _ in range(4)]
        self.picture = [Field() for _ in range(4)]
        self.leftInfoVal = [Field() for _ in range(3)]
        self.locked = False
        self.visible = False
        self.title = ""
        self.news = []
        self.dialogue = None

    def queueCrisisDialogue(self, world, headline, speaker, outcome, headline_text=None):
        """Record the completed engine event; never request a model here."""
        if world is self.parent.world and headline is world.crisis.whichHead:
            self.dialogue = {"speaker": int(speaker), "outcome": str(outcome),
                             "headline_text": headline_text}

    def setWindowTitle(self, title):
        self.title = title

    def setVisible(self, visible):
        self.visible = bool(visible)

    def setRiskValuesVisible(self, visible):
        for field in self.leftInfoVal:
            field.setText("")

    def setLocked(self, locked):
        self.locked = bool(locked)
        if not locked:
            self.dialogue = None
            self.reactionLine.setText("")
            self.question.setEnabled(False)
            self.refresh_news()

    def refresh_news(self):
        self.news = [n for n in self.parent.world.news if n.isQuestioned]

    def showUp(self):
        world = self.parent.world
        self.refresh_news()
        self.visible = True
        if world.beingQuestioned:
            if world.crisis.hasBegun and world.crisis.whichHead is not None:
                CrisisHandler.resumeCrisis(self, world)
            elif self.news:
                CrisisHandler.doCrisis(self, world, self.news[0])
            else:
                world.beingQuestioned = False
                self.visible = False
                MovePlanner.continueNextTurn(self.parent, world)


class Presenter:
    def __init__(self, service):
        self.service = service
        self.llm_opponent = None
        self.newsWindow = NewsPresenter(self)
        self.controlPanel = SimpleNamespace(nextTurnButton=Field(), yearLabel=Field(),
                                            drawScores=lambda: None)
        painter = SimpleNamespace(recalculateMapBuffer=lambda: None)
        scene = SimpleNamespace(mapPainter=painter)
        self.mapView = SimpleNamespace(scene=lambda: scene, resetMapView=lambda: None)
        self.menu = SimpleNamespace(options=[Field()])

    @property
    def world(self):
        return self.service.world

    def setStatus(self, status):
        pass

    def endGame(self):
        self.service.emit("game_ended", nuclear=bool(self.world.NWFlag or self.world.ANWFlag))

    def saveWorld(self):
        # Autosave is deliberately unchecked; explicit safe slots own bridge I/O.
        pass

    def llm_note(self, text):
        self.service.emit("opponent_note", text=str(text))

    def on_turn_completed(self):
        _, gained, lost = Objectives.refresh(self.world, self.world.human)
        self.service.emit("turn_completed", year=self.world.year, gained=gained, lost=lost)
