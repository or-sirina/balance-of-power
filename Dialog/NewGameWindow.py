"""
The new-game dialog: difficulty, side and player count.

Five difficulties now.  The fifth keeps Multipolar's rules but hands the
opposing superpower to a language model, so the dialog also shows what that
level is currently configured to talk to — otherwise a player picks it and
wonders why nothing happened.
"""

from PyQt5.QtWidgets import (QBoxLayout, QButtonGroup, QDialog, QGroupBox, QLabel,
                             QPushButton, QRadioButton)

import Local
import Theme
from Theme import Palette
from constants import LEVEL_COUNT, LEVEL_LLM

#: Where each difficulty's *name* lives in the WINDOW_NEWGAME string group.
#: Indices 0-3 are the original four levels; the fifth is 13 because
#: index 4 in that group is already the word "USA".
LEVEL_NAME_INDEX = (0, 1, 2, 3, 13)

#: Layout of the dialog: how many radio buttons each column holds is fixed by
#: the tallest group, so nothing else needs to know the level count.
LEVEL_GROUP = 0
SIDE_GROUP = 1
MODE_GROUP = 2


class NewGameWindow(QDialog):

    def __init__(self, parent):
        super(NewGameWindow, self).__init__(parent)
        self.parent = parent
        self.buttonGroups = [QButtonGroup() for i in range(3)]
        mainLayout = QBoxLayout(QBoxLayout.TopToBottom)
        columnLayout = QBoxLayout(QBoxLayout.LeftToRight)
        buttonLayout = QBoxLayout(QBoxLayout.LeftToRight)
        column = [QBoxLayout(QBoxLayout.TopToBottom) for i in range(3)]
        level = QGroupBox()
        self.levelOpt = [QRadioButton(str(i)) for i in range(LEVEL_COUNT)]
        for i in self.levelOpt:
            column[0].addWidget(i)
        side = QGroupBox()
        mode = QGroupBox()
        self.sideOpt = [QRadioButton(str(i)) for i in range(2)]
        self.modeOpt = [QRadioButton(str(i)) for i in range(2)]
        for i, j in zip(self.sideOpt, self.modeOpt):
            column[1].addWidget(i)
            column[2].addWidget(j)
        # Keep the three groups the same height so the dialog does not look
        # lopsided now that one column is taller than the others.
        for i in range(LEVEL_COUNT - 2):
            column[1].addSpacing(21)
            column[2].addSpacing(21)
        for group, col in zip((level, side, mode), column):
            group.setLayout(col)
            columnLayout.addWidget(group)
        for i, j in zip(self.levelOpt, range(LEVEL_COUNT)):
            self.buttonGroups[LEVEL_GROUP].addButton(i, j)
        for i, k, j in zip(self.sideOpt, self.modeOpt, range(2)):
            self.buttonGroups[SIDE_GROUP].addButton(i, j)
            self.buttonGroups[MODE_GROUP].addButton(k, j)
        self.levelGroup = level
        self.sideGroup = side
        self.modeGroup = mode

        self.topText = QLabel()
        self.topText.setWordWrap(True)

        # Live hint about the fifth level's backend, so the player knows whether
        # an API key is configured before committing to a game.
        self.llmHint = QLabel()
        self.llmHint.setWordWrap(True)
        self.llmHint.setFont(Theme.font(8))
        self.llmHint.setStyleSheet("color: %s;" % Palette.TEXT_DIM.name())
        for button in self.modeOpt:
            button.toggled.connect(self.updateLlmHint)
        for i, button in enumerate(self.levelOpt):
            button.toggled.connect(self.updateLlmHint)
            if i == LEVEL_LLM - 1:
                button.setToolTip(Local.strings[Local.WINDOW_NEWGAME][14])

        self.cancelButton = QPushButton("Cancel")
        self.cancelButton.released.connect(self.close)
        self.okButton = QPushButton("OK")
        self.okButton.released.connect(self.doSetNewGame)
        buttonLayout.addWidget(self.cancelButton)
        buttonLayout.addWidget(self.okButton)
        mainLayout.addWidget(self.topText)
        mainLayout.addLayout(columnLayout)
        mainLayout.addWidget(self.llmHint)
        mainLayout.addLayout(buttonLayout)
        self.setLayout(mainLayout)
        self.setMinimumSize(520, 360)
        self.setModal(True)
        self.setStrings()
        self.updateLlmHint()

    # -- level-5 hint -------------------------------------------------------

    def updateLlmHint(self):
        # Two human players: nobody plays the opposing superpower for the model,
        # so the hint about its key is noise.
        if not self.levelOpt[LEVEL_LLM - 1].isChecked() or self.modeOpt[1].isChecked():
            self.llmHint.setText("")
            return
        config = getattr(self.parent, "llm_config", None)
        if config is None:
            from GameLogic.LLMClient import LLMConfig
            config = LLMConfig()
        if config.offline or not config.api_key:
            self.llmHint.setText(
                "<span style='color:%s'>No API key configured, so this level will play "
                "exactly like Multipolar. Set one in AI \u2192 AI settings\u2026 "
                "(or the <code>OPENROUTER_API_KEY</code> environment variable).</span>"
                % Palette.WARN.name())
        else:
            self.llmHint.setText("Opponent model: <b>%s</b> at %s"
                                 % (config.model, config.base_url))

    def showEvent(self, event):
        self.updateLlmHint()
        super().showEvent(event)

    # -- actions ------------------------------------------------------------

    def doSetNewGame(self):
        """Action performed on releasing the 'OK' button"""
        confirm = getattr(self.parent, "confirm_abandon_game", None)
        if confirm is not None and not confirm():
            return      # keep the current game; the dialog stays open
        self.parent.saveOptions()
        level = self.buttonGroups[LEVEL_GROUP].checkedId() + 1
        side = self.buttonGroups[SIDE_GROUP].checkedId()
        mode = (self.buttonGroups[MODE_GROUP].checkedId() == 1)
        # ``hide``, not ``close``: closing a dialog counts as cancelling it, and
        # the start screen tells the two apart by ``accepted``/``rejected``.
        self.hide()
        self.parent.start_local_game(level, mode, side)
        self.accept()

    def setStrings(self):
        g = Local.WINDOW_NEWGAME
        for i in range(2):
            self.sideOpt[i].setText(Local.strings[g][i + 4])
            self.modeOpt[i].setText(Local.strings[g][i + 6])
        for i in range(LEVEL_COUNT):
            self.levelOpt[i].setText(Local.strings[g][LEVEL_NAME_INDEX[i]])
        self.levelGroup.setTitle(Local.strings[g][10])
        self.sideGroup.setTitle(Local.strings[g][9])
        self.modeGroup.setTitle(Local.strings[g][8])
        self.topText.setText(Local.strings[g][11])
        self.setWindowTitle(Local.strings[g][12])
