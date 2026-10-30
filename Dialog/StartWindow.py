"""
The start screen: what you see before the game, instead of the game.

Launching straight into a position is a habit left over from a single-purpose
build.  A player arriving at this game needs three things the map cannot give
them: a way in (a new game, the last one, a network game), a plain statement of
what the thing *is*, and who made it.  All three fit on one screen.

The screen is a plain widget rather than a modal dialog, because it is a place
the player can sit and read rather than a box to be dismissed.  It owns no game
state: every button either calls a method that already existed on
:class:`MainWindow` or closes itself, so nothing here can put the game into a
state the menu bar could not.

``main.py`` shows this instead of the game.  The tools and the test suite build
``MainWindow`` directly and never see it, which is deliberate: the start screen
is for people, not for harnesses.  ``BOP_NO_START_MENU=1`` (or ``--no-menu``)
skips it for anyone who wants the old behaviour.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                             QPushButton, QScrollArea, QVBoxLayout, QWidget)

import Local
import Theme
from Theme import Palette

#: What this build is, in the order a newcomer needs it.
ABOUT_GAME = [
    ("The game",
     "A turn-based simulation of the Cold War, 1982 to 1990. You play one "
     "superpower; the other is played by the computer or by a second person. "
     "There is no territory to take: you spend money, weapons, troops and "
     "treaties on the 78 minor countries, and your score is the sum of their "
     "opinion of you, weighted by what each country is worth."),
    ("How a turn works",
     "Each year you enact policies and end the turn. A provocative move can be "
     "contested, and a contested move opens a crisis: the two sides take turns "
     "backing down or pushing the confrontation one rung further down a "
     "nine-rung ladder. The last rung is a nuclear exchange, which nobody wins. "
     "A summit gives both sides a third way out, if both will attend."),
    ("The five difficulties",
     "The first four are the original game's, with a less forgiving opponent and "
     "a narrower margin each time. The fifth hands the opposing superpower to a "
     "language model, which reads the board and argues its case in the reasoning "
     "window. Without an API key it plays like Multipolar."),
    ("If you know the original",
     "A model opponent that chooses which of your moves to contest, advisors who "
     "can be convened as a council, and summits as a third way out of a crisis."),
]

CREDITS = [
    ("Original design", "Chris Crawford, 1985 and 1988, published by Mindscape. "
                        "This is a remake of the 1990 Edition."),
    ("Python port", "Tomasz Ciborski, 2020, from the original Pascal sources."),
    ("Fork author", "Vasilii Vinogradov, who added the model opponent, the "
                    "advisors, summits and network play."),
    ("Thanks", "The rules follow the original Pascal sources, which are public."),
]


def _card(title, body):
    """One titled paragraph, drawn as a panel."""
    box = QFrame()
    box.setStyleSheet(
        "QFrame { background-color: %s; border: 1px solid %s; border-radius: 8px; }"
        % (Palette.PANEL.name(), Palette.BORDER.name()))
    layout = QVBoxLayout()
    layout.setContentsMargins(14, 10, 14, 12)
    layout.setSpacing(6)
    heading = QLabel(title)
    heading.setFont(Theme.font(11, bold=True))
    heading.setStyleSheet("color: %s; border: none;" % Palette.ACCENT.name())
    text = QLabel(body)
    text.setWordWrap(True)
    text.setFont(Theme.font(9))
    text.setStyleSheet("color: %s; border: none;" % Palette.TEXT.name())
    layout.addWidget(heading)
    layout.addWidget(text)
    box.setLayout(layout)
    return box


class StartWindow(QWidget):
    """The screen shown before the game."""

    def __init__(self, parent=None, window=None):
        super(StartWindow, self).__init__(parent)
        #: The MainWindow this screen will hand over to.  Kept under a name of
        #: our own because QWidget.parent is a method.
        self.window = window
        self.setWindowTitle("Balance of Power")
        self.setMinimumSize(900, 520)
        self.setStyleSheet("background-color: %s;" % Palette.WINDOW.name())

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(24, 18, 24, 20)
        body.setSpacing(22)
        body.addWidget(self._build_actions(), 0)
        body.addWidget(self._build_reading(), 1)
        root.addLayout(body, 1)
        root.addWidget(self._build_footer())
        self.setLayout(root)

    # -- pieces -------------------------------------------------------------

    def _build_header(self):
        """Name, edition and the two flags: the whole premise in one band."""
        band = QFrame()
        band.setStyleSheet(
            "QFrame { background-color: %s; border: none;"
            " border-bottom: 1px solid %s; }"
            % (Palette.WINDOW_TOP.name(), Palette.BORDER.name()))
        layout = QHBoxLayout()
        layout.setContentsMargins(26, 20, 26, 18)
        layout.setSpacing(16)

        graphics = getattr(self.window, "graphics", None)
        icon = QLabel()
        if graphics is not None and not graphics.progIcon.isNull():
            icon.setPixmap(graphics.progIcon.scaled(
                64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        icon.setStyleSheet("border: none;")
        layout.addWidget(icon, 0, Qt.AlignVCenter)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        name = QLabel("BALANCE OF POWER")
        name.setFont(Theme.font(22, bold=True))
        name.setStyleSheet("color: %s; border: none;" % Palette.TEXT.name())
        subtitle = QLabel("The 1990 Edition, remade")
        subtitle.setFont(Theme.font(10))
        subtitle.setStyleSheet("color: %s; border: none;" % Palette.TEXT_MUTED.name())
        titles.addWidget(name)
        titles.addWidget(subtitle)
        layout.addLayout(titles, 1)

        # The two flags are the shortest possible statement of what the game is
        # about, and they are already loaded.
        if graphics is not None:
            for side in (0, 1):
                flag = QLabel()
                flag.setPixmap(graphics.flag[side].scaled(
                    72, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                flag.setStyleSheet("border: none;")
                layout.addWidget(flag, 0, Qt.AlignVCenter)
        band.setLayout(layout)
        return band

    def _build_actions(self):
        """The way in.  Deliberately short, and in the order of likely use."""
        column = QWidget()
        column.setFixedWidth(248)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(8)

        self.continueButton = QPushButton("Continue")
        self.continueButton.setObjectName("primary")
        self.continueButton.setToolTip("Continue your saved game")
        self.newButton = QPushButton("New game")
        self.networkButton = QPushButton("Multiplayer…")
        self.mailButton = QPushButton("Play by mail…")
        self.advisorButton = QPushButton("Ask the advisors…")
        self.settingsButton = QPushButton("AI settings…")
        self.helpButton = QPushButton("Manual")
        self.quitButton = QPushButton("Quit")

        self.continueButton.clicked.connect(self.doContinue)
        self.newButton.clicked.connect(self.doNewGame)
        self.networkButton.clicked.connect(self.doNetwork)
        self.mailButton.clicked.connect(self.doMail)
        self.advisorButton.clicked.connect(self.doAdvisors)
        self.settingsButton.clicked.connect(self.doSettings)
        self.helpButton.clicked.connect(self.doHelp)
        self.quitButton.clicked.connect(self.doQuit)

        for button in (self.continueButton, self.newButton):
            button.setMinimumHeight(38)
            layout.addWidget(button)
        # The likeliest action holds the focus, so Enter does the obvious thing.
        self.continueButton.setFocus()
        layout.addSpacing(10)
        for button in (self.networkButton, self.mailButton):
            button.setMinimumHeight(30)
            layout.addWidget(button)
        layout.addSpacing(10)
        for button in (self.advisorButton, self.settingsButton, self.helpButton):
            layout.addWidget(button)
        layout.addStretch(1)
        layout.addWidget(self.quitButton)
        column.setLayout(layout)
        return column

    def _build_reading(self):
        """Everything else: what the game is, and who made it."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: %s; width: 10px; }"
            "QScrollBar::handle:vertical { background: %s; border-radius: 5px; }"
            % (Palette.PANEL.name(), Palette.BORDER_LIGHT.name()))

        inner = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(2, 2, 10, 2)
        layout.setSpacing(10)
        for title, body in ABOUT_GAME:
            layout.addWidget(_card(title, body))
        layout.addWidget(self._credits_heading())
        for title, body in CREDITS:
            layout.addWidget(_card(title, body))
        layout.addStretch(1)
        inner.setLayout(layout)
        scroll.setWidget(inner)
        return scroll

    def _credits_heading(self):
        label = QLabel("Credits")
        label.setFont(Theme.font(13, bold=True))
        label.setStyleSheet("color: %s; border: none; padding-top: 6px;"
                            % Palette.TEXT.name())
        return label

    def _build_footer(self):
        band = QFrame()
        band.setStyleSheet(
            "QFrame { background-color: %s; border: none;"
            " border-top: 1px solid %s; }"
            % (Palette.WINDOW_BOTTOM.name(), Palette.BORDER.name()))
        layout = QHBoxLayout()
        layout.setContentsMargins(26, 8, 26, 8)
        self.footer = QLabel()
        self.footer.setFont(Theme.font(8))
        self.footer.setStyleSheet("color: %s; border: none;"
                                  % Palette.TEXT_DIM.name())
        # Real characters, not entities: QLabel only interprets HTML when it
        # decides the text is rich, and a string starting with "Saves" is not.
        self.footer.setText(
            "Saves and settings: %s" % _user_dir())
        layout.addWidget(self.footer, 1)
        # Music belongs on this screen too: it starts playing here, and the
        # player should be able to change it before committing to a game.
        from Widgets import MusicBar
        self.music = MusicBar(self)
        layout.addWidget(self.music, 0)
        self.quitHint = QLabel()
        self.quitHint.setFont(Theme.font(8))
        self.quitHint.setStyleSheet("color: %s; border: none;"
                                    % Palette.TEXT_DIM.name())
        self.quitHint.setText("Esc: quit")
        layout.addWidget(self.quitHint, 0, Qt.AlignRight)
        band.setLayout(layout)
        return band

    # -- state --------------------------------------------------------------

    def refresh(self):
        """Enable what is actually possible on this machine right now."""
        has_save = self._has_save()
        self.continueButton.setEnabled(has_save)
        self.continueButton.setToolTip(
            "Continue your saved game" if has_save
            else "No saved game yet")
        self.music.refresh()
        network = getattr(self.window, "menu", None) is not None
        self.networkButton.setEnabled(network)
        self.mailButton.setEnabled(network)

    def _has_save(self):
        import os
        import Paths
        return os.path.exists(Paths.user_file("save.dat"))

    # -- actions ------------------------------------------------------------

    def _enter_game(self):
        """Close this screen and show the game instead.

        The game window has no stored geometry of its own, and shown from here it
        would come up at its minimum size on a large display.  It is sized once,
        to the screen, the first time the player actually enters the game.
        """
        if self.window is not None:
            self._sizeToScreen(self.window)
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()
        self.close()

    @staticmethod
    def _sizeToScreen(window):
        from PyQt5.QtWidgets import QApplication
        if getattr(window, "_startSized", False):
            return
        window._startSized = True
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        width = min(int(available.width() * 0.9), 1600)
        height = min(int(available.height() * 0.9), 1000)
        window.resize(max(width, 960), max(height, 520))
        window.move(available.center() - window.rect().center())

    def doContinue(self):
        """Resume the saved game, or say why that is not possible.

        The window read the save when it was built; a save that was unreadable
        then left it holding a fresh placeholder game.  Read it again now, so a
        damaged file is reported here instead of the player being dropped into
        a game they never chose.
        """
        window = self.window
        if window is not None and hasattr(window, "loadWorld"):
            if not window.loadWorld():
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.critical(
                    self, "Balance of Power",
                    getattr(window, "load_error", "")
                    or "There is no saved game to continue.")
                return
        self._enter_game()

    def doNewGame(self):
        """Ask for the game's settings first; enter the game only once it starts.

        Entering before the dialog meant Cancel (or Esc) left the player in the
        placeholder world the window holds until a game is begun.
        """
        window = self.window
        dialog = getattr(window, "newGameWindow", None)
        if dialog is None:
            self._enter_game()
            return

        def accepted():
            settle()
            self._enter_game()

        def rejected():
            settle()

        def settle():
            for signal, slot in ((dialog.accepted, accepted),
                                 (dialog.rejected, rejected)):
                try:
                    signal.disconnect(slot)
                except TypeError:
                    pass

        dialog.accepted.connect(accepted)
        dialog.rejected.connect(rejected)
        dialog.show()
        dialog.raise_()

    def doNetwork(self):
        self._enter_game()
        window = self.window
        if window is not None and hasattr(window, "open_multiplayer"):
            window.open_multiplayer()

    def doMail(self):
        """Play-by-mail lives in the lobby, so open the lobby."""
        self.doNetwork()

    def doAdvisors(self):
        self._enter_game()
        window = self.window
        if window is not None and hasattr(window, "open_advisor_chat"):
            window.open_advisor_chat()

    def doSettings(self):
        """The AI settings are worth opening before a game starts."""
        window = self.window
        if window is None or not hasattr(window, "open_llm_settings"):
            return
        window.open_llm_settings()
        dialog = getattr(window, "llm_settingsWindow", None)
        if dialog is not None:
            dialog.raise_()

    def doHelp(self):
        window = self.window
        if window is None or not hasattr(window, "open_help"):
            return
        window.open_help()
        dialog = getattr(window, "helpWindow", None)
        if dialog is not None:
            dialog.raise_()

    def doQuit(self):
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.doQuit()
            return
        super().keyPressEvent(event)


def _python_version():
    import platform
    return platform.python_version()


def _user_dir():
    import Paths
    try:
        return Paths.user_dir()
    except (AttributeError, OSError):
        return "your home directory"
