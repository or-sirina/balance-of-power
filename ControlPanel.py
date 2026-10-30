"""
Main window bottom panel.

Four groups, left to right:

* **Standings** — both superpowers, their prestige and the scoreboard button;
* **Map mode** — the eighteen mode buttons (plus hidden actions for the
  menus, which index into the same list);
* **Selection** — what is currently selected on the map, with shortcuts to the
  close-up and news windows;
* **Turn** — the year, whose move it is, and the button that ends the turn.
"""

from functools import partial

import time

from PyQt5.QtCore import QSize, Qt, QTimer
from PyQt5.QtWidgets import (QAction, QActionGroup, QDockWidget, QGridLayout,
                             QHBoxLayout, QLabel, QPushButton, QWidget)

import Local
import Theme
from ActionButton import ActionButton
from Theme import Palette
from Widgets import TurnIndicator
from Dialog.ScoresWindow import standing
from constants import MAP_MODE_COUNT, M_TRADE_OUT, M_TRADE_IN


def _format_elapsed(seconds):
    """Elapsed seconds as m:ss, which reads faster than a bare count."""
    minutes, rest = divmod(max(0, int(seconds)), 60)
    return "%d:%02d" % (minutes, rest)


class ControlPanel(QDockWidget):

    def __init__(self, parent):
        super(ControlPanel, self).__init__()
        self.parent = parent
        self.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.setTitleBarWidget(QWidget())

        mainLayout = QHBoxLayout()
        mainLayout.setContentsMargins(8, 4, 8, 6)
        mainLayout.setSpacing(14)
        multiWidget = QWidget()
        panelLayout = []
        self.titleLabel = []
        for i in range(4):
            self.titleLabel.append(QLabel())
            self.titleLabel[i].setFont(Theme.font(9, bold=True))
            self.titleLabel[i].setStyleSheet("color: %s;" % Palette.ACCENT.name())
            self.titleLabel[i].setAlignment(Qt.AlignCenter)
            panelLayout.append(QGridLayout())
            panelLayout[i].setContentsMargins(0, 0, 0, 0)
            panelLayout[i].setSpacing(4)
            mainLayout.addLayout(panelLayout[i])

        self._build_standings(panelLayout[0])
        self._build_map_modes(panelLayout[1])
        self._build_selection(panelLayout[2])
        self._build_turn(panelLayout[3])

        multiWidget.setLayout(mainLayout)
        self.setWidget(multiWidget)
        self.setFixedHeight(112)
        #: Monotonic start of the current wait, or None when it is our move.
        self._waitStarted = None
        self._waitTimer = None
        self.setStrings()

    # -- panels -------------------------------------------------------------

    def _build_standings(self, layout):
        parent = self.parent
        self.flagLabel = [QLabel() for i in range(2)]
        for i in range(2):
            self.flagLabel[i].setPixmap(parent.graphics.flag[i])
            self.flagLabel[i].setFixedSize(30, 18)
            self.flagLabel[i].setScaledContents(True)
        self.scoreLabel = [QLabel() for i in range(4)]
        for label in self.scoreLabel:
            label.setFont(Theme.font(9))
        self.scoreValueLabel = [QLabel() for i in range(2)]
        for label in self.scoreValueLabel:
            label.setFont(Theme.font(12, bold=True))
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.showScoreButton = QPushButton(Local.strings[Local.MAIN_PANEL][4])
        self.showScoreButton.setFixedHeight(24)

        for i in range(2):
            layout.addWidget(self.flagLabel[i], i + 1, 0)
            layout.addWidget(self.scoreLabel[i], i + 1, 1)
            layout.addWidget(self.scoreValueLabel[i], i + 1, 2)
        layout.addWidget(self.showScoreButton, 3, 0, 1, 3)
        layout.addWidget(self.titleLabel[0], 0, 0, 1, 3)
        layout.setColumnStretch(1, 1)

    def _build_map_modes(self, layout):
        mapModeGroup = QActionGroup(self)
        self.mapModeButton = [ActionButton() for i in range(18)]
        self.mapModeAction = [QAction() for i in range(MAP_MODE_COUNT)]
        for i in range(18):
            self.mapModeButton[i].setFixedSize(26, 26)
            self.mapModeButton[i].setIconSize(QSize(22, 22))
            layout.addWidget(self.mapModeButton[i], 1 + i // 9, i % 9)
        for i in range(MAP_MODE_COUNT):
            self.mapModeAction[i].id = i
            self.mapModeAction[i].setCheckable(True)
            mapModeGroup.addAction(self.mapModeAction[i])
            # Buttons 0..16 cover the map modes that have an icon; button 17 is
            # a reserved spacer, and the remaining modes are reachable from the
            # View menu only (as in the original).
            if i < 17:
                self.mapModeButton[i].setAction(self.mapModeAction[i])
        layout.addWidget(self.titleLabel[1], 0, 0, 1, 9)
        self.mapModeButton[17].setEnabled(False)

    def _build_selection(self, layout):
        parent = self.parent
        self.selectionFlag = QLabel()
        self.selectionFlag.setFixedSize(38, 23)
        self.selectionFlag.setScaledContents(True)
        self.selectionName = QLabel()
        self.selectionName.setFont(Theme.font(10, bold=True))
        self.selectionValue = QLabel()
        self.selectionValue.setFont(Theme.font(11, bold=True))
        self.selectionValue.setStyleSheet("color: %s;" % Palette.ACCENT.name())
        self.closeUpButton = QPushButton(parent.graphics.icon[20], "")
        self.newsButton = QPushButton(parent.graphics.icon[22], "")
        for button in (self.closeUpButton, self.newsButton):
            button.setFixedSize(32, 32)
            button.setIconSize(QSize(28, 28))

        layout.addWidget(self.selectionFlag, 1, 0)
        layout.addWidget(self.selectionName, 1, 1, 1, 2)
        layout.addWidget(self.selectionValue, 2, 1, 1, 2)
        layout.addWidget(self.closeUpButton, 1, 3)
        layout.addWidget(self.newsButton, 2, 3)
        layout.addWidget(self.titleLabel[2], 0, 0, 1, 4)
        self.selectionName.setFixedWidth(120)
        self.selectionValue.setFixedWidth(120)

    def _build_turn(self, layout):
        self.yearLabel = QLabel("1982")
        self.yearLabel.setFont(Theme.font(20, bold=True))
        self.yearLabel.setAlignment(Qt.AlignCenter)
        self.yearCaption = QLabel()
        self.yearCaption.setFont(Theme.font(8))
        self.yearCaption.setAlignment(Qt.AlignCenter)
        self.yearCaption.setStyleSheet("color: %s;" % Palette.TEXT_MUTED.name())
        self.turnIndicator = TurnIndicator()
        self.switchPlayerButton = QPushButton()
        self.nextTurnButton = QPushButton()
        self.nextTurnButton.setObjectName("primary")
        for button in (self.switchPlayerButton, self.nextTurnButton):
            # One line each: the labels used to carry a newline and were
            # squeezed into 26 px.
            button.setFixedHeight(28)
        self.nextTurnButton.setMinimumWidth(170)

        # Next and Switch share one row; stacked, they overlapped and the lower
        # one was clipped by the panel's bottom edge.
        buttonRow = QHBoxLayout()
        buttonRow.setContentsMargins(0, 0, 0, 0)
        buttonRow.setSpacing(6)
        buttonRow.addWidget(self.nextTurnButton, 1)
        buttonRow.addWidget(self.switchPlayerButton, 0)

        layout.addWidget(self.titleLabel[3], 0, 0, 1, 2)
        layout.addWidget(self.yearLabel, 1, 0)
        layout.addWidget(self.yearCaption, 2, 0)
        layout.addWidget(self.turnIndicator, 1, 1, 2, 1)
        layout.addLayout(buttonRow, 3, 0, 1, 2)
        layout.setColumnStretch(0, 0)
        layout.setColumnStretch(1, 1)
        self.turnIndicator.setMinimumWidth(210)

    # -- strings / wiring ---------------------------------------------------

    def setStrings(self):
        self.updatePlayerNames()
        for i in range(4):
            self.titleLabel[i].setText(Local.strings[Local.MAIN_PANEL][4 + i].upper())
        self.switchPlayerButton.setText(Local.strings[Local.MAIN_PANEL][8].replace("\n", " "))
        self.switchPlayerButton.setToolTip(
            "Hand the mouse to the other player without ending the year "
            "(the original game's Change Sides).")
        self.nextTurnButton.setText(Local.strings[Local.MAIN_PANEL][9].replace("\n", " "))
        self.showScoreButton.setText(Local.strings[Local.WINDOW_SCORES][5])
        self.yearCaption.setText(Local.strings[Local.MAIN_PANEL][7])
        for i in range(MAP_MODE_COUNT):
            if i < 17:
                self.mapModeAction[i].setIcon(self.parent.graphics.icon[i])
                self.mapModeAction[i].setText(Local.strings[Local.MENU][i])
            elif 17 <= i <= 21:
                self.mapModeAction[i].setIcon(self.parent.graphics.icon[i - 9])
                self.mapModeAction[i].setText(Local.strings[Local.MENU][i - 9])
            elif 24 <= i <= 32:
                self.mapModeAction[i].setText(Local.strings[Local.MENU][i % 3 + 17])
            elif 22 <= i <= 23:
                self.mapModeAction[i].setText(Local.strings[Local.MENU][i - 5])
            elif 32 <= i <= 34:
                self.mapModeAction[i].setText(Local.strings[Local.MENU][i - 13])
            elif i in (M_TRADE_OUT, M_TRADE_IN):
                self.mapModeAction[i].setIcon(self.parent.graphics.icon[27])
                # The stored strings end in "by " because the map title appends
                # a country name; as a menu entry that read as a dangling word.
                self.mapModeAction[i].setText(
                    Local.strings[Local.MENU][72 if i == M_TRADE_OUT else 73].strip()
                    + " the selected country")
            else:
                self.mapModeAction[i].setText(Local.strings[Local.MENU][i - 4])
        self.refreshTurnState()

    def connectActions(self):
        for i in range(MAP_MODE_COUNT):
            self.mapModeAction[i].triggered.connect(partial(self.parent.mapView.setMapMode, i))
        self.newsButton.released.connect(self.parent.newsWindow.showUp)
        self.showScoreButton.released.connect(self.parent.scoresWindow.show)
        self.closeUpButton.released.connect(self.parent.showCloseUpForSelection)
        self.switchPlayerButton.released.connect(self.doChangeSides)
        self.nextTurnButton.released.connect(self.doNextTurn)

    # -- updates ------------------------------------------------------------

    def updateSelection(self):
        selection = self.parent.mapView.selection
        if selection:
            self.selectionFlag.setStyleSheet("")
            self.selectionFlag.setPixmap(self.parent.graphics.flag[selection.id])
            self.selectionName.setText(Local.strings[Local.DATA_COUNTRIES + selection.id][Local.CTRY_NAME])
            self.selectionValue.setText(selection.value)
        else:
            # A bare white rectangle reads as a missing flag; show a muted
            # empty slot instead.
            self.selectionFlag.clear()
            self.selectionFlag.setStyleSheet(
                "border: 1px dashed %s; border-radius: 2px;" % Palette.BORDER_LIGHT.name())
            self.selectionName.setText(Local.strings[Local.MAIN_PANEL][24])
            self.selectionValue.setText("")
        self.closeUpButton.setEnabled(selection is not None)

    def updatePlayerNames(self):
        """Update superpower names in the leftmost panel."""
        world = self.parent.world
        # One "(you)", on the superpower at this keyboard.  On a network (and in
        # play by mail) that is the local side, not ``world.human``: the two used
        # to be tagged separately and a network game read "(you) (you)".
        mine = self.parent.player_side()
        for i in range(2):
            label = Local.strings[Local.DATA_COUNTRIES + i][Local.CTRY_NAME]
            if i == mine:
                label += Local.strings[Local.MAIN_PANEL][10]
            if i == world.cmptr and not world.twoPFlag:
                label += Local.strings[Local.MAIN_PANEL][11]
            self.scoreLabel[i].setText(label)

    def drawScores(self):
        """Update scores on the control panel."""
        world = self.parent.world
        for i, c in zip(range(2), world.country[:2]):
            value = standing(c, world)
            self.scoreValueLabel[i].setText("{:+,}".format(value))
            color = Palette.OK if value >= 0 else Palette.DANGER
            self.scoreValueLabel[i].setStyleSheet("color: %s;" % color.name())
        self.parent.scoresWindow.refresh()

    def refreshTurnState(self):
        """Reflect whose move it is and whether the turn may be ended."""
        parent = self.parent
        world = parent.world
        self.yearLabel.setText(str(world.year))
        self.switchPlayerButton.setVisible(parent.is_hotseat())
        ending = parent.network_game
        hotseat_label = parent.hotseat_next_label()
        self.nextTurnButton.setText(Local.strings[Local.MULTIPLAYER][26] if ending
                                    else hotseat_label or
                                    Local.strings[Local.MAIN_PANEL][9].replace("\n", " "))
        self.nextTurnButton.setToolTip(
            "Each player moves in the same year. The first player presses this to "
            "pass the mouse on; the second player's press resolves the year."
            if hotseat_label else "")
        # Once one player is done the hand-over has happened; swapping back would
        # give the finished player a disabled End button.
        self.switchPlayerButton.setEnabled(parent.can_act() and not parent.pending_end)

        if world.winFlag or world.ANWFlag or world.NWFlag:
            self.turnIndicator.setState(Local.strings[Local.MAIN_PANEL][27]
                                        if world.winFlag else Local.strings[Local.MAIN_PANEL][28],
                                        "", Palette.NEUTRAL)
            self.nextTurnButton.setText("Game over")
            self.switchPlayerButton.setEnabled(False)
            self.nextTurnButton.setEnabled(False)
            self._stopWaitClock()
            return
        if parent.can_act():
            who = Local.strings[Local.DATA_COUNTRIES + parent.local_side][Local.CTRY_NAME]
            self.turnIndicator.setState("%s: %s" % (who, Local.strings[Local.MULTIPLAYER][27]),
                                        "", Palette.OK)
            self._stopWaitClock()
        else:
            # The button used to go quietly grey, which reads as a broken
            # control rather than as "it is not your move".  Say so on the
            # button, and count how long we have been waiting: in a lobby or
            # over a flaky link the difference between "he is thinking" and "he
            # has gone" is exactly this number.
            self.turnIndicator.setState(Local.strings[Local.MULTIPLAYER][17],
                                        self._waitText(parent), Palette.WARN)
            self.nextTurnButton.setText(Local.strings[Local.MULTIPLAYER][63])
            if parent.network_game:
                self._startWaitClock()
        self.nextTurnButton.setEnabled(parent.can_end_turn())

    # -- waiting clock ------------------------------------------------------

    def _waitText(self, parent):
        """The 'waiting for X' line, with the elapsed time appended."""
        base = parent.waiting_for_text()
        if self._waitStarted is None:
            return base
        elapsed = int(time.monotonic() - self._waitStarted)
        return "%s \u2014 %s" % (base, _format_elapsed(elapsed))

    def _startWaitClock(self):
        if self._waitStarted is None:
            self._waitStarted = time.monotonic()
        if self._waitTimer is not None:
            return
        self._waitTimer = QTimer(self)
        self._waitTimer.setInterval(1000)
        self._waitTimer.timeout.connect(self._tickWaitClock)
        self._waitTimer.start()

    def _stopWaitClock(self):
        self._waitStarted = None
        if self._waitTimer is not None:
            self._waitTimer.stop()
            self._waitTimer.deleteLater()
            self._waitTimer = None

    def _tickWaitClock(self):
        parent = self.parent
        if parent is None or self._waitStarted is None:
            self._stopWaitClock()
            return
        self.turnIndicator.setState(Local.strings[Local.MULTIPLAYER][17],
                                    self._waitText(parent), Palette.WARN)

    # -- actions ------------------------------------------------------------

    def doChangeSides(self):
        """Action performed on releasing 'Switch player' button (hot-seat)."""
        if self.parent.can_act() and not self.parent.pending_end:
            self.parent.switch_hotseat_side()

    def doNextTurn(self):
        """Action performed on releasing 'End turn' button."""
        self.nextTurnButton.setEnabled(False)
        self.parent.request_end_turn()
