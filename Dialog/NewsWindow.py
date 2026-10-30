from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (QAbstractItemView, QBoxLayout, QButtonGroup,
                             QComboBox, QDialog, QGridLayout, QGroupBox,
                             QHeaderView, QLabel, QMessageBox, QPushButton,
                             QRadioButton, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget)
from Widgets import FitScrollArea
import Local
import Theme
from GameLogic.Advisors import roster
from Theme import Palette
from functools import partial
from GameLogic.CrisisHandler import (canQuestion, doCHumanLoose, doCHumanTough, doCrisis,
                                     getAdvisorOpinion, resumeCrisis)
from GameLogic.MovePlanner import continueNextTurn

class NewsWindow(QDialog):

    def __init__(self, parent):
        super(NewsWindow, self).__init__(parent)
        self.parent = parent
        # top table - news list and filters
        self.table = QTableWidget(0,5)
        horizLabels = ["", "", "", "", ""]
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.itemSelectionChanged.connect(self.doDisplayNewsHeadline)
        self.table.setHorizontalHeaderLabels(horizLabels)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setWordWrap(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        topLayout = QGridLayout()
        topLayout.addWidget(self.table, 0,1)
        filterLayout = QBoxLayout(QBoxLayout.TopToBottom)
        self.filters = [QPushButton(parent.graphics.icon[23 + i], "") for i in range(5)]
        filterGroup = QButtonGroup()
        for i,j in zip(self.filters, range(5)):
            i.setFixedHeight(32)
            i.setMinimumWidth(120)
            i.setAutoExclusive(True)
            i.setCheckable(True)
            i.released.connect(partial(self.doRefreshNews, j))
            filterGroup.addButton(i)
            filterLayout.addWidget(i)
            filterLayout.addSpacing(-5)
        filterLayout.addSpacing(30)
        filterLayout.setAlignment(Qt.AlignVCenter)
        self.ctryList = QComboBox()
        self.ctryList.setMaxVisibleItems(10)
        self.ctryList.addItems([Local.strings[Local.DATA_COUNTRIES + i][Local.CTRY_NAME] for i in range(80)])
        self.ctryList.currentIndexChanged.connect(partial(self.doRefreshNews, 5))
        self.localNews = QRadioButton()
        self.localNews.released.connect(partial(self.doRefreshNews, 5))
        filterGroup.addButton(self.localNews)
        filterLayout.addWidget(self.localNews)
        filterLayout.addWidget(self.ctryList)
        topLayout.addLayout(filterLayout,0,0)
        topLayout.setContentsMargins(-50,0,0,0)
        self.table.setFixedHeight(220)


        # left half - news
        buttons = QBoxLayout(QBoxLayout.LeftToRight)
        leftLayout = QBoxLayout(QBoxLayout.TopToBottom)
        leftLayout.setContentsMargins(-80,0,0,0)
        self.newsHline = QLabel()
        self.newsHline.setWordWrap(True)
        # Headline plus the tension / score summary: up to five wrapped lines.
        self.newsHline.setMinimumHeight(96)
        self.newsHline.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        leftLayout.addSpacing(20)
        leftLayout.addWidget(self.newsHline)
        leftLayout.addSpacing(8)
        self.question = QPushButton()
        self.backDown = QPushButton()
        self.question.released.connect(self.doTough)
        self.backDown.released.connect(self.doLoose)
        for i in (self.question, self.backDown): buttons.addWidget(i)
        leftLayout.addLayout(buttons)
        self.reactionLine = QLabel()
        self.reactionLine.setMinimumHeight(44)
        self.reactionLine.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.reactionLine.setWordWrap(True)
        leftLayout.addSpacing(20)
        leftLayout.addWidget(self.reactionLine)
        leftLayout.addSpacing(20)
        leftInfoLayout = [QBoxLayout(QBoxLayout.LeftToRight) for i in range(3)]
        self.leftInfo = [QLabel() for i in range(3)]
        self.leftInfoVal = [QLabel()  for i in range(3)]
        for i in range(3):
            leftInfoLayout[i].addWidget(self.leftInfo[i])
            leftInfoLayout[i].addWidget(self.leftInfoVal[i])
            leftLayout.addLayout(leftInfoLayout[i])
            if i < 2: leftLayout.addSpacing(-5)
        
        # right half - advisory
        rightLayout = QBoxLayout(QBoxLayout.TopToBottom)
        rightLayout.setContentsMargins(0,-50,0,0)
        #rightLayout.addWidget(self.advisory)
        headsLayout = QBoxLayout(QBoxLayout.LeftToRight)
        headsColumn = [QBoxLayout(QBoxLayout.TopToBottom) for i in range(2)]
        head = [QBoxLayout(QBoxLayout.LeftToRight) for i in range(4)]
        self.picture = [QLabel() for i in range(4)]
        self.advice = [QLabel() for i in range(4)]
        self.bias = [QLabel() for i in range(4)]
        self.advisorSide = 0
        for i in range(4):
            art = parent.graphics.advisorSmall[0][i]
            self.picture[i].setPixmap(art)
            self.picture[i].setFixedSize(art.size())
            # Name the factor this advisor weights, so the disagreement between
            # the four of them is legible instead of mysterious.
            self.bias[i].setAlignment(Qt.AlignCenter)
            self.bias[i].setFont(Theme.font(7))
            self.bias[i].setStyleSheet("color: %s;" % Palette.TEXT_DIM.name())
            column = QBoxLayout(QBoxLayout.TopToBottom)
            column.setSpacing(2)
            column.addWidget(self.picture[i], 0, Qt.AlignHCenter)
            column.addWidget(self.bias[i])
            column.addStretch(1)
            self.advice[i].setWordWrap(True)
            self.advice[i].setFixedWidth(96)
            head[i].addLayout(column)
            head[i].addWidget(self.advice[i])
            headsColumn[i//2].addLayout(head[i])
        # Parented: without a parent this is a top-level widget that nothing
        # ever shows, and it stayed in the application's widget list for the
        # life of the process.
        self.closeUpButton = QPushButton(self)
        
        for i in range(2): headsLayout.addLayout(headsColumn[i])
        rightLayout.addLayout(headsLayout)

        # save right and left layouts into groups
        self.detailGroup = [QGroupBox() for i in range(3)]
        self.detailGroup[0].setLayout(leftLayout)
        self.detailGroup[1].setLayout(rightLayout)
        self.detailGroup[2].setLayout(topLayout)

        mainLayout = QGridLayout()
        mainLayout.addWidget(self.detailGroup[2], 0, 0, 1, 2)
        for i in range(2): mainLayout.addWidget(self.detailGroup[i], 1, i)
        
        self.setAdvisorSide(0)
        self.setStrings()
        # The layout needs ~830x590, more than a 1366x768 laptop at 125-150%
        # scaling offers: host it in a scroll area so the window can shrink.
        content = QWidget()
        content.setLayout(mainLayout)
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(FitScrollArea(content))
        self.setLayout(outer)
        self.setMinimumSize(400, 300)
        self.resize(830, 590)
        self.setModal(True)

    def filterCondition(self, n, mode):
        if mode == 0: return n.actor == self.parent.world.USA and n.new > n.old     #USA Actions
        elif mode == 1: return n.actor == self.parent.world.USA and n.new < n.old   #USA Other
        elif mode == 2: return n.actor == self.parent.world.USSR and n.new > n.old  #USSR Actions
        elif mode == 3: return n.actor == self.parent.world.USSR and n.new < n.old  #USSR Other
        elif mode == 4: return n.actor.id  >= 2                                     #Minor actions
        elif mode == 6: return n.isQuestioned                                       #AI turn - questions our moves
        else:                                                                       #Filter by country
            return self.sortedCountries[self.ctryList.currentIndex()] in (n.actor.id, n.target.id)

    def doRefreshNews(self, mode):
        """
        Populate the table with event headlines filtered in accordance to the given 'mode'

        """
        self.mode = mode
        if mode == 5: self.localNews.setChecked(True)
        news = self.parent.world.news
        self.table.setRowCount(0)
        # Filter the news and store successfully filtered objects in the self.news property
        self.news = []
        for n in news:
            if self.filterCondition(n, mode): self.news.append(n)
        for i,n in zip(range(len(self.news)), self.news):
            self.table.insertRow(i)
            self.table.setItem(i, 0, QTableWidgetItem(
                QIcon(self.parent.graphics.flag[n.actor.id]), Local.strings[Local.DATA_COUNTRIES + n.actor.id][Local.CTRY_NAME]))
            self.table.setItem(i, 1, QTableWidgetItem(
                QIcon(self.parent.graphics.flag[n.target.id]), Local.strings[Local.DATA_COUNTRIES + n.target.id][Local.CTRY_NAME]))
            self.table.setItem(i, 2, QTableWidgetItem(n.getTypeName()))
            if n.action not in (0,6): prefix = "\u25bc" if n.new < n.old else "\u25b2"
            else: prefix = ""
            self.table.setItem(i, 3, QTableWidgetItem(prefix + n.getActionValue(False)))
            checkedItem = QTableWidgetItem()
            # "Action possible?" -- only where the Question button would really
            # work (the computer's own unsettled move, a minor country's increase
            # the player has influence over), not on the player's own moves,
            # revolutions or coups.
            checkedItem.setText("✔" if canQuestion(self.parent.world, n) else "")
            checkedItem.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 4, checkedItem)
        self.table.resizeRowsToContents()
        self.table.verticalHeader().setDefaultSectionSize(35)

    def newsTitle(self):
        """The window's everyday title (crises borrow it for their own)."""
        return Local.strings[Local.MAIN_PANEL][13]

    def showUp(self):
        mode = self._getCurrentMode()
        if not self.parent.world.crisis.hasBegun:
            self.setWindowTitle(self.newsTitle())
        self.doRefreshNews(mode)
        # Rebuilding the table clears the selection, and showing the "nothing
        # selected" panel disables both crisis buttons.  During a crisis that is
        # a soft lock: the buttons are the only way out, ``doCrisis`` re-enables
        # them only on the first show (``hasBegun`` is already true by the
        # second), and the table is locked so no row can be selected to wake
        # them.  Opening the news window again therefore made the turn
        # impossible to finish.  The buttons belong to the crisis, not to the
        # table's selection.
        if self.table.currentRow() < 0 and not self.parent.world.beingQuestioned:
            self.doDisplayNewsHeadline()
        self.setVisible(True)
        if mode == 6:    #Reopen the window closed during AI questioning turn, resume AI actions
            world = self.parent.world
            crisis = world.crisis
            if crisis.hasBegun and crisis.whichHead is not None:
                # A crisis is already under way (window closed with Esc, or the
                # game was saved and loaded in the middle of it).  Redraw it as
                # it stood; ``doCrisis`` would skip the opening (blank panel,
                # dead Back Down button) and let the computer move again.
                resumeCrisis(self, world)
            elif self.news:
                doCrisis(self, world, self.news[0])
            else:
                # Everything that was being questioned has been settled; the
                # turn only needed this window to be closed.
                world.beingQuestioned = False
                self.setVisible(False)
                continueNextTurn(self.parent, world)

    def doDisplayNewsHeadline(self):
        rowNum = self.table.currentRow()
        if rowNum < 0:
            # Nothing selected.  This used to blank the panel, leaving a large
            # empty frame next to a table that only fills a quarter of the
            # window.  Say something true instead: the latest dispatch, or what
            # the world looks like if this year has produced none.
            self.hideAdvisors()
            self.closeUpButton.setEnabled(False)
            self.newsHline.setText(self.idleSummary())
            return
        headline = self.news[rowNum]
        self.newsHline.setText(headline.text)
        # Questionable policy - display advisory panel
        if not headline.crisisVal:
            # Globals.p ``Headline``: the button is live only for the computer
            # superpower's own unsettled move, or an increase by a minor country
            # the human has real influence over -- never for the human's own
            # moves, revolutions, surrenders or events (those have no policy to
            # take back, and questioning one crashed).
            self.question.setEnabled(canQuestion(self.parent.world, headline))
            self.backDown.setEnabled(False)
            for i in range(4):
                self.advice[i].setText(getAdvisorOpinion(self.parent.world, headline, i + 1))
                self.picture[i].setVisible(True)
        else: self.hideAdvisors()

    def idleSummary(self):
        """What to show in the details panel when there is nothing to show.

        In a quiet year the news table is empty for most filters, and the panel
        beside it was simply blank.  A player glancing at it deserves either the
        last thing that happened or a one-line read on the world.
        """
        world = getattr(self.parent, "world", None)
        if world is None:
            return ""
        lines = []
        recent = world.news[-1] if world.news else None
        if recent is not None:
            lines.append("<b>%s</b>" % recent.text)
        elif getattr(world, "lastEvent", ""):
            lines.append("<b>%s</b>" % world.lastEvent)
        else:
            lines.append("<b>No dispatches this year.</b>")
        lines.append(self.worldLine(world, getattr(self.parent, "local_side", 0)))
        return "<br>".join(lines)

    @staticmethod
    def worldLine(world, side=0):
        """A one-line read on the state of the competition."""
        try:
            usa, ussr = world.USA, world.USSR
            # Measured since 1982, exactly as the scores window does it.  Using
            # the raw totals made this line name a different leader from the
            # score cards on the same screen.
            lead = ((usa.score - usa.initScore)
                    - (ussr.score - ussr.initScore))
            # Capitalised because it starts a sentence after the mood clause.
            who = "The United States" if lead >= 0 else "The Soviet Union"
            # The reading the status bar gives, not the truth: what the player
            # knows is the point of the intelligence budget.
            known = getattr(world, "knownNastiness", None)
            tension = known[0 if int(side) == 0 else 1] if known else world.nastiness
            if tension < 30:
                mood = "The world is quiet"
            elif tension < 70:
                mood = "The world is tense"
            else:
                mood = "The world is close to the brink"
            return ("<span style='color:#93a6bd'>Tension %d. %s. "
                    "%s leads by %d points.</span>"
                    % (tension, mood, who, abs(lead)))
        except (AttributeError, TypeError):
            return ""

    def doLoose(self):
        """Action performed by releasing the 'back down' button"""
        doCHumanLoose(self, self.parent.world, self.news[self.table.currentRow()])
    
    def doTough(self):
        """Action performed by releasing the 'question' button"""
        doCHumanTough(self, self.parent.world, self.news[self.table.currentRow()])


    def hideAdvisors(self):
        self.backDown.setEnabled(False)
        self.question.setEnabled(False)
        for i in range(4):
            self.picture[i].setVisible(False)
            self.advice[i].setText("")
        self.setRiskValuesVisible(False)

    def setRiskValuesVisible(self, visible):
        for i,j,k in zip(self.leftInfo, self.leftInfoVal, range(3)):
            i.setText(Local.strings[Local.CRISIS_FILTER][22+k] if visible else "")
            j.setText("")

    def setLocked(self, value):
        if not value:
            previousRow = self.table.currentRow()
            self.backDown.setText(Local.strings[Local.CRISIS_BD_BUTTON][0])
            self.reactionLine.setText("")
            self.question.setDisabled(value)
            self.question.setText(Local.strings[Local.CRISIS_SUPER_BUTTON][9])
            self.setWindowTitle(self.newsTitle())
            self.doRefreshNews(self._getCurrentMode())
            self.table.selectRow(previousRow)
        self.setRiskValuesVisible(value)
        self.table.setDisabled(value)
        for i in self.filters: i.setDisabled(value)
        self.ctryList.setDisabled(value)
        self.localNews.setDisabled(value)

    def _getCurrentMode(self):
        if self.parent.world.beingQuestioned: return 6
        if self.localNews.isChecked(): return 5
        for i,j in zip(range(5), self.filters):
            if j.isChecked():
                return i
        return 5

    def refresh_if_open(self):
        """Re-read the headline list after the world changed under us.

        The network guest gets a fresh world on every snapshot, and the table
        would otherwise keep pointing at objects from the previous state.
        """
        if not self.isVisible():
            return
        if self.parent.world.beingQuestioned:
            return  # a crisis owns the window right now
        self.doRefreshNews(self._getCurrentMode())

    def endOfCrisis(self):
        self.setLocked(False)


    def setTableLocked(self, value):
        for i in self.filters: i.setEnabled(value)
        self.table.setEnabled(value)

    def reject(self):
        """Window can be closed during the crisis. If so, back down in the current crisis"""
        resBtn = QMessageBox.Yes
        w = self.parent.world
        beingQuestioned = w.beingQuestioned
        if (beingQuestioned or not self.table.isEnabled()) and not any((w.ANWFlag, w.NWFlag, w.winFlag)):
            # The old text went on to say "re-open the window to continue the
            # turn", which was the bug: the crisis stayed open and the player was
            # stuck.  Backing down now really does back down.
            resBtn = QMessageBox.question(self, "Balance of power",
                Local.strings[Local.CRISIS_FILTER][6],
                QMessageBox.Cancel|QMessageBox.Yes)
            if resBtn != QMessageBox.Yes:
                return
            self._backOutOfCrisis()
            if w.beingQuestioned:
                # The next questioned headline has just been put on the screen by
                # the same call that finished this one; the turn goes on there.
                return
        QDialog.reject(self)

    def _backOutOfCrisis(self):
        """Concede the crisis on screen and acknowledge it, exactly as the two
        clicks on the Back Down button would."""
        w = self.parent.world
        c = w.crisis
        head = c.whichHead
        if head is None:
            row = self.table.currentRow()
            head = self.news[row] if 0 <= row < len(self.news) else None
        if head is None:
            self.setLocked(False)
            if w.beingQuestioned:
                w.beingQuestioned = False
                self.setVisible(False)
                continueNextTurn(self.parent, w)
            return
        if c.hasBegun and not c.backDown:
            doCHumanLoose(self, w, head)            # first click: concede
        if c.backDown:
            doCHumanLoose(self, w, head)            # second click: acknowledge
        else:
            self.setLocked(False)

    def setAdvisorSide(self, side):
        """Swap in the advisory team of whichever superpower is playing here."""
        side = 0 if int(side) == 0 else 1
        if side == self.advisorSide and self.picture[0].pixmap() is not None \
                and not self.picture[0].pixmap().isNull():
            return
        self.advisorSide = side
        cards = self.parent.graphics.advisorSmall.get(side, [])
        team = roster(side)
        for i in range(4):
            if i < len(cards):
                self.picture[i].setPixmap(cards[i])
                self.picture[i].setFixedSize(cards[i].size())
            if i < len(team):
                self.bias[i].setText("<b>%s</b><br>%s"
                                     % (team[i].name, team[i].blurb))
                self.bias[i].setToolTip(team[i].role)

    def setStrings(self):
        self.setAdvisorSide(self.advisorSide)
        if not self.parent.world.crisis.hasBegun:
            self.setWindowTitle(self.newsTitle())
        self.table.setHorizontalHeaderLabels(Local.strings[Local.CRISIS_FILTER][8:13])
        for i in range(5):
            if i < 3:
                self.detailGroup[i].setTitle(Local.strings[Local.CRISIS_FILTER][i + 25])
            self.filters[i].setText(Local.strings[Local.CRISIS_FILTER][i])
            self.filters[i].setMinimumWidth(max(120, self.filters[i].sizeHint().width()))
        while self.ctryList.count() > 0: self.ctryList.removeItem(0)
        ctryNames = [Local.strings[Local.DATA_COUNTRIES + i ][Local.CTRY_NAME] for i in range(len(self.parent.world.country))]
        self.sortedCountries = sorted(range(len(ctryNames)), key=ctryNames.__getitem__)
        self.ctryList.addItems([ctryNames[self.sortedCountries[i]] for i in range(len(ctryNames))])
        for i in range(len(ctryNames)):
            self.ctryList.setItemIcon(i, QIcon(self.parent.graphics.flag[self.sortedCountries[i]]))
        
        self.localNews.setText(Local.strings[Local.CRISIS_FILTER][5])
        self.question.setText(Local.strings[Local.CRISIS_SUPER_BUTTON][9])
        self.backDown.setText(Local.strings[Local.CRISIS_BD_BUTTON][0])
        self.reactionLine.setText("")
        self.newsHline.setText("")