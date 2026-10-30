"""
What the other superpower was thinking.

At the fifth difficulty level the opponent is a language model, and it returns a
short justification with every plan.  Without somewhere to read it, the level is
a black box: the player sees a policy appear and has no idea whether it came
from a strategy or from a misunderstanding of the briefing.

The log is shown one year behind.  Reading the opponent's reasoning for the year
you are currently deciding would turn a game about judging intentions into a
game about reading the answer key.
"""

import html

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QHeaderView,
                             QLabel, QPushButton, QSplitter, QTableWidget,
                             QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

import Local
import Theme
from GameLogic.LLMOpponent import ACTION_DISPLAY_NAMES
from Theme import Palette


class OpponentLogWindow(QDialog):
    """A year-by-year record of the model opponent's plans and reasons."""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("Opponent's reasoning")
        self.setModal(False)
        self.setMinimumSize(720, 480)

        root = QVBoxLayout()
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        self.status = QLabel()
        # The text is built here, with every dynamic part escaped, so it is
        # always rich text: left on auto-detect, a line with entities and no tags
        # was shown with the entities spelled out.
        self.status.setTextFormat(Qt.RichText)
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: %s;" % Palette.TEXT_MUTED.name())
        root.addWidget(self.status)

        splitter = QSplitter(Qt.Vertical)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Year", "Actions", "Reasoning"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(True)
        self.table.itemSelectionChanged.connect(self.showDetail)
        splitter.addWidget(self.table)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setStyleSheet(
            "QTextEdit { background-color: %s; border: 1px solid %s; border-radius: 6px;"
            " padding: 8px; }" % (Palette.CHART_BG.name(), Palette.BORDER.name()))
        splitter.addWidget(self.detail)
        splitter.setSizes([240, 200])
        root.addWidget(splitter, 1)

        buttons = QHBoxLayout()
        self.refreshButton = QPushButton("Refresh")
        self.refreshButton.clicked.connect(self.refresh)
        self.closeButton = QPushButton("Close")
        self.closeButton.clicked.connect(self.close)
        buttons.addWidget(self.refreshButton)
        buttons.addStretch(1)
        buttons.addWidget(self.closeButton)
        root.addLayout(buttons)

        self.setLayout(root)
        self.refresh()

    # -- data ---------------------------------------------------------------

    def rows(self):
        """Every plan except the one for the year in progress."""
        log = list(getattr(self.parent, "llm_log", []))
        world = getattr(self.parent, "world", None)
        if world is not None:
            # Hide the current year: its outcome has not happened yet.
            log = [entry for entry in log if entry[0] < world.year]
        return log

    def action_label(self, action):
        """The readable name of a policy verb."""
        return ACTION_DISPLAY_NAMES.get(action, action or "?")

    def label(self, target_id):
        """The country name for a policy target, falling back to the id."""
        world = getattr(self.parent, "world", None)
        if world is None:
            return str(target_id)
        return Local.countryName(target_id)

    def spend_report(self, opponent):
        """What the model has cost so far, from the client that is really used."""
        try:
            if opponent.backend == "decisions" and not opponent.offline:
                return opponent.jev.spend_report()
            return opponent.client.spend_report()
        except Exception:
            return ""

    def status_html(self, opponent):
        """The header: who is playing, what it cost, and why it is not the model."""
        parts = [html.escape(opponent.status_line())]
        config = opponent.config
        if opponent.offline:
            note = ("The built-in AI is playing this level because \u201cUse the "
                    "built-in AI\u201d is switched on under AI \u2192 AI "
                    "settings\u2026.")
        elif not config.usable:
            note = ("The built-in AI is playing this level because no API key is "
                    "set; add one under AI \u2192 AI settings\u2026 to hand "
                    "this side to a language model.")
        else:
            note = ""
            spend = self.spend_report(opponent)
            if spend:
                parts.append(html.escape(spend))
        text = " &nbsp;&middot;&nbsp; ".join(parts)
        fallback = getattr(opponent, "last_fallback", None)
        if fallback and not note and getattr(opponent, "disabled", False):
            text += ("<br>The model %s; the built-in AI plays the rest of this game "
                     "(saving the AI settings tries again)."
                     % html.escape(fallback[1]))
        if note:
            text += "<br>" + html.escape(note)
        try:
            from GameLogic.AdvisorChat import advisor_status
            advisors = advisor_status(getattr(self.parent, "_advisor_client", None))
        except Exception:
            advisors = ""
        if advisors:
            text += "<br>" + html.escape(advisors)
        return text

    def refresh(self):
        opponent = getattr(self.parent, "llm_opponent", None)
        if opponent is None:
            self.status.setText(
                "This game is not using a language-model opponent. Start an "
                "<b>Adaptive (LLM)</b> game to see its reasoning here.")
        else:
            self.status.setText(self.status_html(opponent))
        entries = self.rows()
        self.table.setRowCount(0)
        for row, (year, source, reasoning, actions) in enumerate(reversed(entries)):
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(year)))
            if actions:
                # The target is shown as its country name: the raw numeric id
                # told the player nothing at all.
                summary = ", ".join("%s: %s (%d)"
                                    % (self.action_label(a), self.label(t), lvl)
                                    for a, t, lvl in actions[:4])
                if len(actions) > 4:
                    summary += " \u2026"
            elif source == "fallback":
                summary = "built-in AI played"
            elif source == "crisis":
                # A judgement about the player's move, not a policy of its own;
                # "stood pat" would misdescribe it.
                summary = "contested your move"
            else:
                summary = "stood pat"
            self.table.setItem(row, 1, QTableWidgetItem(summary))
            self.table.setItem(row, 2, QTableWidgetItem(reasoning or "\u2014"))
        self.table.resizeRowsToContents()
        if self.table.rowCount():
            self.table.selectRow(0)
        else:
            opponent = getattr(self.parent, "llm_opponent", None)
            why = ""
            if opponent is not None and not opponent.offline \
                    and not opponent.config.usable:
                why = (" No API key is set, so the built-in AI is playing; "
                       "configure one under AI \u2192 AI settings\u2026.")
            self.detail.setHtml(
                "<span style='color:%s'>Nothing recorded yet. The opponent's "
                "reasoning appears here after its first move.%s</span>"
                % (Palette.TEXT_DIM.name(), html.escape(why)))

    def source_label(self, source):
        """What produced this entry, in words the player reads."""
        return {"llm": "the model",
                "jev": "the model",
                "fallback": "the built-in AI (the model did not provide this move)",
                "mock": "the built-in AI",
                "crisis": "its answer to your move"}.get(source)

    def showDetail(self):
        row = self.table.currentRow()
        entries = list(reversed(self.rows()))
        if row < 0 or row >= len(entries):
            return
        year, source, reasoning, actions = entries[row]
        lines = ["<b style='color:%s'>%d</b>" % (Palette.ACCENT.name(), year)]
        source_text = self.source_label(source)
        if source_text:
            lines.append("<span style='color:%s'>source: %s</span>"
                         % (Palette.TEXT_DIM.name(), source_text))
        lines.append("<p style='color:%s'>%s</p>"
                     % (Palette.TEXT.name(),
                        # Model output, shown in a rich-text widget: markup in it
                        # must be text, not tags.
                        html.escape(str(reasoning)) if reasoning
                        else "no explanation given"))
        if actions:
            lines.append("<b>Actions</b><ul>")
            for action, target, level in actions:
                lines.append("<li>%s: %s, step %d</li>"
                             % (self.action_label(action), self.label(target),
                                level))
            lines.append("</ul>")
        self.detail.setHtml("".join(lines))

    def showEvent(self, event):
        self.refresh()
        super().showEvent(event)
