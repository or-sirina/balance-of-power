"""
Settings for the language-model opponent and the advisor chat.

Deliberately plain: an endpoint, a model id, a key, and a way to prove it works.
The "Test connection" button matters more than it looks — on a corporate network
the difference between "no key", "wrong model id", "proxy blocks it" and "TLS is
intercepted and the CA is not trusted" is four different conversations with IT,
and a one-line diagnosis saves three of them.
"""

import copy
import html

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
                             QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QSpinBox, QTextEdit, QVBoxLayout,
                             QWidget)
from Widgets import FitScrollArea

from GameLogic.AdvisorChat import ai_advisors_enabled, chat_config, set_ai_advisors
from GameLogic.JevClient import JevClient
from GameLogic.LLMClient import DEFAULT_BASE_URL, DEFAULT_CHAT_MODEL, DEFAULT_MODEL, LLMClient, LLMError, MOCK_MODEL
from Theme import Palette

#: A few models worth offering by name; the field stays free-text because the
#: catalogue changes faster than this list will.
MODEL_SUGGESTIONS = (
    # Decisions models (the opponent): these answer typed questions, not prose.
    "typesafe/jev-1.13",
    # Text models (the advisors).  A decisions model here would answer nothing:
    # the advisors need an endpoint that writes sentences.
    "qwen/qwen3.8-27b",
    "qwen/qwen3.8-27b:free",
    "google/gemini-3.8-flash",
    "anthropic/claude-sonnet-4.5",
    "openai/gpt-5.1",
    "meta-llama/llama-3.3-70b-instruct",
    "mistralai/mistral-large",
    "qwen/qwen3.8-max-0902",
    "deepseek/deepseek-v4.1-flash",
    MOCK_MODEL,
)

#: Shown only in the advisor field.
ADVISOR_MODEL_SUGGESTIONS = (
    "qwen/qwen3.8-27b",
    "qwen/qwen3.8-27b:free",
    "google/gemini-3.8-flash",
    "anthropic/claude-sonnet-4.5",
    "openai/gpt-5.1",
    "meta-llama/llama-3.3-70b-instruct",
    "mistralai/mistral-large",
)


class LLMSettingsWindow(QDialog):
    """Configure, and prove, the model connection."""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("AI settings")
        self.setModal(False)
        self.setMinimumWidth(620)

        root = QVBoxLayout()
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        intro = QLabel(
            "The <b>Adaptive (LLM)</b> difficulty level hands the opposing superpower "
            "to a language model. Any OpenAI-compatible endpoint works; OpenRouter is "
            "the default. Without a key it uses the same opponent as Multipolar.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: %s;" % Palette.TEXT_MUTED.name())
        root.addWidget(intro)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self.offlineBox = QCheckBox("Use the built-in AI (no network calls)")
        form.addRow(self.offlineBox)

        self.baseEdit = QLineEdit()
        self.baseEdit.setPlaceholderText(DEFAULT_BASE_URL)
        form.addRow("Endpoint", self.baseEdit)

        self.modelBox = QComboBox()
        self.modelBox.setEditable(True)
        self.modelBox.addItems(MODEL_SUGGESTIONS)
        form.addRow("Model", self.modelBox)

        # -- the advisors, which are a separate system with a separate model --
        self.advisorsBox = QCheckBox(
            "AI advisors (uncheck for the historical advisors)")
        self.advisorsBox.setToolTip(
            "Off: the four advisors answer from the game state, with no network. "
            "On: each one is given a role, beliefs and a manner of speech, and "
            "answers through a text model.")
        form.addRow(self.advisorsBox)

        self.chatModelBox = QComboBox()
        self.chatModelBox.setEditable(True)
        self.chatModelBox.addItems(ADVISOR_MODEL_SUGGESTIONS)
        self.chatModelBox.setToolTip(
            "Use a chat model here. Some models only answer structured questions "
            "and cannot write the advisors' replies.")
        form.addRow("Advisor model", self.chatModelBox)

        self.reasoningBox = QCheckBox("Let the advisor model think first")
        self.reasoningBox.setToolTip(
            "Some models spend their whole answer budget thinking and return "
            "nothing. Leave this off unless you need it.")
        form.addRow(self.reasoningBox)

        self.keyEdit = QLineEdit()
        self.keyEdit.setEchoMode(QLineEdit.Password)
        self.keyEdit.setPlaceholderText("sk-or-\u2026 (stored in your user data directory)")
        reveal = QPushButton("\u25c9")
        reveal.setFixedWidth(30)
        reveal.setCheckable(True)
        reveal.setToolTip("Show the key")
        reveal.toggled.connect(
            lambda shown: self.keyEdit.setEchoMode(
                QLineEdit.Normal if shown else QLineEdit.Password))
        key_row = QHBoxLayout()
        key_row.addWidget(self.keyEdit, 1)
        key_row.addWidget(reveal)
        form.addRow("API key", key_row)

        self.tempSpin = QDoubleSpinBox()
        self.tempSpin.setRange(0.0, 2.0)
        self.tempSpin.setSingleStep(0.1)
        form.addRow("Temperature", self.tempSpin)

        self.tokensSpin = QSpinBox()
        self.tokensSpin.setRange(128, 8192)
        self.tokensSpin.setSingleStep(128)
        form.addRow("Max answer tokens", self.tokensSpin)

        self.timeoutSpin = QSpinBox()
        self.timeoutSpin.setRange(5, 300)
        self.timeoutSpin.setSuffix(" s")
        form.addRow("Timeout", self.timeoutSpin)

        self.callsSpin = QSpinBox()
        self.callsSpin.setRange(0, 10000)
        self.callsSpin.setSpecialValueText("no limit")
        self.callsSpin.setToolTip(
            "The most model calls one game may make, in total: the opponent's "
            "moves and the advisors share this count. When it is used up the "
            "built-in AI and the historical advisors take over.")
        form.addRow("Model calls per game", self.callsSpin)
        root.addLayout(form)

        note = QLabel(
            "Environment variables win over these fields: "
            "<code>BOP_LLM_BASE_URL</code>, <code>BOP_LLM_MODEL</code>, "
            "<code>BOP_LLM_API_KEY</code> (or <code>OPENROUTER_API_KEY</code>). "
            "Behind a proxy, set <code>HTTPS_PROXY</code>; if TLS is intercepted, "
            "point <code>REQUESTS_CA_BUNDLE</code> at your corporate CA file.")
        note.setWordWrap(True)
        note.setStyleSheet("color: %s;" % Palette.TEXT_DIM.name())
        root.addWidget(note)

        self.result = QTextEdit()
        self.result.setReadOnly(True)
        self.result.setMaximumHeight(96)
        self.result.setStyleSheet(
            "QTextEdit { background-color: %s; border: 1px solid %s; }"
            % (Palette.CHART_BG.name(), Palette.BORDER.name()))
        root.addWidget(self.result)

        buttons = QHBoxLayout()
        self.testButton = QPushButton("Test connection")
        self.testButton.clicked.connect(self.do_test)
        self.saveButton = QPushButton("Save")
        self.saveButton.setObjectName("primary")
        self.saveButton.clicked.connect(self.do_save)
        self.closeButton = QPushButton("Close")
        self.closeButton.clicked.connect(self.close)
        buttons.addWidget(self.testButton)
        buttons.addStretch(1)
        buttons.addWidget(self.closeButton)
        buttons.addWidget(self.saveButton)

        # Scroll the fields, keep the buttons pinned: a 1366x768 laptop at
        # 125-150% scaling is shorter than the form.
        scrolled = QVBoxLayout()
        scrolled.setContentsMargins(0, 0, 0, 0)
        scrolled.setSpacing(0)
        content = QWidget()
        content.setLayout(root)
        scrolled.addWidget(FitScrollArea(content), 1)
        buttons.setContentsMargins(16, 6, 16, 12)
        scrolled.addLayout(buttons)
        self.setLayout(scrolled)
        self.reload()

    # -- state --------------------------------------------------------------

    def reload(self):
        config = self.parent.llm_config
        self.offlineBox.setChecked(config.offline or config.model == MOCK_MODEL)
        self.baseEdit.setText(config.base_url)
        self.modelBox.setCurrentText(config.model)
        self.chatModelBox.setCurrentText(config.chat_model)
        self.advisorsBox.setChecked(ai_advisors_enabled(config))
        self.reasoningBox.setChecked(not config.disable_reasoning)
        self.keyEdit.setText(config.api_key)
        self.tempSpin.setValue(config.temperature)
        self.tokensSpin.setValue(config.max_tokens)
        self.timeoutSpin.setValue(int(config.timeout))
        self.callsSpin.setValue(int(config.max_requests or 0))
        self.result.clear()
        if not config.api_key:
            self.say("No API key set. The Adaptive level will use the built-in AI.",
                     Palette.WARN)
        else:
            note = ""
            opponent = getattr(self.parent, "llm_opponent", None)
            client = getattr(opponent, "client", None) if opponent is not None else None
            # The schema downgrade is worth showing: it means the provider is
            # being used in a weaker mode, and it is the kind of thing that
            # otherwise only shows up as the occasional odd answer.
            if client is not None and getattr(client, "schema_note", ""):
                note = " &nbsp;<span style='color:%s'>%s</span>" % (
                    Palette.WARN.name(), client.schema_note)
            self.say("Opponent: %s.&nbsp; Advisors: %s.%s"
                     % (config.describe(),
                        (config.chat_model if ai_advisors_enabled(config)
                         else "the historical advisors"),
                        note),
                     Palette.TEXT_MUTED)

    def collect(self, config=None):
        """Read the form back, without saving.

        With no argument the running game's configuration is updated in place.
        Pass a copy to read the form without touching anything live, which is
        what "Test connection" does.
        """
        live = config is None
        if live:
            config = self.parent.llm_config
        config.base_url = (self.baseEdit.text().strip() or DEFAULT_BASE_URL).rstrip("/")
        config.model = self.modelBox.currentText().strip() or DEFAULT_MODEL
        config.chat_model = (self.chatModelBox.currentText().strip()
                             or DEFAULT_CHAT_MODEL)
        config.disable_reasoning = not self.reasoningBox.isChecked()
        if live:
            set_ai_advisors(self.advisorsBox.isChecked())
        # An emptied field falls back to the environment's key, which the note
        # under the form promises is honoured.
        config.api_key = self.keyEdit.text().strip() or config._env_key
        config.temperature = self.tempSpin.value()
        config.max_tokens = self.tokensSpin.value()
        config.timeout = float(self.timeoutSpin.value())
        config.max_requests = self.callsSpin.value() or None
        config.offline = self.offlineBox.isChecked() or config.model == MOCK_MODEL
        return config

    def say(self, text, colour=None):
        self.result.setText("<span style='color:%s'>%s</span>"
                            % ((colour or Palette.TEXT).name(), text))
        self.result.repaint()

    # -- actions ------------------------------------------------------------

    def do_save(self):
        config = self.collect()
        try:
            path = config.save()
        except OSError as exc:
            self.say("Could not write the settings: %s" % exc, Palette.DANGER)
            return
        # A running game picks the change up on its next turn.
        if getattr(self.parent, "llm_opponent", None) is not None:
            self.parent.llm_opponent.config = config
            self.parent.llm_opponent.client.config = config
            # New settings deserve a fresh try, even if the model had been
            # failing and the opponent had given up on it.
            self.parent.llm_opponent.reset_failures()
        advisors = getattr(self.parent, "_advisor_client", None)
        if advisors is not None and getattr(advisors, "advisor_breaker", None):
            advisors.advisor_breaker.reset()
        self.say("Saved to %s" % path, Palette.OK)

    def do_test(self):
        # Work on a copy: testing a half-edited form must not change the
        # settings of the game that is running, nor the advisors switch.
        config = self.collect(copy.copy(self.parent.llm_config))
        # A probe is not a move: it must not be counted against the game's calls.
        config.game_budget = None
        if config.offline or config.model == MOCK_MODEL:
            self.say("Built-in AI selected: no connection needed.", Palette.OK)
            return
        if not config.api_key:
            self.say("No API key, so there is nothing to test.", Palette.WARN)
            return
        # Test what the game will actually call.  A decisions model (Jev) is
        # reached at a different endpoint from a chat model, so asking it a chat
        # question reports a 400 for a connection that is perfectly healthy; and
        # the advisors use a chat model of their own.
        steps = []
        if config.resolved_backend() == "decisions":
            steps.append(("Opponent (decisions)", self._ping_decisions, config))
        else:
            steps.append(("Opponent", self._ping_chat, config))
        if self.advisorsBox.isChecked():
            # Only a separate advisor model needs its own probe; when the
            # opponent is itself a chat model it is the same call.
            advisors = chat_config(config)
            if advisors is not config:
                steps.append(("Advisors", self._ping_chat, advisors))
        self.testButton.setEnabled(False)
        self.say("Contacting %s \u2026 (gives up after about %d s)"
                 % (html.escape(config.base_url),
                    int(config.timeout * 1.5 * len(steps))), Palette.TEXT_MUTED)
        from Async import run_blocking

        def run_all():
            report = []
            for label, ping, target in steps:
                try:
                    report.append((label, True, ping(target)))
                except LLMError as exc:
                    report.append((label, False, str(exc)))
                except Exception as exc:         # never crash the dialog
                    report.append((label, False, "%s: %s" % (type(exc).__name__, exc)))
            return report

        try:
            report = run_blocking(run_all, timeout=config.timeout * 1.5 * len(steps) + 5,
                                  parent=self)
        except TimeoutError as exc:
            self.say("Timed out: %s" % html.escape(str(exc)), Palette.DANGER)
            return
        except Exception as exc:                     # never crash the dialog
            self.say("Failed: %s: %s" % (type(exc).__name__, html.escape(str(exc))),
                     Palette.DANGER)
            return
        finally:
            self.testButton.setEnabled(True)
        lines = []
        for label, ok, text in report:
            if ok:
                lines.append("%s: connection works. The model replied: %s"
                             % (html.escape(label), html.escape(text.strip()[:120])))
            else:
                lines.append("%s failed: %s" % (html.escape(label), html.escape(text)))
        good = all(ok for _, ok, _ in report)
        self.say("<br>".join(lines), Palette.OK if good else Palette.DANGER)

    @staticmethod
    def _ping_chat(config):
        client = LLMClient(config)
        return client.chat([{"role": "user",
                             "content": "Reply with the single word: ready"}],
                           timeout=config.timeout)

    @staticmethod
    def _ping_decisions(config):
        client = JevClient(config)
        answer = client.noul({"purpose": "connection test"}, "ready",
                             "Is this a connection test? Answer yes.",
                             timeout=config.timeout)
        return "answered a decision question (%.0f%% yes)" % (answer.noul * 100)
