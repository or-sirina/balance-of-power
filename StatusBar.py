"""
The strip above the map: turn prompt, hovered-country readout and the
world-tension gauge.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDockWidget, QHBoxLayout, QLabel, QSizePolicy, QWidget

import Local
import Theme
from Theme import Palette
from Widgets import MusicBar, TensionBar


class StatusBar(QDockWidget):

    def __init__(self, parent):
        super(StatusBar, self).__init__()
        self.parent = parent
        self.setTitleBarWidget(QWidget())
        self.setFeatures(QDockWidget.NoDockWidgetFeatures)

        container = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(10)

        self.label = QLabel()
        self.label.setFont(Theme.font(11, bold=True))
        self.label.setTextFormat(Qt.RichText)

        self.hover = QLabel()
        self.hover.setFont(Theme.font(9))
        self.hover.setStyleSheet("color: %s;" % Palette.TEXT_MUTED.name())
        self.hover.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.hover.setTextFormat(Qt.RichText)

        self.aiStatus = QLabel()
        self.aiStatus.setFont(Theme.font(8))
        self.aiStatus.setStyleSheet("color: %s;" % Palette.ACCENT.name())
        self.aiStatus.setVisible(False)

        # Music sits next to the tension gauge: both are ambient state the
        # player glances at rather than reads.
        self.music = MusicBar(self)

        self.tension = TensionBar()
        self.tension.setToolTip(Local.strings[Local.TENSION][1])
        # "World tension: Nuclear exchange" plus "DEFCON 1 \u00b7 est. \u00b150" did not
        # fit the gauge's default 250 px and was cut to "World tension: Brink of\u2026".
        self.tension.setMinimumWidth(340)

        layout.addWidget(self.label)
        layout.addWidget(self.hover, 1)
        layout.addWidget(self.aiStatus)
        layout.addWidget(self.music)
        layout.addWidget(self.tension)
        container.setLayout(layout)
        self.setWidget(container)
        self.setFixedHeight(34)
        self.setLabel(Local.strings[Local.MAIN_PANEL][14])

    def refreshMusic(self):
        """Called when the music state changes from anywhere else."""
        self.music.refresh()

    def setLabel(self, text):
        self.label.setText(text)

    def setAiStatus(self, text):
        self.aiStatus.setText(text or "")
        self.aiStatus.setVisible(bool(text))

    def setHoverText(self, text):
        self.hover.setText(text or "")

    def setTension(self, value, detail="", war=False):
        """Show the gauge.  ``war`` is True only once the exchange has happened.

        "Nuclear exchange" and DEFCON 1 mean the bombs have flown; a world that
        merely reads as maximum tension (the peaceful end of the game included)
        is "Brink of war" at DEFCON 2.
        """
        strings = Local.strings[Local.TENSION]
        if value < 0.25:
            caption = strings[3]
        elif value < 0.6:
            caption = strings[4]
        elif value < 0.9 or not war:
            caption = strings[5]
        else:
            caption = strings[6]
        # The gauge used to print "World tension 5/5" for a calm world: that is
        # the DEFCON scale (5 = peace), but it read as "maximum".  Say the word
        # first and keep the DEFCON number as a labelled secondary detail, so
        # the text and the lit blocks agree.
        defcon = 5 - int(round(min(1.0, max(0.0, value)) * 4))
        if not war:
            defcon = max(2, defcon)
        short = Local.strings[Local.TENSION][1]          # "World tension"
        # ``detail`` arrives as "World tension \u00b1N" (or empty).
        if detail.startswith(short):
            detail = detail[len(short):].strip()
            if detail:
                detail = "est. " + detail
        extra = "DEFCON %d" % defcon + ((" \u00b7 " + detail) if detail else "")
        text = "%s: %s" % (short, caption)
        self.tension.setTension(value, text, extra)
        # The gauge elides what does not fit; the whole line is always here.
        self.tension.setToolTip("%s \u00b7 %s" % (text, extra))
