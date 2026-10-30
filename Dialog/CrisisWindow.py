"""
The head-to-head crisis dialog.

Shown when one superpower's move is contested by the other human player.  It
replaces the news-window crisis machinery for two-player games, which the
original port never wired up (``reactNews`` skips its AI branches entirely when
``twoPFlag`` is set, so two players could provoke each other freely).

The dialog is deliberately read-only about outcomes: it reports what the player
decided and lets :class:`GameLogic.CrisisDuel.CrisisDuel` apply the rules, so
the host and the guest agree on the result.
"""

from PyQt5.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPainter, QPen
from PyQt5.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                             QPushButton, QVBoxLayout, QWidget)

import Local
import Theme
from GameLogic.Advisors import roster
from GraphicsLoader import ADVISOR_RINGS
from Theme import Palette, lerp_color
from Widgets import FitScrollArea


def rung_name(level):
    """What to call a rung of the crisis ladder.

    Only rungs 4 and below are DEFCONs, and the world-tension gauge on the
    status bar counts DEFCON 5 down to 1 as well; printing "DEFCON 7" invented a
    level that exists nowhere.  The bands are the manual's: 9-7 is the back
    channel, 6-5 a diplomatic crisis, 4-1 the DEFCONs.
    """
    try:
        level = int(level)
    except (TypeError, ValueError):
        level = 1
    if level <= 4:
        return "DEFCON %d" % max(1, level)
    if level <= 6:
        return "Diplomatic crisis"
    return "Back channel"


class DefconLadder(QWidget):
    """Nine rungs from DEFCON 5 down to DEFCON 1."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._level = 9
        self.setFixedHeight(34)
        self.setMinimumWidth(320)

    def setLevel(self, level):
        self._level = max(1, min(9, int(level)))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        width = (self.width() - 8 * 3) / 9.0
        painter.setFont(Theme.font(7))
        for index in range(9):
            x = index * (width + 3)
            # The rungs are numbered 9 (safe) down to 1 (the exchange) from left
            # to right, so the lit band has to grow *towards* the red end as the
            # crisis climbs.  Lighting ``index < level`` did the opposite: it
            # left only the green "9" cell alight at the brink of war.
            active = index < 10 - self._level
            t = index / 8.0
            color = lerp_color(Palette.OK, Palette.CRITICAL, t) if active else Palette.BORDER
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(x, 4, width, 16), 3, 3)
            if active:
                painter.setPen(QPen(Palette.TEXT_ON_ACCENT if t > 0.55 else Palette.TEXT))
                painter.drawText(int(x), 4, int(width), 16, Qt.AlignCenter, str(9 - index))
        painter.end()


class AdvisorRow(QFrame):
    """One advisor: a portrait card, what that advisor cares about, and a verdict."""

    def __init__(self, parent, index):
        super().__init__(parent)
        # NB: QWidget.parent is a *method*, so keep the window under our own
        # name rather than reaching for self.parent later.
        self.window = parent
        self.index = index
        self.side = 0
        layout = QHBoxLayout()
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        # Portrait column.  The card carries the advisor's colour, and the
        # caption names the factor that advisor weights most heavily — the one
        # thing that explains why the four of them disagree.
        art = parent.graphics.advisorLarge[0][index]
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)
        self.picture = QLabel()
        self.picture.setPixmap(art)
        self.picture.setFixedSize(art.size())
        self.caption = QLabel()
        self.caption.setAlignment(Qt.AlignCenter)
        self.caption.setFont(Theme.font(7))
        self.caption.setStyleSheet("color: %s; border: none;" % Palette.TEXT_DIM.name())
        column.addWidget(self.picture, 0, Qt.AlignHCenter)
        column.addWidget(self.caption)
        column.addStretch(1)

        self.text = QLabel()
        self.text.setWordWrap(True)
        # Advisor lines can come from a language model: never let them be
        # interpreted as rich text.
        self.text.setTextFormat(Qt.PlainText)
        self.text.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.text.setStyleSheet("color: %s; border: none;" % Palette.TEXT.name())

        layout.addLayout(column)
        layout.addWidget(self.text, 1)
        self.setLayout(layout)
        self.setStyleSheet(
            "AdvisorRow { background-color: %s; border: 1px solid %s; border-radius: 6px; }"
            % (Palette.CHART_BG.name(), ADVISOR_RINGS[index].darker(180).name()))

    def setSide(self, side):
        """Portraits and names follow whoever is being advised."""
        side = 0 if int(side) == 0 else 1
        if side == self.side:
            return
        self.side = side
        art = self.window.graphics.advisorLarge[side][self.index]
        self.picture.setPixmap(art)
        self.picture.setFixedSize(art.size())
        self.setStrings()

    def setStrings(self):
        team = roster(self.side)
        if self.index < len(team):
            advisor = team[self.index]
            self.caption.setText("<b>%s</b><br>%s" % (advisor.name, advisor.blurb))
            self.caption.setToolTip(advisor.role)

    def setAdvice(self, text):
        self.text.setText(text)


class CrisisWindow(QDialog):
    """Asks one player to back down, to push the crisis further, or to talk.

    The window reports a *verb* rather than a boolean, because since the summit
    was added there are three answers and not two.  It never decides anything
    itself: :class:`GameLogic.CrisisDuel.CrisisDuel` owns the rules, so the host
    and the guest agree on the result.
    """

    decided = pyqtSignal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.setModal(True)
        self.setMinimumSize(560, 300)
        self._prompt = None
        #: True for a moment after a new prompt appears, so a double-click on
        #: the previous prompt's button cannot answer the next one (hot-seat:
        #: both players share one mouse).
        self._guard = False

        # Everything but the answer buttons scrolls, so a small screen never
        # hides the buttons.
        root = QVBoxLayout()
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)

        self.title = QLabel()
        self.title.setFont(Theme.font(15, bold=True))
        self.title.setAlignment(Qt.AlignCenter)
        body.addWidget(self.title)

        # Hot-seat only: say out loud whose answer this is.
        self.handoff = QLabel()
        self.handoff.setAlignment(Qt.AlignCenter)
        self.handoff.setWordWrap(True)
        self.handoff.setTextFormat(Qt.RichText)
        self.handoff.hide()
        body.addWidget(self.handoff)

        self.ladder = DefconLadder()
        body.addWidget(self.ladder)

        self.levelCaption = QLabel()
        self.levelCaption.setAlignment(Qt.AlignCenter)
        self.levelCaption.setStyleSheet("color: %s;" % Palette.TEXT_MUTED.name())
        body.addWidget(self.levelCaption)

        self.headline = QLabel()
        self.headline.setWordWrap(True)
        self.headline.setFont(Theme.font(11))
        self.headline.setAlignment(Qt.AlignCenter)
        self.headline.setStyleSheet(
            "QLabel { background-color: %s; border: 1px solid %s; border-radius: 6px;"
            " padding: 10px; }" % (Palette.CHART_BG.name(), Palette.BORDER.name()))
        body.addWidget(self.headline)

        self.context = QLabel()
        self.context.setWordWrap(True)
        self.context.setAlignment(Qt.AlignCenter)
        self.context.setStyleSheet("color: %s;" % Palette.TEXT_MUTED.name())
        body.addWidget(self.context)

        self.stakes = QLabel()
        self.stakes.setAlignment(Qt.AlignCenter)
        body.addWidget(self.stakes)

        # Shown only while a summit is on the table, so the player can see who
        # proposed it and what refusing would cost.
        self.summitNote = QLabel()
        self.summitNote.setWordWrap(True)
        self.summitNote.setAlignment(Qt.AlignCenter)
        self.summitNote.setStyleSheet(
            "QLabel { background-color: %s; border: 1px solid %s; border-radius: 6px;"
            " padding: 8px; color: %s; }"
            % (Palette.CHART_BG.name(), Palette.ACCENT.name(), Palette.TEXT.name()))
        self.summitNote.hide()
        body.addWidget(self.summitNote)

        self.advisorBox = QWidget()
        advisorLayout = QGridLayout()
        advisorLayout.setSpacing(6)
        self.advisors = [AdvisorRow(parent, i) for i in range(4)]
        for i, row in enumerate(self.advisors):
            advisorLayout.addWidget(row, i // 2, i % 2)
        self.advisorBox.setLayout(advisorLayout)
        body.addWidget(self.advisorBox)

        # The four rule-based verdicts are on screen before this is pressed;
        # the button re-asks the council itself, one line each, from the model.
        self.councilButton = QPushButton()
        self.councilButton.clicked.connect(self.askCouncil)
        body.addWidget(self.councilButton)

        self._scroll = FitScrollArea(content)
        root.addWidget(self._scroll, 1)
        buttons = QHBoxLayout()
        self.declineButton = QPushButton()
        self.proposeButton = QPushButton()
        self.acceptButton = QPushButton()
        self.acceptButton.setObjectName("danger")
        self.declineButton.clicked.connect(lambda: self._answer("__decline__"))
        self.acceptButton.clicked.connect(lambda: self._answer("__accept__"))
        self.proposeButton.clicked.connect(lambda: self._answer("summit"))
        buttons.addStretch(1)
        buttons.addWidget(self.declineButton)
        buttons.addWidget(self.proposeButton)
        buttons.addWidget(self.acceptButton)
        buttons.addStretch(1)
        root.addLayout(buttons)

        self.setLayout(root)

    # -- presentation -------------------------------------------------------

    def reject(self):
        """Escape must not dismiss a crisis that is waiting for an answer.

        The dialog is modal and ``MainWindow`` keeps ``duel`` set until an
        answer arrives.  Closing it without deciding left the turn unresolvable:
        no prompt on screen, ``resolving`` never cleared, End Turn disabled for
        the rest of the game.  Code that needs the window gone clears the duel
        first and calls ``hide()``, which does not come through here.
        """
        if self._prompt is not None and getattr(self.parent, "duel", None) is not None:
            self.show()
            self.raise_()
            self.activateWindow()
            return
        super().reject()

    def showPrompt(self, prompt):
        """``prompt`` is a :class:`CrisisPrompt`."""
        self._prompt = prompt
        strings = Local.strings[Local.MULTIPLAYER]
        who = Local.strings[Local.DATA_COUNTRIES + prompt.decider.id][Local.CTRY_NAME]
        self.setWindowTitle("%s \u2014 %s" % (strings[46] % who, strings[47]))
        self.title.setText(prompt.title())
        self.ladder.setLevel(prompt.level)
        if prompt.is_summit_phase:
            self.levelCaption.setText(strings[41] % rung_name(prompt.level))
        elif not prompt.is_challenge_phase:
            self.levelCaption.setText(rung_name(prompt.level))
        else:
            self.levelCaption.setText(strings[40])
        self.headline.setText(prompt.headline)
        self.context.setText(prompt.context_text())

        note = prompt.summit_note_text()
        self.summitNote.setText(note)
        self.summitNote.setVisible(bool(note))

        theirs = 1 - prompt.decider.id
        mine = prompt.risk(prompt.decider.id)
        yours = prompt.risk(theirs)
        self.stakes.setText(
            "<b style='color:%s'>%s:</b> %s&nbsp;&nbsp;&nbsp;"
            "<b style='color:%s'>%s:</b> %s" % (
                Theme.superpower_color(prompt.decider.id).name(),
                Local.strings[Local.DATA_COUNTRIES + prompt.decider.id][Local.CTRY_NAME],
                Local.strings[Local.CRISIS_RISK][mine],
                Theme.superpower_color(theirs).name(),
                Local.strings[Local.DATA_COUNTRIES + theirs][Local.CTRY_NAME],
                Local.strings[Local.CRISIS_RISK][yours]))
        # The one-player news window shows what backing down would cost; so does
        # this one, for the side that has to decide.
        if not prompt.is_challenge_phase:
            self.stakes.setText("%s<br><b>%s:</b> %d" % (
                self.stakes.text(), Local.strings[Local.CRISIS_FILTER][22],
                prompt.prestige_at_risk()))

        for row, advice in zip(self.advisors, prompt.advisors()):
            row.setSide(prompt.decider.id)
            row.setStrings()
            row.setAdvice(advice)

        choices = prompt.choices
        self.acceptButton.setText(prompt.question_text())
        self.declineButton.setText(prompt.accept_text()
                                   if prompt.is_challenge_phase
                                   else prompt.back_down_text())
        # The summit is the third answer, and it only exists once the crisis is
        # actually escalating: offering talks before anyone has contested
        # anything would be meaningless.
        self.councilButton.setText(Local.strings[Local.MULTIPLAYER][64])
        self.proposeButton.setText(prompt.proposal_text())
        self.proposeButton.setVisible("summit" in choices)
        self.proposeButton.setEnabled("summit" in choices)
        self.acceptButton.setVisible(bool(choices))
        self.declineButton.setVisible(bool(choices))
        # Hand-off line for two players at one keyboard.
        parent = self.parent
        hotseat = bool(parent is not None and getattr(getattr(parent, "world", None), "twoPFlag", False)
                       and not getattr(parent, "network_game", False))
        if hotseat:
            self.handoff.setText(
                "<b style='color:%s'>Pass the keyboard to %s</b> \u2014 this answer is theirs."
                % (Theme.superpower_color(prompt.decider.id).name(), who))
        self.handoff.setVisible(hotseat)
        if hotseat:
            self._startGuard()
        else:
            self._guardSerial = getattr(self, "_guardSerial", 0) + 1
            self._guard = False
            self.declineButton.setEnabled(True)
            self.acceptButton.setEnabled(True)
        if not self.isVisible():
            # Open at the size the content wants (the scroll area keeps it from
            # outgrowing the screen: the screen-fit filter clamps it on show).
            hint = self._scroll.sizeHint()
            self.resize(max(720, hint.width() + 40), max(300, hint.height() + 90))
        self.show()
        self.raise_()
        self.activateWindow()
        # Let the window paint with the rule-based verdicts first, then ask the
        # council in the background: a model that takes ten seconds must not
        # keep the crisis off the screen for ten seconds.
        if self._councilAvailable():
            QTimer.singleShot(0, self.askCouncil)

    def release_guard(self):
        """End the click guard now (for automated crawlers and tests only)."""
        self._guardSerial = getattr(self, "_guardSerial", 0) + 1
        self._endGuard()

    def guard_active(self):
        """True during the short click guard after a hot-seat prompt appears."""
        return bool(self._guard)

    def _startGuard(self):
        """Ignore clicks for ~400 ms after a prompt appears."""
        self._guard = True
        self._guardSerial = getattr(self, "_guardSerial", 0) + 1
        serial = self._guardSerial
        for button in (self.declineButton, self.proposeButton, self.acceptButton):
            button.setEnabled(False)
        QTimer.singleShot(400, lambda: self._endGuard(serial))

    def _endGuard(self, serial=None):
        if serial is not None and serial != getattr(self, "_guardSerial", 0):
            return          # a newer prompt has restarted the guard
        self._guard = False
        prompt = self._prompt
        choices = prompt.choices if prompt is not None else ()
        self.declineButton.setEnabled(True)
        self.acceptButton.setEnabled(True)
        self.proposeButton.setEnabled("summit" in choices)

    def _councilAvailable(self):
        """Whether it is worth asking the model at all.

        Both conditions matter: a usable key, and the player having chosen the
        AI advisors rather than the historical bench.  With the bench selected
        the four rule-based lines already on screen *are* the council, and
        re-asking would produce the same four lines by a longer route.
        """
        from GameLogic.AdvisorChat import ai_advisors_enabled
        parent = self.parent
        if parent is None or getattr(parent, "run_council", None) is None:
            return False
        config = getattr(parent, "llm_config", None)
        return bool(getattr(config, "usable", False)) and ai_advisors_enabled(config)

    def askCouncil(self):
        """Replace the rule-based verdicts with what the council actually says."""
        parent = self.parent
        prompt = self._prompt
        if parent is None or prompt is None:
            return
        if getattr(self, "_council_busy", False):
            # The timer and the button can both fire, and a new prompt can
            # arrive while the old one is still being answered.  Ask again once
            # the call in flight is back, for whichever prompt is then showing.
            self._council_again = True
            return
        self._council_busy = True
        self.councilButton.setEnabled(False)
        try:
            # The council that speaks is the one belonging to the side that has
            # to decide, which in a contested crisis is not necessarily the
            # player whose turn it is.
            lines = parent.run_council(situation=prompt.context_text(),
                                       headline=prompt.news, rounds=1,
                                       side=prompt.decider.id)
        except Exception as exc:
            self._council_busy = False
            import html
            reason = str(exc)
            if len(reason) > 120:
                reason = reason[:117] + "..."
            # Tooltips auto-detect rich text, and the reason can carry a
            # server's response body: escape it and keep it short.
            self.councilButton.setToolTip(
                "the council is unavailable: %s" % html.escape(reason))
            self.councilButton.setEnabled(True)
            return
        self._council_busy = False
        self.councilButton.setEnabled(True)
        # The call pumps the event loop while it waits, so the crisis can have
        # been answered (or replaced by the next prompt) in the meantime.  Lines
        # written for the old prompt must not land on the new one.
        if self._prompt is not prompt or not self.isVisible():
            if getattr(self, "_council_again", False):
                self._council_again = False
                if self._prompt is not None and self.isVisible():
                    QTimer.singleShot(0, self.askCouncil)
            return
        self._council_again = False
        if not lines:
            return
        for row in self.advisors:
            row.setSide(prompt.decider.id)
            row.setStrings()
        from GameLogic.Advisors import roster
        spoken = dict(lines)
        for index, row in enumerate(self.advisors):
            team = roster(prompt.decider.id)
            if index >= len(team):
                continue
            # run_council returns (line, round, advisor) per key: the round and
            # the advisor are there for the debate view, which needs to order
            # the transcript; here only the sentence matters.
            entry = spoken.get(team[index].key)
            if entry:
                row.setAdvice(entry[0])

    def _answer(self, verb):
        """Translate the button that was pressed into one of the duel's verbs."""
        prompt = self._prompt
        if self._guard:
            return
        if verb == "__accept__":
            if prompt is not None and prompt.is_challenge_phase:
                verb = "contest"
            elif prompt is not None and prompt.is_summit_phase:
                verb = "yes"
            else:
                verb = "tough"
        elif verb == "__decline__":
            if prompt is not None and prompt.is_challenge_phase:
                verb = "accept"
            elif prompt is not None and prompt.is_summit_phase:
                verb = "no"
            else:
                verb = "back_down"
        self.hide()
        self.decided.emit(str(verb))
