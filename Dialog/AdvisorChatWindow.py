"""
Sit down with one of your advisors and argue about the crisis.

The four disagree because they weigh different things; see
:mod:`GameLogic.Advisors`.  This window makes that usable: pick a face, read who
they are and what they care about, and put a question to them.  If a crisis is
open, the headline is handed to them automatically, so "should I back down?" is
answered about the actual decision in front of you.

Two panels behind the conversation are what make the advice weighable rather
than merely charming.  Every recommendation ends with a country, a direction and
a confidence, and the note under the reply repeats it; the panel on the right
keeps the running score — how often each advisor has been right, how confident
they usually sound, and what they remember of this game (see
:mod:`GameLogic.AdvisorMemory`).  A prediction is scored as soon as the world is
one turn older, which happens the next time an advisor is asked or this window is
reopened.
"""

import html

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import (QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QTextEdit, QVBoxLayout)

import Local
import Theme
from GameLogic.AdvisorChat import AdvisorSession
from GameLogic.Advisors import roster
from Theme import Palette

OPENING_QUESTION = "What is your assessment of our position?"
#: How many remembered lines the panel shows.  The advisor gets a few more; the
#: panel is for the player, who only needs the gist.
RECORDED_EVENTS = 5

#: The record panel's wording for the verdict computed in
#: :mod:`GameLogic.AdvisorMemory`.  A verdict not listed here is shown as it is,
#: so the panel keeps working if that module changes its words.
VERDICT_WORDS = {
    "well calibrated": "close to the mark",
    "overconfident": "sounds surer than it is",
    "underconfident": "sounds less sure than it is",
}


def _advisor_colour(side, advisor):
    """The ring colour this advisor is drawn with elsewhere in the interface."""
    try:
        from GraphicsLoader import ADVISOR_RINGS
        index = getattr(advisor, "index", 0)
        return ADVISOR_RINGS[index % len(ADVISOR_RINGS)]
    except (ImportError, AttributeError, IndexError, TypeError):
        return Palette.TEXT


class AdvisorChatWindow(QDialog):
    """A conversation with one of the four advisors."""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("Advisors")
        self.setModal(False)
        self.setMinimumSize(820, 440)
        self.resize(1060, 620)
        self.sessions = {}
        self.messages = []
        self.side = 0
        self.index = 0

        root = QVBoxLayout()
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)
        root.addLayout(self._build_header())

        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(self._build_roster(), 0)
        body.addWidget(self._build_conversation(), 1)
        body.addWidget(self._build_record(), 0)
        root.addLayout(body, 1)
        root.addLayout(self._build_input())
        self.setLayout(root)
        self.reload()

    # -- construction -------------------------------------------------------

    def _build_header(self):
        header = QHBoxLayout()
        self.title = QLabel()
        self.title.setFont(Theme.font(13, bold=True))
        self.subtitle = QLabel()
        self.subtitle.setStyleSheet("color: %s;" % Palette.TEXT_MUTED.name())
        self.subtitle.setWordWrap(True)
        column = QVBoxLayout()
        column.setSpacing(2)
        column.addWidget(self.title)
        column.addWidget(self.subtitle)
        header.addLayout(column, 1)
        self.clearButton = QPushButton("New conversation")
        self.clearButton.clicked.connect(self.do_reset)
        header.addWidget(self.clearButton, 0, Qt.AlignTop)
        return header

    def _panel(self, width):
        """One of the bordered side panels."""
        frame = QFrame()
        frame.setFixedWidth(width)
        frame.setStyleSheet(
            "QFrame { background-color: %s; border: 1px solid %s; border-radius: 8px; }"
            % (Palette.PANEL.name(), Palette.BORDER.name()))
        return frame

    def _build_roster(self):
        frame = self._panel(136)
        column = QVBoxLayout()
        column.setContentsMargins(10, 10, 10, 10)
        column.setSpacing(8)
        self.portrait = QLabel()
        self.portrait.setAlignment(Qt.AlignCenter)
        column.addWidget(self.portrait, 0, Qt.AlignHCenter)
        self.who = QLabel()
        self.who.setWordWrap(True)
        self.who.setAlignment(Qt.AlignCenter)
        self.who.setFont(Theme.font(9, bold=True))
        column.addWidget(self.who)
        self.role = QLabel()
        self.role.setWordWrap(True)
        self.role.setAlignment(Qt.AlignCenter)
        self.role.setStyleSheet("color: %s; border: none;" % Palette.TEXT_MUTED.name())
        column.addWidget(self.role)
        self.bias = QLabel()
        self.bias.setWordWrap(True)
        self.bias.setAlignment(Qt.AlignCenter)
        self.bias.setStyleSheet("color: %s; border: none;" % Palette.ACCENT.name())
        column.addWidget(self.bias)
        column.addStretch(1)
        self.picker = QComboBox()
        self.picker.currentIndexChanged.connect(self.select_advisor)
        column.addWidget(self.picker)
        frame.setLayout(column)
        return frame

    def _build_conversation(self):
        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setStyleSheet(
            "QTextEdit { background-color: %s; border: 1px solid %s; border-radius: 8px;"
            " padding: 8px; }" % (Palette.CHART_BG.name(), Palette.BORDER.name()))
        return self.transcript

    def _build_record(self):
        """The scoreboard: who has been right, and what they remember."""
        frame = self._panel(248)
        column = QVBoxLayout()
        column.setContentsMargins(8, 8, 8, 8)
        column.setSpacing(6)
        self.record = QTextEdit()
        self.record.setReadOnly(True)
        self.record.setStyleSheet(
            "QTextEdit { background-color: %s; border: none; }" % Palette.PANEL.name())
        column.addWidget(self.record, 1)
        frame.setLayout(column)
        return frame

    def _build_input(self):
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText(
            "Ask about the crisis, a country, or what to do next\u2026")
        self.input.returnPressed.connect(self.do_ask)
        self.sendButton = QPushButton("Ask")
        self.sendButton.setObjectName("primary")
        self.sendButton.clicked.connect(self.do_ask)
        # E2: turn four separate conversations into one argument.  This is what
        # the advisors are for - one voice at a time is just a chatbot.
        self.councilButton = QPushButton("Convene the council")
        self.councilButton.setToolTip(
            "Put the same situation to all four at once and hear them disagree")
        self.councilButton.clicked.connect(self.do_convene)
        self.status = QLabel()
        self.status.setStyleSheet("color: %s;" % Palette.TEXT_DIM.name())
        row.addWidget(self.status, 0)
        row.addWidget(self.input, 1)
        row.addWidget(self.sendButton)
        row.addWidget(self.councilButton)
        return row

    # -- state --------------------------------------------------------------

    def reload(self):
        """Follow the game: new side, new advisors, an open crisis, or none."""
        world = getattr(self.parent, "world", None)
        if world is None:
            return
        # The advisors belong to whoever is at this keyboard.
        side = getattr(self.parent, "local_side", world.human)
        if world.twoPFlag:
            side = world.human
        side = 0 if int(side) == 0 else 1
        if side != self.side or self.picker.count() == 0:
            self.side = side
            self._fill_picker()
        self.sessions.clear()
        self.select_advisor(max(0, self.picker.currentIndex()))
        self.refresh_context()

    def _fill_picker(self):
        self.picker.blockSignals(True)
        self.picker.clear()
        for advisor in roster(self.side):
            self.picker.addItem(advisor.name)
        self.picker.blockSignals(False)

    def current_headline(self):
        """The crisis headline, if one is on the table."""
        world = self.parent.world
        for news in getattr(world, "news", ()):
            if getattr(news, "isQuestioned", False):
                return getattr(news, "text", "")
        if self.parent.duel is not None:
            prompt = self.parent.duel.prompt()
            if prompt:
                return prompt.get("headline", "")
        return None

    def current_news(self):
        """The News object behind the current crisis, if there is one.

        ``current_headline()`` returns the text for display; the council needs
        the object, because the offline verdicts are computed from the move it
        records.
        """
        world = getattr(self.parent, "world", None)
        if world is None:
            return None
        for news in getattr(world, "news", ()):
            if getattr(news, "isQuestioned", False):
                return news
        duel = getattr(self.parent, "duel", None)
        return getattr(duel, "news", None)

    def refresh_context(self):
        """Say which advisory bench is in play, and whether a crisis is open.

        Two different systems answer in this window - the historical bench of
        the original and the model-backed advisors - and the player chose
        between them, so saying which one is talking is the least the window can
        do.  The model's name is shown when there is one.
        """
        import Local
        from GameLogic.AdvisorChat import ai_advisors_enabled
        config = getattr(self.parent, "llm_config", None)
        extra = Local.strings[Local.ADVISOR_EXTRA]
        if ai_advisors_enabled(config) and getattr(config, "usable", False):
            who = "%s: %s" % (extra[2], config.chat_model)
            colour = Palette.OK.name()
        else:
            who = extra[3]
            colour = Palette.TEXT_MUTED.name()
        headline = self.current_headline()
        parts = ["<span style='color:%s'>%s</span>" % (colour, who)]
        if headline:
            parts.append("<span style='color:%s'>Crisis open</span>"
                         % Palette.WARN.name())
        self.status.setText(" &nbsp;·&nbsp; ".join(parts))

    def select_advisor(self, index):
        if index < 0:
            return
        team = roster(self.side)
        if index >= len(team):
            return
        self.index = index
        advisor = team[index]
        # Keep the selector and the portrait/name panel on the same advisor
        # whatever path got us here.
        if self.picker.count() != len(team) or self.picker.itemText(index) != advisor.name:
            self._fill_picker()
        if self.picker.currentIndex() != index:
            self.picker.blockSignals(True)
            self.picker.setCurrentIndex(index)
            self.picker.blockSignals(False)
        cards = self.parent.graphics.advisorLarge.get(self.side, [])
        if index < len(cards):
            pixmap = cards[index]
            self.portrait.setPixmap(pixmap)
            self.portrait.setFixedSize(pixmap.size())
        self.who.setText(advisor.name)
        self.role.setText(advisor.role)
        self.bias.setText(advisor.blurb)
        self.title.setText("Crisis advisory: %s" % Local.strings[
            Local.DATA_COUNTRIES + self.side][Local.CTRY_NAME])
        self.subtitle.setText(
            "Ask your advisors about the crisis, a country, or next year's plan. "
            "They weigh different things, so they often disagree.")
        self.show_transcript()

    # -- the record panel ---------------------------------------------------

    def refresh_record(self):
        """Redraw the scoreboard for the side currently at the keyboard."""
        session = self.session()
        memory = session.memory
        parts = ["<div style='line-height:135%'>"]
        parts.append(
            "<p style='margin:0'><b>Track record</b><br>"
            "<span style='color:%s'>Each forecast is checked next turn against "
            "what the country actually did.</span></p>"
            % Palette.TEXT_MUTED.name())
        for row in memory.scoreboard(self.side):
            current = row["key"] == session.advisor.key
            colour = Palette.ACCENT.name() if current else Palette.TEXT.name()
            if row["resolved"]:
                detail = ("%d of %d right (%.0f%%); it claims %.0f%% on average"
                          % (row["hits"], row["resolved"], 100.0 * row["rate"],
                             100.0 * row["mean_confidence"]))
                if row["open"]:
                    detail += ", %d open" % row["open"]
                verdict = VERDICT_WORDS.get(row["verdict"], row["verdict"]) or ""
                detail += ". %s" % (verdict[:1].upper() + verdict[1:])
            else:
                detail = ("no scored predictions yet"
                          + (", %d open" % row["open"] if row["open"] else ""))
            parts.append(
                "<p style='margin-top:10px; margin-bottom:0'>"
                "<b style='color:%s'>%s</b><br>"
                "<span style='color:%s'>%s</span></p>"
                % (colour, html.escape(row["name"]), Palette.TEXT_MUTED.name(),
                   html.escape(detail)))
            for entry in row["recent"][-3:]:
                parts.append("<p style='margin:2px 0 0 0'><span style='color:%s'>%s</span></p>"
                             % (_verdict_colour(entry), html.escape(_recent_line(entry))))
        events = memory.events_for(self.side)[-RECORDED_EVENTS:]
        if events:
            parts.append("<p style='margin-top:12px; margin-bottom:0'><b>What they "
                         "remember</b></p>")
            for event in events:
                parts.append("<p style='margin:2px 0 0 0'><span style='color:%s'>%s</span></p>"
                             % (Palette.TEXT_MUTED.name(),
                                html.escape(str(event.get("text", "")))))
        parts.append("</div>")
        self.record.setHtml("".join(parts))

    # -- conversation -------------------------------------------------------

    def session(self):
        if self.index not in self.sessions:
            config = self.parent.llm_config
            # The game's shared advisor client, so every conversation draws on
            # the same per-game call budget instead of each starting its own.
            shared = getattr(self.parent, "advisor_client", None)
            self.sessions[self.index] = AdvisorSession(
                self.side, self.index, config=config,
                client=shared() if shared is not None else None,
                execute=self.parent.llm_execute)
        return self.sessions[self.index]

    def show_transcript(self):
        session = self.session()
        # The transcript is rebuilt from the message list every time rather than
        # appended to: inserting HTML at the end of a QTextEdit merges the new
        # paragraph into the previous one, which made consecutive replies run
        # together on one line.
        self.messages = []
        advisor = session.advisor
        self.messages.append((advisor.name,
                              "I have read the latest briefing. "
                              "What would you like to know?", Palette.ACCENT))
        self.render()
        self.refresh_record()
        if not session.history:
            # Greet with a first assessment once per session.
            self.ask(OPENING_QUESTION, record=False)

    def append(self, speaker, text, colour):
        self.messages.append((speaker, text, colour))
        self.render()

    def render(self):
        parts = ["<div style='line-height:130%'>"]
        for speaker, text, colour in self.messages:
            parts.append(
                "<p style='margin-top:12px; margin-bottom:0'>"
                "<b style='color:%s'>%s</b><br>"
                "<span style='color:%s'>%s</span></p>"
                % (colour.name(), speaker, Palette.TEXT.name(),
                   html.escape(text).replace("\n", "<br>")))
        parts.append("</div>")
        self.transcript.setHtml("".join(parts))
        self.transcript.moveCursor(QTextCursor.End)

    def do_convene(self):
        """E2: run the council and render the debate as one transcript."""
        parent = self.parent
        runner = getattr(parent, "run_council", None)
        if runner is None:
            return
        headline = self.current_headline()
        question = self.input.text().strip()
        if question:
            self.input.clear()
        self.councilButton.setEnabled(False)
        self.status.setText("The council is convening\u2026")
        try:
            spoken = runner(headline=self.current_news(), rounds=2)
        except Exception as exc:
            self.status.setText("The council could not be reached (%s)." % exc)
            self.councilButton.setEnabled(True)
            return
        self.councilButton.setEnabled(True)
        self.status.setText("")
        side = self.side
        self.messages = []
        self.messages.append(
            ("The council",
             "Convened on: %s" % (headline or question or "the present situation"),
             Palette.ACCENT))
        if not spoken:
            self.append("The council", "Nobody had anything to say.", Palette.TEXT_DIM)
            return
        # Round one in roster order, then the rebuttals, so the transcript reads
        # as a meeting rather than as four unrelated answers.
        for round_number, label in ((1, "First positions"), (2, "Answers")):
            round_lines = [(key, value) for key, value in spoken.items()
                           if value[1] == round_number]
            if not round_lines:
                continue
            self.append(label, "", Palette.TEXT_MUTED)
            order = [a.key for a in roster(side)]
            round_lines.sort(key=lambda item: order.index(item[0])
                             if item[0] in order else len(order))
            for key, (text, _round, advisor) in round_lines:
                self.append(advisor.name, text, _advisor_colour(side, advisor))
        self.refresh_record()

    def do_reset(self):
        self.sessions.pop(self.index, None)
        self.show_transcript()

    def do_ask(self):
        question = self.input.text().strip()
        if not question:
            return
        self.input.clear()
        self.ask(question)

    def ask(self, question, record=True):
        advisor = roster(self.side)[self.index]
        if record:
            self.append("You", question, Palette.TEXT_MUTED)
        # The "thinking" state lives in the status line rather than in the
        # transcript: rewriting a QTextEdit's HTML to remove a placeholder
        # mangles the surrounding markup, which is exactly what it used to do.
        self.sendButton.setEnabled(False)
        self.input.setEnabled(False)
        self.status.setText("<span style='color:%s'>%s is considering\u2026</span>"
                            % (Palette.TEXT_DIM.name(), advisor.name))
        self.status.repaint()
        session = self.session()
        error = ""
        try:
            reply = session.ask(self.parent.world, question,
                                self.current_headline())
        except Exception as exc:                      # never take the game down
            reply = "I cannot answer that just now."
            error = str(exc)
        self.append(advisor.name, reply, Palette.ACCENT)
        # The recorded forecast, with the advisor's record against it: the
        # player should be able to see how much this voice is worth.
        note = session.prediction_note()
        if note:
            self.append("Recorded", note, Palette.TEXT_DIM)
        self.refresh_record()
        self.sendButton.setEnabled(True)
        self.input.setEnabled(True)
        self.input.setFocus()
        self.refresh_context()
        if error:
            # The reason belongs on the status line, not in the advisor's mouth.
            self.status.setText("The advisor could not answer (%s)."
                                % html.escape(error))

    def showEvent(self, event):
        self.reload()
        super().showEvent(event)


def _recent_line(entry):
    """One scored prediction as a line: "1984 Poland up 70%: right"."""
    try:
        year, country, direction, confidence, hit = entry[:5]
    except (TypeError, ValueError):
        return str(entry)
    words = {1: "up", 0: "hold", -1: "down"}
    return "%s %s %s %d%%: %s" % (year, country,
                                  words.get(int(direction), "hold"),
                                  int(confidence),
                                  "right" if int(hit) else "wrong")


def _verdict_colour(entry):
    try:
        return (Palette.OK if int(entry[4]) else Palette.DANGER).name()
    except (TypeError, ValueError, IndexError):
        return Palette.TEXT_MUTED.name()
