"""
The objectives strip: a compact panel showing how the standing promises are
holding up.

The prestige score moves for reasons the player mostly did not cause and only
becomes legible in 1990, so between 1982 and 1990 the game gives almost no
feedback.  This strip is that feedback: one chip per intermediate objective,
green while it holds and red once it has been lost, with the numbers behind it
in the tooltip.  A details button opens the same list with the reward attached.

The strip is a dock widget rather than a modal so it can sit permanently above
the map.  It reads its contents from :mod:`GameLogic.Objectives`; there is no
game logic in this file.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFontMetrics
from PyQt5.QtWidgets import (QDialog, QDockWidget, QHBoxLayout, QLabel,
                             QPushButton, QSizePolicy, QVBoxLayout,
                             QWidget)

import Theme
from GameLogic import Objectives
from Theme import Palette
from Widgets import FitScrollArea


class ChipLabel(QLabel):
    """A label that elides its text on the right instead of clipping it.

    A plain centred QLabel narrower than its text crops *both* ends, which cut
    the reward number off the front of every chip.  The full text stays in
    ``fullText`` (and in the tooltip); what is painted always starts at the left.
    """

    def __init__(self):
        super(ChipLabel, self).__init__()
        self.fullText = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def setChipText(self, text):
        self.fullText = text
        self._elide()

    def _elide(self):
        # Padding (6) and border (1) on both sides, from the style sheet.
        room = max(10, self.width() - 14)
        metrics = QFontMetrics(self.font())
        self.setText(metrics.elidedText(self.fullText, Qt.ElideRight, room))

    def resizeEvent(self, event):
        super(ChipLabel, self).resizeEvent(event)
        self._elide()


class ObjectivesBar(QDockWidget):
    """A thin strip of objective chips, one per standing commitment."""

    def __init__(self, parent):
        super(ObjectivesBar, self).__init__()
        self.parent = parent
        self.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.setTitleBarWidget(QWidget())

        root = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 3, 10, 3)
        layout.setSpacing(8)

        self.heading = QLabel()
        self.heading.setFont(Theme.font(8, bold=True))
        self.heading.setStyleSheet("color: %s;" % Palette.ACCENT.name())
        layout.addWidget(self.heading)

        self.chips = []
        self.chipBox = QWidget()
        chipLayout = QHBoxLayout()
        chipLayout.setContentsMargins(0, 0, 0, 0)
        chipLayout.setSpacing(6)
        self.chipBox.setLayout(chipLayout)
        layout.addWidget(self.chipBox, 1)

        self.tally = QLabel()
        self.tally.setFont(Theme.font(8, bold=True))
        layout.addWidget(self.tally)

        self.detailsButton = QPushButton()
        self.detailsButton.setFixedHeight(22)
        self.detailsButton.clicked.connect(self.openDetails)
        layout.addWidget(self.detailsButton)

        root.setLayout(layout)
        self.setWidget(root)
        self.setFixedHeight(34)
        self.detailsWindow = None
        self.setStrings()

    # -- presentation -------------------------------------------------------

    def setStrings(self):
        """Built once at start-up; the objective text itself is data."""
        self.heading.setText("Objectives")
        self.detailsButton.setText("Details")
        self.tally.setText("")

    def _ensureChips(self, count):
        if len(self.chips) == count:
            return
        layout = self.chipBox.layout()
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Detach at once: a pending deleteLater() leaves the old card
                # painted over the new ones until the event loop gets to it.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self.chips = []
        for _ in range(count):
            chip = ChipLabel()
            chip.setFont(Theme.font(8, bold=True))
            chip.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            chip.setMinimumWidth(40)
            layout.addWidget(chip, 1)
            self.chips.append(chip)

    def refresh(self):
        """Re-read the objectives for the local player."""
        world = getattr(self.parent, "world", None)
        if world is None:
            self.hide()
            return
        side = self.localSide()
        rows = Objectives.evaluate(world, side)
        if not rows:
            self.hide()
            return
        self.show()
        self._ensureChips(len(rows))
        # After a nuclear war nothing is "holding": the promises are void.
        void = bool(getattr(world, "NWFlag", False) or getattr(world, "ANWFlag", False))
        met = 0
        for chip, (objective, is_met, progress) in zip(self.chips, rows):
            held_now = Objectives.ever_met(world, side, objective.id)
            if is_met and not void:
                met += 1
            # Three states, not two: held now (green), held once and lost
            # (red), and never held (neutral).  A player looking at a red chip
            # needs to know whether they lost something or never had it.
            if void:
                colour, border = Palette.TEXT_DIM, Palette.BORDER
            elif is_met:
                colour, border = Palette.OK, Palette.OK.darker(140)
            elif held_now:
                colour, border = Palette.DANGER, Palette.DANGER.darker(140)
            else:
                colour, border = Palette.TEXT_DIM, Palette.BORDER
            # The name first: on a narrow screen the chip is elided on the
            # right, and "Allies..." says more than "+15...".
            chip.setChipText("%s \u00b7 %s%d" % (objective.short,
                                               "+" if is_met and not void else "",
                                               objective.reward))
            self.chipBox.layout().setStretchFactor(chip, max(1, len(chip.fullText)))
            chip.setStyleSheet(
                "QLabel { color: %s; border: 1px solid %s; border-radius: 4px;"
                " padding: 3px 6px; background-color: %s; }"
                % (colour.name(), border.name(), Palette.PANEL.name()))
            chip.setToolTip("<b>%s</b><br>%s<br><br>%s<br>worth %d points%s"
                            % (objective.title, objective.detail,
                               progress or "not measurable yet",
                               objective.reward,
                               " (void after nuclear war)" if void else ""))
        bonus = 0 if void else Objectives.bonus(world, side)
        self.tally.setText("void" if void else "%d/%d  %+d" % (met, len(rows), bonus))
        self.tally.setToolTip("Void: nuclear war ended every commitment"
                              if void else
                              "%d of %d objectives holding; objective bonus %+d points"
                              % (met, len(rows), bonus))
        tallyColour = Palette.OK if (met == len(rows) and not void) else Palette.TEXT_MUTED
        self.tally.setStyleSheet("color: %s;" % tallyColour.name())
        if self.detailsWindow is not None and self.detailsWindow.isVisible():
            self.detailsWindow.refresh()

    def localSide(self):
        world = getattr(self.parent, "world", None)
        session = getattr(self.parent, "session", None)
        if session is not None and getattr(session, "is_online", False):
            return int(getattr(self.parent, "local_side", 0))
        # Hot-seat and single-player both show the side whose turn it is, so the
        # strip always describes the player who can actually act on it.
        return int(getattr(world, "human", 0))

    def openDetails(self):
        if self.detailsWindow is None:
            self.detailsWindow = ObjectivesWindow(self.parent)
        self.detailsWindow.refresh()
        self.detailsWindow.show()
        self.detailsWindow.raise_()


class ObjectivesWindow(QDialog):
    """The same objectives, with the reward and the live numbers spelled out."""

    def __init__(self, parent):
        super(ObjectivesWindow, self).__init__(parent)
        self.parent = parent
        self.setWindowTitle("Objectives")
        self.setMinimumSize(520, 300)
        self.resize(580, 520)

        root = QVBoxLayout()
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        self.intro = QLabel()
        self.intro.setWordWrap(True)
        self.intro.setStyleSheet("color: %s;" % Palette.TEXT_MUTED.name())
        self.intro.setText(
            "These objectives count while they hold, and are dropped as soon as "
            "they stop holding.")
        root.addWidget(self.intro)

        self.rows = QWidget()
        self.rowsLayout = QVBoxLayout()
        self.rowsLayout.setContentsMargins(0, 0, 0, 0)
        self.rowsLayout.setSpacing(6)
        self.rows.setLayout(self.rowsLayout)
        root.addWidget(FitScrollArea(self.rows), 1)

        self.tally = QLabel()
        self.tally.setFont(Theme.font(10, bold=True))
        root.addWidget(self.tally)

        buttons = QHBoxLayout()
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        buttons.addStretch(1)
        buttons.addWidget(close)
        root.addLayout(buttons)

        self.setLayout(root)
        self.refresh()

    def refresh(self):
        world = getattr(self.parent, "world", None)
        if world is None:
            return
        session = getattr(self.parent, "session", None)
        if session is not None and getattr(session, "is_online", False):
            side = int(getattr(self.parent, "local_side", 0))
        else:
            side = int(getattr(world, "human", 0))
        rows = Objectives.evaluate(world, side)

        while self.rowsLayout.count():
            item = self.rowsLayout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Detach at once: a pending deleteLater() leaves the old card
                # painted over the new ones until the event loop gets to it.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

        void = bool(getattr(world, "NWFlag", False) or getattr(world, "ANWFlag", False))
        met = 0
        for objective, is_met, progress in rows:
            if is_met and not void:
                met += 1
            held_once = Objectives.ever_met(world, side, objective.id)
            if void:
                state, colour = "void (nuclear war)", Palette.TEXT_DIM
            elif is_met:
                state, colour = "holding", Palette.OK
            elif held_once:
                state, colour = "lost", Palette.DANGER
            else:
                state, colour = "not yet", Palette.TEXT_DIM
            label = QLabel(
                "<b style='color:%s'>%s</b> &nbsp;<span style='color:%s'>%s</span>"
                "<br><span style='color:%s'>%s</span><br>"
                "<span style='color:%s'>%s \u00b7 worth %d points</span>"
                % (colour.name(), objective.title, colour.name(), state,
                   Palette.TEXT.name(), objective.detail,
                   Palette.TEXT_MUTED.name(),
                   progress or "not measurable yet", objective.reward))
            label.setWordWrap(True)
            # A margin, not CSS padding: Qt's height-for-width ignores the
            # style sheet's padding, which made the cards overlap.
            label.setMargin(9)
            label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
            label.setStyleSheet(
                "QLabel { background-color: %s; border: 1px solid %s;"
                " border-radius: 6px; }"
                % (Palette.CHART_BG.name(), Palette.BORDER.name()))
            self.rowsLayout.addWidget(label)
        self.rowsLayout.addStretch(1)

        if void:
            self.tally.setText("Objectives void after nuclear war \u00b7 objective bonus +0")
        else:
            self.tally.setText("Holding %d of %d \u00b7 objective bonus %+d"
                               % (met, len(rows), Objectives.bonus(world, side)))
