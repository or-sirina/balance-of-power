#!/usr/bin/env python3
"""Display-only crisis dialogue; fake clients, no external service or credentials.

    QT_QPA_PLATFORM=offscreen python3 tests/test_crisis_dialogue.py
"""

import _isolate  # noqa: F401 -- must precede game imports

import copy
import json
import os
import pickle
import random
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import QApplication, QDialog

from Async import run_blocking
from Dialog.NewsWindow import NewsWindow
from GameLogic import CrisisHandler as CH
from GameLogic.AdvisorChat import chat_config, set_ai_advisors
from GameLogic.CrisisDialogue import generate, snapshot
from GameLogic.LLMClient import LLMConfig, LLMError
from GameLogic.World import World
from constants import GOVTAID, LEVEL_LLM


class FakeClient:
    def __init__(self, config):
        self.config = chat_config(config)
        self.calls = []
        self.error = None
        self.bad_reply = None
        self.thread = None
        self.messages = None

    def chat(self, messages, **kwargs):
        self.thread = threading.get_ident()
        self.messages = messages
        facts = json.loads(messages[-1]["content"])
        self.calls.append(facts)
        if self.error:
            raise self.error
        if self.bad_reply is not None:
            return self.bad_reply
        answer = {
            "reaction": "%s: %s over %s." % (facts["diplomatic_speaker"],
                                              facts["event"], facts["country"]["country"]),
            "advisors": {a["key"]: "Model advice from %s about %s." % (
                a["name"], facts["country"]["country"]) for a in facts["advisors"]},
        }
        if facts.get("language") == "ru":
            answer["reaction"] = "Заявление: " + answer["reaction"]
            answer["advisors"] = {key: "Совет: " + text for key, text in answer["advisors"].items()}
        return json.dumps(answer)


class Host(QDialog):
    def __init__(self, world):
        super().__init__()
        self.world = world
        self.llm_config = LLMConfig(model="typesafe/jev-1.13", chat_model="test/prose",
                                    api_key="fake-local-test-key", timeout=1)
        self.client = FakeClient(self.llm_config)
        pix = QPixmap(12, 12)
        pix.fill()
        self.graphics = SimpleNamespace(icon=[QIcon() for _ in range(40)],
                                        flag=[pix for _ in range(80)],
                                        advisorSmall={side: [pix] * 4 for side in (0, 1)})
        self.during_request = None
        self.loading_seen = False
        news, world.news = world.news, []
        self.window = NewsWindow(self)
        world.news = news
        self.window.show()

    def advisor_client(self):
        self.client.config = chat_config(self.llm_config)
        return self.client

    def llm_execute(self, fn, timeout=None):
        self.loading_seen = self.window.dialogueStatus.text() == "LLM diplomacy: loading\u2026"
        if self.during_request:
            callback, self.during_request = self.during_request, None
            gate = threading.Event()

            def dispatch():
                try:
                    callback()
                finally:
                    gate.set()

            QTimer.singleShot(0, dispatch)
            original = fn

            def fn():
                gate.wait(1)
                return original()
        return run_blocking(fn, timeout=1, tick_ms=5)


class CrisisDialogueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def setUp(self):
        set_ai_advisors(True)
        self.hosts = []

    def tearDown(self):
        for host in self.hosts:
            host.window.hide()
            host.hide()
        self.app.processEvents()
        set_ai_advisors(True)

    def make(self, actor=0, human=0, world=None):
        world = world or World(LEVEL_LLM, False, human)
        if not world.news:
            CH.doPolicy(world, world.country[actor], world.country[9], GOVTAID, 4)
        news = next(n for n in reversed(world.news) if n.action == GOVTAID)
        host = Host(world)
        self.hosts.append(host)
        nw = host.window
        nw.ctryList.setCurrentIndex(nw.sortedCountries.index(9))
        nw.doRefreshNews(5)
        nw.table.selectRow(nw.news.index(news))
        return host, news

    def flush(self):
        # The first dispatch runs the queued refresh (and its worker); a second
        # dispatch handles a newer event queued while that worker pumped Qt.
        for _ in range(4):
            self.app.processEvents()

    def begin(self, host, news):
        # Force the computer to stand for predictable UI assertions. All
        # mechanics-invariance comparisons below use the original calculation.
        with patch.object(CH, "gimpt", return_value=-100):
            CH.doCrisis(host.window, host.world, news)
        self.flush()

    def test_both_challenge_directions_and_both_player_sides(self):
        for human in (0, 1):
            for actor in (0, 1):
                with self.subTest(human=human, actor=actor):
                    host, news = self.make(actor=actor, human=human)
                    self.begin(host, news)
                    self.assertEqual(len(host.client.calls), 1)
                    facts = host.client.calls[0]
                    self.assertEqual(facts["player"],
                                     CH.Local.strings[CH.Local.DATA_COUNTRIES + human][CH.Local.CTRY_NAME])
                    self.assertEqual(facts["event"], "challenge" if human == actor else "stood_firm")
                    self.assertEqual(host.client.config.model, "test/prose")
                    self.assertTrue(host.loading_seen)
                    self.assertEqual(host.window.dialogueStatus.text(), "LLM diplomacy: ready.")
                    self.assertTrue(all(label.text().startswith("Model advice") for label in host.window.advice))
                    self.assertNotEqual(host.client.thread, threading.get_ident())

    def test_snapshot_is_frozen_and_does_not_touch_world_or_rng(self):
        host, news = self.make()
        self.begin(host, news)
        before, rng = pickle.dumps(host.world), random.getstate()
        request = snapshot(host.world, news, 1, "challenge")
        self.assertEqual(pickle.dumps(host.world), before)
        self.assertEqual(random.getstate(), rng)
        old_facts = json.loads(request.facts)
        host.world.year += 1
        news.old = 5
        reply = generate(request, host.client)
        self.assertEqual(host.client.calls[-1]["year"], old_facts["year"])
        self.assertEqual(len(reply.advisors), 4)

    def test_russian_output_is_explicit_and_reply_has_portable_result_shape(self):
        host, news = self.make()
        self.begin(host, news)
        request = snapshot(host.world, news, 1, "challenge", language="ru")
        reply = generate(request, host.client)
        self.assertIn("EVERY reaction and advisor sentence in Russian", host.client.messages[0]["content"])
        self.assertEqual(host.client.calls[-1]["language"], "ru")
        self.assertEqual(reply.advice, reply.advisors)
        self.assertTrue(reply.used_model)
        self.assertEqual(reply.status, "Дипломатия LLM: ответ получен.")

    def test_english_only_crisis_lines_for_russian_request_are_rejected(self):
        host, news = self.make()
        self.begin(host, news)
        request = snapshot(host.world, news, 1, "challenge", language="ru")
        host.client.bad_reply = json.dumps({"reaction": "We will stand firm.",
                                           "advisors": {key: "We should negotiate."
                                                        for key in request.advisor_keys}})
        with self.assertRaises(LLMError):
            generate(request, host.client)

    def test_escalation_concession_and_restore_are_display_only(self):
        host, news = self.make()
        self.begin(host, news)
        CH.hangTough(host.window, host.world, host.world.USSR)
        self.flush()
        self.assertEqual(host.client.calls[-1]["event"], "stood_firm")
        before = pickle.dumps(host.world)
        CH.resumeCrisis(host.window, host.world)
        self.flush()
        # resumeCrisis updates presentation scratch fields by design; it must
        # not advance the ladder or alter policy/relations.
        state = pickle.loads(before)
        self.assertEqual(host.world.crisis.level, state.crisis.level)
        self.assertEqual(host.world.USA.govtAid, state.USA.govtAid)
        self.assertEqual(host.world.USA.diplOpinion, state.USA.diplOpinion)
        self.assertEqual(host.client.calls[-1]["event"], "restored")
        CH.doCHumanLoose(host.window, host.world, news)
        self.flush()
        self.assertEqual(host.client.calls[-1]["event"], "backed_down")
        self.assertTrue(host.client.calls[-1]["crisis_ended"])
        self.assertEqual(host.window.dialogueStatus.text(), "LLM diplomacy: ready.")

    def test_enabled_text_leaves_mechanics_and_random_sequence_identical(self):
        first, news = self.make(actor=1)
        copied = copy.deepcopy(first.world)
        second, other_news = self.make(world=copied)
        rng = random.getstate()
        CH.doCrisis(first.window, first.world, news)
        self.flush()
        expected, expected_rng = pickle.dumps(first.world), random.getstate()
        random.setstate(rng)
        set_ai_advisors(False)
        CH.doCrisis(second.window, second.world, other_news)
        self.flush()
        self.assertEqual(pickle.dumps(second.world), expected)
        self.assertEqual(random.getstate(), expected_rng)
        self.assertEqual(len(second.client.calls), 0)

    def test_disabled_offline_and_missing_key_never_call_model(self):
        for condition in ("disabled", "offline", "key"):
            with self.subTest(condition=condition):
                host, news = self.make()
                set_ai_advisors(condition != "disabled")
                if condition == "offline":
                    host.llm_config.offline = True
                elif condition == "key":
                    host.llm_config.api_key = ""
                self.begin(host, news)
                self.assertEqual(len(host.client.calls), 0)
                self.assertIn("built-in text", host.window.dialogueStatus.text())
                self.assertTrue(host.window.reactionLine.text())

    def test_invalid_and_failed_replies_keep_stock_text_and_say_fallback(self):
        for bad in ("not JSON", '{"reaction":"x","advisors":{}}',
                    '{"reaction":"x","advisors":{},"choice":"tough"}', None):
            with self.subTest(reply=bad):
                host, news = self.make()
                host.client.bad_reply = bad
                if bad is None:
                    host.client.error = TimeoutError("fake timeout")
                self.begin(host, news)
                self.assertIn("built-in text", host.window.dialogueStatus.text())
                self.assertTrue(host.window.reactionLine.text())
                self.assertFalse(any(label.text().startswith("Model advice") for label in host.window.advice))

    def test_new_rung_during_request_discards_old_reply_and_coalesces_hooks(self):
        host, news = self.make()
        host.during_request = lambda: CH.hangTough(host.window, host.world, host.world.USSR)
        self.begin(host, news)
        self.assertEqual(len(host.client.calls), 2)
        self.assertEqual(host.client.calls[0]["crisis_level"], 9)
        self.assertEqual(host.client.calls[1]["crisis_level"], 8)
        self.assertIn("stood_firm", host.window.reactionLine.text())
        self.assertEqual(host.window.dialogueStatus.text(), "LLM diplomacy: ready.")

    def test_world_replacement_or_hiding_discards_late_response(self):
        for change in ("world", "hide"):
            with self.subTest(change=change):
                host, news = self.make()
                if change == "world":
                    host.during_request = lambda: setattr(host, "world", World(4, False, 0))
                else:
                    host.during_request = host.window.hide
                self.begin(host, news)
                self.assertNotIn("Model advice", host.window.advice[0].text())
                self.assertNotEqual(host.window.dialogueStatus.text(), "LLM diplomacy: ready.")

    def test_duplicate_refresh_during_request_does_not_call_twice(self):
        host, news = self.make()
        host.during_request = lambda: host.window.queueCrisisDialogue(host.world, news, 1, "challenge")
        self.begin(host, news)
        self.assertEqual(len(host.client.calls), 1)
        # Re-drawing the identical event restores the cached text as well.
        host.window.reactionLine.setText("stock")
        host.window.queueCrisisDialogue(host.world, news, 1, "challenge")
        self.flush()
        self.assertEqual(len(host.client.calls), 1)
        self.assertIn("challenge", host.window.reactionLine.text())

    def test_later_failure_restores_rule_based_advice(self):
        host, news = self.make()
        self.begin(host, news)
        self.assertTrue(host.window.advice[0].text().startswith("Model advice"))
        host.client.error = LLMError("fake unavailable")
        CH.hangTough(host.window, host.world, host.world.USSR)
        self.flush()
        self.assertIn("built-in text", host.window.dialogueStatus.text())
        self.assertFalse(host.window.advice[0].text().startswith("Model advice"))

    def test_disabling_advisors_during_request_discards_model_output(self):
        host, news = self.make()
        host.during_request = lambda: set_ai_advisors(False)
        self.begin(host, news)
        self.assertIn("AI advisors disabled", host.window.dialogueStatus.text())
        self.assertFalse(host.window.advice[0].text().startswith("Model advice"))

    def test_editing_endpoint_or_credentials_during_request_discards_reply(self):
        for setting in ("base_url", "api_key"):
            with self.subTest(setting=setting):
                host, news = self.make()
                host.during_request = lambda: setattr(host.llm_config, setting, "new-fake-setting")
                self.begin(host, news)
                self.assertFalse(host.window.advice[0].text().startswith("Model advice"))
                self.assertIn("built-in text", host.window.dialogueStatus.text())


if __name__ == "__main__":
    unittest.main()
