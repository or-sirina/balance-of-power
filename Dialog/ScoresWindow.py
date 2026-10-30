from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QBoxLayout, QDialog, QFrame, QLabel, QPushButton,
                             QSizePolicy)

import Local
import Theme
from Charts import LineChart
from Theme import Palette
from constants import GAME_BASE_YEAR, GAME_END_YEAR


def standing(power, world):
    """The score as of the last scored year, which is what the chart plots.

    ``score - initScore`` is not the same thing between the start of a year and
    its scoring: the year's historical events shift ``initScore`` at once while
    ``score`` waits for ``mainMove``.  A game ended by nuclear war stops in that
    gap, so the card disagreed with its own gain line and the chart.
    """
    ended_in_war = world.ANWFlag or world.NWFlag
    history = power.historyScore
    if ended_in_war and history:
        return history[-1]
    return power.score - power.initScore


class ScoreCard(QFrame):
    """One superpower's score block: flag, name, totals and the turn delta."""

    def __init__(self, parent, side):
        super().__init__(parent)
        self.side = side
        self.setObjectName("scoreCard")
        layout = QBoxLayout(QBoxLayout.TopToBottom)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        header = QBoxLayout(QBoxLayout.LeftToRight)
        self.flag = QLabel()
        self.flag.setPixmap(parent.graphics.flag[side])
        self.flag.setFixedSize(38, 24)
        self.flag.setScaledContents(True)
        self.name = QLabel()
        self.name.setFont(Theme.font(13, bold=True))
        header.addWidget(self.flag)
        header.addSpacing(8)
        header.addWidget(self.name)
        header.addStretch(1)

        self.total = QLabel("0")
        self.total.setFont(Theme.font(26, bold=True))
        self.total.setAlignment(Qt.AlignCenter)

        self.deltaLabel = QLabel()
        self.deltaLabel.setAlignment(Qt.AlignCenter)
        self.deltaLabel.setFont(Theme.font(10))

        self.spark = LineChart([[]])
        self.spark.setCompact(True)
        self.spark.setMinimumHeight(46)
        self.spark.setAxisRange(None, None)

        layout.addLayout(header)
        layout.addWidget(self.total)
        layout.addWidget(self.deltaLabel)
        layout.addWidget(self.spark)
        self.setLayout(layout)
        self._apply_style()

    def _apply_style(self):
        color = Theme.superpower_color(self.side)
        self.setStyleSheet(
            "#scoreCard { background-color: %s; border: 1px solid %s; border-radius: 8px; }"
            % (Palette.PANEL_ALT.name(), color.name()))
        self.name.setStyleSheet("color: %s;" % color.name())

    def setStrings(self):
        self.name.setText(Local.strings[Local.DATA_COUNTRIES + self.side][Local.CTRY_NAME])

    def updateValues(self, superpower, world):
        score = standing(superpower, world)
        # ``oldScore`` is overwritten as soon as the year is scored, so the gain
        # comes from the history, which also leaves out any baseline shift.
        history = superpower.historyScore
        delta = history[-1] - history[-2] if len(history) > 1 else 0
        self.total.setText("{:+,}".format(score))
        color = Palette.OK if delta >= 0 else Palette.DANGER
        self.total.setStyleSheet("color: %s;" % (Palette.OK.name() if score >= 0 else Palette.DANGER.name()))
        self.deltaLabel.setText("%s %s" % (Local.strings[Local.WINDOW_SCORES][0], "{:+,}".format(delta)))
        self.deltaLabel.setStyleSheet("color: %s;" % color.name())
        history = list(superpower.historyScore) or [0]
        self.spark.setData([history])
        self.spark.setAxisRange(None, None)
        self.spark.setTitle("")


class ScoresWindow(QDialog):
    """Current standing of both superpowers, with a running prestige chart."""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.setModal(True)
        self.setMinimumSize(520, 420)
        self.resize(560, 500)
        self._build()
        self.setStrings()

    def _build(self):
        root = QBoxLayout(QBoxLayout.TopToBottom)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        self.headline = QLabel()
        self.headline.setFont(Theme.font(14, bold=True))
        self.headline.setAlignment(Qt.AlignCenter)

        cards = QBoxLayout(QBoxLayout.LeftToRight)
        self.cards = [ScoreCard(self.parent, 0), ScoreCard(self.parent, 1)]
        for card in self.cards:
            cards.addWidget(card, 1)

        self.chartTitle = QLabel()
        self.chartTitle.setFont(Theme.font(10, bold=True))
        self.chartTitle.setStyleSheet("color: %s;" % Palette.TEXT_MUTED.name())

        self.chart = LineChart([[], []])
        self.chart.setMinimumHeight(200)
        self.chart.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("color: %s;" % Palette.TEXT_MUTED.name())

        # Filled in only when the game has ended: who won, and by how much.
        self.verdict = QLabel()
        self.verdict.setAlignment(Qt.AlignCenter)
        self.verdict.setFont(Theme.font(12, bold=True))
        self.verdict.setWordWrap(True)
        self.verdict.hide()

        root.addWidget(self.headline)
        root.addWidget(self.verdict)
        root.addLayout(cards)
        root.addWidget(self.chartTitle)
        root.addWidget(self.chart, 1)
        root.addWidget(self.summary)

        buttons = QBoxLayout(QBoxLayout.LeftToRight)
        buttons.addStretch(1)
        self.newGameButton = QPushButton("New game")
        self.newGameButton.clicked.connect(self._new_game)
        self.closeButton = QPushButton("Close")
        self.closeButton.setDefault(True)
        self.closeButton.clicked.connect(self.close)
        buttons.addWidget(self.newGameButton)
        buttons.addWidget(self.closeButton)
        root.addLayout(buttons)
        self.setLayout(root)

    def setStrings(self):
        strings = Local.strings[Local.WINDOW_SCORES]
        self.setWindowTitle(strings[-1])
        self.chartTitle.setText("<b>%s</b> \u2014 %s" % (strings[5], strings[1]))
        self.chart.setLegend((Local.strings[Local.WINDOW_SCORES][2],
                              Local.strings[Local.WINDOW_SCORES][3]))
        # Nine labels, not twelve: the history holds 1982-1990 and the game
        # ends in 1990, so the last three were axis ticks for years that cannot
        # occur.
        self.chart.setCategories(["'%d" % (GAME_BASE_YEAR + i)
                                 for i in range(GAME_END_YEAR - GAME_BASE_YEAR + 1)])
        for card in self.cards:
            card.setStrings()
        self.refresh()

    def refresh(self):
        """Re-read the world and repaint the standings.

        Deliberately *not* called ``update``: overriding ``QWidget.update``
        makes Qt's own repaint scheduling recurse into the game logic.
        """
        world = getattr(self.parent, "world", None)
        if world is None:
            return
        usa, ussr = world.country[0], world.country[1]
        for card, power in zip(self.cards, (usa, ussr)):
            card.updateValues(power, world)
        self.chart.setData((list(usa.historyScore) or [0], list(ussr.historyScore) or [0]))
        self._update_headline(usa, ussr)

    def _update_headline(self, usa, ussr):
        world = self.parent.world
        gap = standing(usa, world) - standing(ussr, world)
        if world.ANWFlag or world.NWFlag:
            # The scores stop meaning anything: nobody wins a nuclear war.
            self.headline.setText("Nuclear war \u2014 nobody wins")
            self.headline.setStyleSheet("color: %s;" % Palette.DANGER.name())
        elif gap == 0:
            self.headline.setText("Dead heat")
            self.headline.setStyleSheet("color: %s;" % Palette.TEXT.name())
        else:
            leader = usa if gap > 0 else ussr
            lead = abs(gap)
            color = Theme.superpower_color(leader.id)
            self.headline.setText("%s leads by %s" % (
                Local.strings[Local.DATA_COUNTRIES + leader.id][Local.CTRY_NAME], "{:,}".format(lead)))
            self.headline.setStyleSheet("color: %s;" % color.name())
        self._update_verdict(usa, ussr)
        # The victory line belongs to the end of the game, not to every repaint.
        if world.winFlag:
            self.summary.setText(Local.strings[Local.WINDOW_SCORES][4])
        elif world.ANWFlag or world.NWFlag:
            self.summary.setText("")
        else:
            self.summary.setText("")

    def _new_game(self):
        """Offered at the end of a game (and handy at any time)."""
        self.close()
        window = self.parent
        if getattr(window, "newGameWindow", None) is not None:
            window.newGameWindow.show()
            window.newGameWindow.raise_()

    def _update_verdict(self, usa, ussr):
        """A one-line result once the game is over."""
        world = self.parent.world
        if not world.winFlag:
            self.verdict.hide()
            return
        gap = (usa.score - usa.initScore) - (ussr.score - ussr.initScore)
        names = [Local.strings[Local.DATA_COUNTRIES + i][Local.CTRY_NAME] for i in (0, 1)]
        if gap == 0:
            text, color = "A draw: both superpowers finish level.", Palette.TEXT
        elif world.twoPFlag and self.parent.is_hotseat():
            winner = 0 if gap > 0 else 1
            text = "%s won by %s points." % (names[winner], "{:,}".format(abs(gap)))
            color = Theme.superpower_color(winner)
        else:
            # The player at this keyboard: not ``world.human``, which in play by
            # mail has already passed to the opponent.
            mine = self.parent.player_side()
            won = (gap > 0) == (mine == 0)
            text = "You %s by %s points." % ("won" if won else "lost", "{:,}".format(abs(gap)))
            color = Palette.OK if won else Palette.DANGER
        self.verdict.setText(text)
        self.verdict.setStyleSheet("color: %s;" % color.name())
        self.verdict.show()

    def showEvent(self, event):
        self.refresh()
        super().showEvent(event)
