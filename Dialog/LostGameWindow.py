from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QBoxLayout, QDialog, QLabel, QPushButton
import Local

class LostGameWindow(QDialog):

    def __init__(self, parent):
        super(LostGameWindow, self).__init__(parent)
        mainLayout = QBoxLayout(QBoxLayout.TopToBottom)
        mainLayout.setAlignment(Qt.AlignCenter)
        self.quitButton = QPushButton("OK")
        self.quitButton.setStyleSheet(
            "QPushButton { color: white; background-color: #303030; border: 1px solid #777;"
            " border-radius: 4px; padding: 5px 18px; }"
            "QPushButton:hover { background-color: #444; }")
        self.quitButton.released.connect(self.hide)
        # Filled by showUp() before the window is ever displayed; the text used
        # to be a lorem-ipsum placeholder from the skeleton.
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.setStyleSheet("LostGameWindow { background-color: black; }")
        mainLayout.addWidget(self.text)
        mainLayout.addWidget(self.quitButton)
        self.setLayout(mainLayout)
        self.setFixedSize(400, 300)
    
    def showUp(self, accidental, who=None):
        """``who`` names the superpower that started the war when it was not
        the player at this keyboard (hot-seat, or the other player's push)."""
        strings = Local.strings[Local.WINDOW_ENDGAME]
        message = strings[0] % strings[2 if accidental else 1]
        if accidental and len(strings) > 3 and "<br>" in message:
            # Nobody chose it: the dice fired on a rung of the ladder.  Swap
            # the first sentence, keep the rest of the epitaph.
            message = strings[3] + message[message.index("<br>"):]
        elif who:
            message = message.replace("You have", "%s has" % who, 1)
        str = "<font color=\"white\"><p align=\"center\">%s<br><br></p></font>" % message
        self.text.setText(str)
        self.setVisible(True)
