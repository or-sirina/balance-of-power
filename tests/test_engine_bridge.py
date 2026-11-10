"""Focused rule parity, command validation and local transport checks.

Run: python -m unittest discover -s tests -p test_engine_bridge.py
"""

import _isolate  # noqa: F401 -- keep settings, credentials and saves out of tests

import copy
import http.client
import json
import random
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from EngineBridge import GameService, create_server
from EngineBridge.models import configured_client_factory
from EngineBridge.presenter import Presenter
from GameLogic import CrisisHandler, MovePlanner, Objectives
from GameLogic.Globals import doPolicy
from GameLogic.PolicyRules import policy_info
from GameLogic.World import World
from Net.GameFile import canonical_state_bytes
from Net.State import world_to_state


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.service = GameService(save_dir=self.directory.name)
        self.serial = 0

    def command(self, command, args=None, service=None):
        game = service or self.service
        self.serial += 1
        return game.handle({"id": "test-%d" % self.serial, "command": command,
                            "args": args or {}, "expected_revision": game.revision})

    def start(self, side=0, level=3, seed=7):
        response = self.command("new_game", {"side": side, "level": level, "seed": seed})
        self.assertTrue(response["ok"], response)
        return response

    def snapshot(self, game=None):
        return canonical_state_bytes(world_to_state((game or self.service).world))

    def test_opening_matches_original_and_does_not_use_qt(self):
        self.start()
        reference = GameService(save_dir=self.directory.name)
        original_rng = random.getstate()
        try:
            random.seed(7)
            reference.world = World(3, False, 0).repair()
            Objectives.ensure_state(reference.world)
            reference.presenter = Presenter(reference)
            MovePlanner.prePlanMove(reference.world)
            MovePlanner.mainMove(reference.presenter, reference.world)
            Objectives.snapshot(reference.world)
            expected_rng = random.getstate()
        finally:
            random.setstate(original_rng)
        self.assertEqual(self.snapshot(), self.snapshot(reference))
        self.assertEqual(self.service._rng, expected_rng)
        isolated = subprocess.run([sys.executable, "-c",
            "import sys; import EngineBridge; assert not any(name.startswith('PyQt5') for name in sys.modules)"],
            # This is an import-isolation assertion, not a startup performance
            # benchmark; allow for contention during bundled-build validation.
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
        self.assertEqual(isolated.returncode, 0, isolated.stderr)

    def test_actual_policy_and_end_turn_parity(self):
        self.start()
        reference = GameService(save_dir=self.directory.name)
        reference.world = copy.deepcopy(self.service.world)
        reference._rng = self.service._rng
        actor = self.service.world.USA
        found = next((c.id, info.old, info.steps()) for c in self.service.world.country[2:]
                     for info in [policy_info(self.service.world, actor, 2, c)]
                     if any(v != info.old for v in info.steps()))
        cid, old, steps = found
        value = next(v for v in steps if v != old)
        self.assertTrue(self.command("policy", {"target": cid, "action": 2, "value": value})["ok"])
        with reference._random_context():
            doPolicy(reference.world, reference.world.USA, reference.world.country[cid], 2, value)
        self.assertEqual(self.snapshot(), self.snapshot(reference))
        self.assertTrue(self.command("end_turn")["ok"])
        with reference._random_context():
            MovePlanner.prePlanMove(reference.world)
            CrisisHandler.reactNews(reference.presenter, reference.world)
        self.assertEqual(self.snapshot(), self.snapshot(reference))
        self.assertEqual(self.service._rng, reference._rng)

    def test_reject_illegal_policy_stale_and_duplicate(self):
        self.start(level=1)
        snapshot, revision = self.snapshot(), self.service.revision
        response = self.command("policy", {"target": 2, "action": 7, "value": 5})
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "illegal_policy")
        self.assertEqual(self.snapshot(), snapshot)
        self.assertEqual(self.service.revision, revision)
        request = {"id": "once", "command": "end_turn", "args": {}, "expected_revision": revision}
        response = self.service.handle(request)
        self.assertTrue(response["ok"])
        self.assertEqual(response, self.service.handle(request))
        self.assertEqual(self.service.revision, revision + 1)
        stale = self.service.handle(dict(request, id="stale"))
        self.assertEqual(stale["error"]["code"], "stale_revision")
        reused = self.service.handle(dict(request, command="state"))
        self.assertEqual(reused["error"]["code"], "duplicate_id")

    def _human_crisis(self):
        self.start()
        w = self.service.world
        with self.service._random_context():
            target = w.country[2]
            old = w.USA.insgAid[target.id]
            doPolicy(w, w.USA, target, 3, min(5, old + 1))
            news = next(n for n in reversed(w.news) if n.actor.id == 0 and n.target.id == target.id and n.action == 3)
            news.isQuestioned = True
            w.beingQuestioned = True
            self.service.presenter.newsWindow.showUp()
        return news, old

    def test_human_actor_retreat_reverts_and_blocks_other_actions(self):
        news, old = self._human_crisis()
        self.assertEqual(self.service.view()["crisis"]["level"], 9)
        self.assertTrue(self.service.view()["crisis"]["human_is_actor"])
        before = self.snapshot()
        blocked = self.command("end_turn")
        self.assertEqual(blocked["error"]["code"], "crisis_active")
        self.assertEqual(before, self.snapshot())
        response = self.command("crisis_choice", {"choice": "loose"})
        self.assertTrue(response["ok"], response)
        self.assertEqual(self.service.world.USA.insgAid[news.target.id], old)
        self.assertEqual(response["state"]["crisis"]["choices"], ["continue"])
        response = self.command("crisis_choice", {"choice": "continue"})
        self.assertTrue(response["ok"], response)
        self.assertTrue(any(event["type"] == "turn_completed" for event in response["events"]))

    def test_computer_actor_retreat_by_challenger_keeps_policy(self):
        self.start()
        w = self.service.world
        # Select an actual opponent headline that the original rules stand over.
        # A fixed draw removes sampling from the test without changing equations.
        found = False
        base = copy.deepcopy(w)
        for cid in range(2, 80):
            self.service.world = copy.deepcopy(base)
            w = self.service.world
            self.service.presenter = Presenter(self.service)
            with self.service._random_context(), patch.object(CrisisHandler, "randint", return_value=32767):
                doPolicy(w, w.USSR, w.country[cid], 3, min(5, w.USSR.insgAid[cid] + 1))
                candidates = [i for i, n in enumerate(w.news) if n.actor.id == 1 and n.target.id == cid
                              and n.action == 3 and CrisisHandler.canQuestion(w, n)]
                if not candidates:
                    continue
                response = self.command("question", {"news_id": candidates[-1]})
                if response["ok"] and w.crisis.hasBegun and w.crisis.level == 8:
                    found = True
                    break
        self.assertTrue(found)
        held = w.USSR.insgAid[cid]
        self.assertFalse(self.service.view()["crisis"]["human_is_actor"])
        response = self.command("crisis_choice", {"choice": "loose"})
        self.assertTrue(response["ok"], response)
        self.assertEqual(w.USSR.insgAid[cid], held)

    def test_save_load_preserves_world_rng_and_pending_crisis(self):
        self._human_crisis()
        before, rng, view = self.snapshot(), self.service._rng, self.service.view()
        self.assertTrue(self.command("save")["ok"])
        self.command("crisis_choice", {"choice": "loose"})
        self.assertTrue(self.command("load")["ok"])
        self.assertEqual(before, self.snapshot())
        self.assertEqual(rng, self.service._rng)
        self.assertEqual(view, self.service.view())
        self.assertTrue(self.command("crisis_choice", {"choice": "loose"})["ok"])
        bad = self.command("save", {"slot": "../outside"})
        self.assertEqual(bad["error"]["code"], "invalid_slot")

    def test_advisor_is_display_only_and_default_offline(self):
        factory = unittest.mock.Mock(side_effect=AssertionError("unexpected model call"))
        self.service.model_client_factory = factory
        self.start()
        factory.assert_not_called()
        self.service.model_client_factory = None
        before, revision = self.snapshot(), self.service.revision
        response = self.command("advisor", {"index": 0, "question": "What matters?", "language": "ru"})
        self.assertTrue(response["ok"], response)
        self.assertFalse(response["advice"]["used_model"])
        self.assertIn("Сужу по текущим данным", response["advice"]["text"])
        self.assertEqual(before, self.snapshot())
        self.assertEqual(revision, self.service.revision)

    def test_slow_advice_does_not_lock_game_and_stale_reply_is_rejected(self):
        self.start()
        entered, release = threading.Event(), threading.Event()
        original = self.service._run_advice
        def slow(*args):
            entered.set()
            release.wait(3)
            return original(*args)
        self.service._run_advice = slow
        result = []
        worker = threading.Thread(target=lambda: result.append(self.command("advisor", {"index": 0, "question": "Advice?"})))
        worker.start()
        self.assertTrue(entered.wait(1))
        response = self.command("select_country", {"country_id": 3})
        self.assertTrue(response["ok"])
        release.set()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result[0]["error"]["code"], "stale_advice")

    def test_http_loopback_auth_origin_and_size_boundary(self):
        server = create_server(self.service)
        self.assertEqual(server.server_address[0], "127.0.0.1")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        def post(headers=None, body=None):
            connection = http.client.HTTPConnection(*server.server_address, timeout=3)
            try:
                connection.request("POST", "/command", body or json.dumps({"id": "state", "command": "state"}), headers or {})
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()
        self.assertEqual(post()[0], 401)
        auth = {"Authorization": "Bearer " + server.token}
        status, response = post(auth)
        self.assertEqual(status, 200)
        self.assertTrue(response["ok"])
        self.assertIsNone(response["state"])
        self.assertEqual(post(dict(auth, Origin="https://example.com"))[0], 403)
        self.assertEqual(post(auth, "[invalid")[0], 400)
        self.assertEqual(post(auth, " " * 40000)[0], 413)

    def test_configured_chat_factory_is_lazy_shared_and_honors_saved_toggle(self):
        from types import SimpleNamespace
        options_path = Path(self.directory.name) / "options.dat"
        options = [False] * 12
        options_path.write_text(json.dumps(options))
        config = SimpleNamespace(usable=True, offline=False)
        client = SimpleNamespace(config=config)
        with patch("GameLogic.LLMClient.LLMConfig", return_value=config) as config_type, \
             patch("GameLogic.LLMClient.LLMClient", return_value=client) as client_type, \
             patch("GameLogic.AdvisorChat.chat_config", return_value=config), \
             patch("Paths.user_file", return_value=str(options_path)):
            factory = configured_client_factory()
            config_type.assert_not_called()
            client_type.assert_not_called()
            self.assertIsNone(factory())
            client_type.assert_not_called()
            options[11] = True
            options_path.write_text(json.dumps(options))
            self.assertIs(factory(), client)
            self.assertIs(factory(), client)
            self.assertEqual(client_type.call_count, 1)
        from GameLogic.AdvisorChat import set_ai_advisors
        set_ai_advisors(True)

    def _configured_opponent(self, client):
        from GameLogic.LLMClient import LLMConfig
        from GameLogic.LLMOpponent import LLMOpponent
        # This is a deliberately fake key and fake transport. No network runs.
        config = LLMConfig(offline=False, api_key="unit-test-not-a-real-key", model="unit-test-chat", backend="chat")
        return LLMOpponent(config=config, client=client)

    def test_level_five_uses_original_model_plan_and_validation(self):
        class Client:
            calls = 0
            def chat_chain(self, *args, **kwargs):
                self.calls += 1
                return '{"reasoning":"test","actions":[{"action":"destabilize","target":2,"level":1}]}'
        client = Client()
        self.service.opponent_factory = lambda: self._configured_opponent(client)
        self.assertEqual(client.calls, 0)
        response = self.start(level=5)
        self.assertEqual(client.calls, 1)
        self.assertEqual(response["state"]["opponent"], "model")
        self.assertEqual(self.service.world.USSR.destab[2], 1)
        self.assertEqual(self.service.presenter.llm_opponent.stats["llm"], 1)
        self.assertTrue(any(e["type"] == "opponent_plan" and e["source"] == "llm" for e in response["events"]))

    def test_rejected_command_keeps_level_five_opponent_and_campaign_identity(self):
        class Client:
            calls = 0
            def chat_chain(self, *args, **kwargs):
                self.calls += 1
                return '{"actions":[{"action":"destabilize","target":2,"level":1}]}'
        client = Client()
        self.service.opponent_factory = lambda: self._configured_opponent(client)
        self.start(level=5)
        world, presenter = self.service.world, self.service.presenter
        opponent, source = presenter.llm_opponent, self.service._opponent_source
        before, rng = self.snapshot(), self.service._rng
        rejected = self.command("policy", {"target": 0, "action": 2, "value": 1})
        self.assertFalse(rejected["ok"])
        self.assertIs(self.service.world, world)
        self.assertIs(self.service.presenter, presenter)
        self.assertIs(self.service.presenter.llm_opponent, opponent)
        self.assertEqual(self.service._opponent_source, source)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.service._rng, rng)
        self.assertFalse(self.command("new_game", {"level": 8})["ok"])
        self.assertIs(self.service.presenter.llm_opponent, opponent)
        self.assertTrue(self.command("end_turn")["ok"])
        self.assertEqual(client.calls, 2)
        self.assertEqual(self.service.presenter.llm_opponent.stats["llm"], 2)

    def test_level_five_failures_play_heuristic_once_and_retain_breaker(self):
        class Client:
            calls = 0
            def chat_chain(self, *args, **kwargs):
                self.calls += 1
                raise TimeoutError("unit test timeout")
        client = Client()
        self.service.opponent_factory = lambda: self._configured_opponent(client)
        with patch.object(MovePlanner, "compuAI", wraps=MovePlanner.compuAI) as fallback:
            self.start(level=5)
            self.assertEqual(fallback.call_count, 1)
            self.assertTrue(self.command("end_turn")["ok"])
            self.assertEqual(fallback.call_count, 2)
            self.assertTrue(self.command("end_turn")["ok"])
            self.assertEqual(fallback.call_count, 3)
        self.assertEqual(client.calls, 2)
        self.assertTrue(self.service.presenter.llm_opponent.disabled)
        self.assertEqual(self.service.world.year, 1984)
        self.assertEqual(self.service.view()["opponent"], "heuristic_model_unavailable")

    def test_slow_model_simulation_is_detached_and_replacement_discards_it(self):
        entered, release = threading.Event(), threading.Event()
        class Client:
            def chat_chain(self, *args, **kwargs):
                entered.set()
                release.wait(4)
                return '{"actions":[{"action":"destabilize","target":2,"level":1}]}'
        self.service.opponent_factory = lambda: self._configured_opponent(Client())
        result = []
        worker = threading.Thread(target=lambda: result.append(self.command("new_game", {"level": 5})))
        worker.start()
        self.assertTrue(entered.wait(1))
        state = self.command("state")
        self.assertTrue(state["ok"])
        self.assertIsNone(state["state"])
        # New game can replace a pending simulation while its transport waits.
        replacement = self.command("new_game", {"level": 1, "side": 1})
        self.assertTrue(replacement["ok"])
        self.assertEqual(replacement["state"]["side"], 1)
        release.set()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result[0]["error"]["code"], "stale_simulation")
        self.assertEqual(self.service.world.level, 1)
        self.assertIsNone(self.service._busy)

    def test_bilingual_views_localize_all_event_kinds_without_mutating_state(self):
        from types import SimpleNamespace
        from EngineBridge.localization import HISTORY_RU, country_name, news_ru, reason_ru, step_ru, type_ru
        from GameLogic.HistoricalEvents import EVENTS
        self.start()
        before, rng = self.snapshot(), self.service._rng
        view = self.command("state")["state"]
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.service._rng, rng)
        self.assertTrue(all("text_ru" in news for news in view["news"]))
        self.assertEqual(country_name(0), "США")
        self.assertEqual(step_ru(1, 1), "200 млн долларов в год")
        self.assertEqual(step_ru(1, 5), "4000 млн долларов в год")
        self.assertEqual(step_ru(2, 2), "100 млн долларов в год")
        self.assertIn("123 тыс.", reason_ru("Not enough troops left (123 thousand free); a higher step needs its full number free."))
        w = self.service.world
        cases = [(w.country[2], w.country[2], 1, 0, 1, "Революция"),
                 (w.country[2], w.country[2], 2, 0, 1, "Государственный переворот"),
                 (w.country[2], w.USA, 0, 0, 0, "Финляндизация"),
                 (w.country[2], w.country[3], 6, 1, 1, "Военные действия"),
                 (w.country[2], w.country[3], 6, 2, 1, "Капитуляция")]
        for actor, target, action, old, new, kind in cases:
            news = SimpleNamespace(actor=actor, target=target, host=actor, action=action, old=old, new=new)
            self.assertEqual(type_ru(news), kind)
            self.assertRegex(news_ru(news), "[А-Яа-я]")
        self.assertEqual(set(HISTORY_RU), {event.key for event in EVENTS})
        for event in EVENTS:
            if callable(event.headline):
                originals = ["Reagan and Gorbachev meet in Iceland. The talks collapse over missile defence, but both men leave believing the other is serious.",
                             "Reagan and Gorbachev meet in Iceland. Nothing is agreed, and the meeting ends in recrimination."]
            else:
                originals = [event.headline]
            for original in originals:
                news = SimpleNamespace(action=9, customText=original, text=original,
                    actor=w.country[event.actor], target=w.country[event.victim or event.actor])
                self.assertIn(HISTORY_RU[event.key][0], news_ru(news))
                self.assertNotIn(original, news_ru(news))

    def test_crisis_dialogue_reports_actual_retreat_speaker_and_original_headline(self):
        from GameLogic.LLMClient import LLMConfig
        news, old = self._human_crisis()
        original_headline = news.text
        response = self.command("crisis_choice", {"choice": "loose"})
        self.assertTrue(response["ok"])
        self.assertIn("США", response["state"]["crisis"]["reaction_ru"])
        self.assertIn("отменено", response["state"]["crisis"]["reaction_ru"])
        class Client:
            config = LLMConfig(offline=False, api_key="unit-test-not-a-real-key", model="unit-test-chat", backend="chat")
            facts = None
            def chat(self, messages, **kwargs):
                self.facts = json.loads(messages[-1]["content"])
                return json.dumps({"reaction": "A test reaction.", "advisors": {a["key"]: "Test advice." for a in self.facts["advisors"]}})
        client = Client()
        self.service.model_client_factory = lambda: client
        before, rng = self.snapshot(), self.service._rng
        response = self.command("crisis_dialogue", {"language": "en"})
        self.assertTrue(response["ok"], response)
        self.assertEqual(client.facts["diplomatic_speaker"], "United States")
        self.assertEqual(client.facts["event"], "backed_down")
        self.assertEqual(client.facts["headline"], original_headline)
        self.assertEqual(client.facts["policy_status"], "reverted")
        self.assertEqual(client.facts["held_policy_level"], old)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.service._rng, rng)
        self.assertTrue(response["dialogue"]["used_model"])
        self.assertNotIn("nastiness", client.facts)

    def test_http_model_retry_does_not_consume_mechanics_randomness(self):
        import io
        import urllib.error
        from GameLogic.LLMClient import LLMClient, LLMConfig
        response = io.BytesIO(json.dumps({"choices": [{"message": {"content": "after retry"}}]}).encode())
        response.headers = {"Content-Type": "application/json"}
        error = urllib.error.HTTPError("https://example.invalid", 503, "unavailable",
                                       {"Content-Type": "application/json"}, io.BytesIO(b'{}'))
        self.addCleanup(error.close)
        opener = unittest.mock.Mock()
        opener.open.side_effect = [error, response]
        client = LLMClient(LLMConfig(offline=False, api_key="unit-test-not-a-real-key", backend="chat", timeout=1))
        before = random.getstate()
        with patch("urllib.request.build_opener", return_value=opener), patch.object(client, "_pause"):
            self.assertEqual(client.chat([{"role": "user", "content": "test"}]), "after retry")
        self.assertEqual(opener.open.call_count, 2)
        self.assertEqual(random.getstate(), before)

    def _complete_tutorial(self, stop_at=10):
        response = self.command("tutorial_start")
        self.assertTrue(response["ok"], response)
        data = response["state"]["tutorial"]
        self.assertTrue(data["active"])
        self.assertEqual(data["step"], 0)
        self.assertEqual(response["state"]["side"], 0)
        self.assertEqual(response["state"]["level"], 1)
        target, value = data["target_country"], data["value"]
        self.assertTrue(data["value_label_ru"])
        response = self.command("select_country", {"country_id": target})
        self.assertEqual(response["state"]["tutorial"]["step"], 1)
        self.assertEqual(self.command("tutorial_ack")["state"]["tutorial"]["step"], 2)
        old = next(p["old"] for p in self.service.view()["selection"]["policies"] if p["action"] == 2)
        unchanged = self.command("policy", {"target": target, "action": 2, "value": old})
        self.assertTrue(unchanged["ok"])
        self.assertEqual(unchanged["state"]["tutorial"]["step"], 2)
        rejected = self.command("policy", {"target": target, "action": 7, "value": 1})
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["state"]["tutorial"]["step"], 2)
        response = self.command("policy", {"target": target, "action": 2, "value": value})
        self.assertEqual(response["state"]["tutorial"]["step"], 3)
        self.command("end_turn")
        for _ in range(20):
            view = self.service.view()
            if not view["crisis"]["active"]:
                break
            self.command("crisis_choice", {"choice": "continue" if "continue" in view["crisis"]["choices"] else "loose"})
        self.assertEqual(self.service.view()["tutorial"]["step"], 4)
        self.assertEqual(self.command("select_country", {"country_id": target})["state"]["tutorial"]["step"], 5)
        revision = self.service.revision
        reply_year, reply_side = self.service.world.year, self.service.world.human
        response = self.command("advisor", {"index": 0, "question": "Explain the choices", "language": "ru"})
        self.assertTrue(response["ok"], response)
        self.assertFalse(response["advice"]["used_model"])
        self.assertEqual(response["advice"]["year"], reply_year)
        self.assertEqual(response["advice"]["side"], reply_side)
        self.assertIsNone(response["advice"]["country_id"])
        self.assertNotEqual(response["advice"]["year"], response["state"]["year"])
        self.assertEqual(response["state"]["tutorial"]["step"], 6)
        self.assertEqual(self.service.revision, revision + 1)
        self.assertEqual(response["state"]["crisis"]["level"], 9)
        self.assertEqual(response["state"]["crisis"]["choices"], [])
        self.assertFalse(response["state"]["tutorial"]["finished"])
        if stop_at == 6:
            return self.snapshot(), self.service._rng
        response = self.command("tutorial_ack")
        self.assertEqual(response["state"]["tutorial"]["step"], 7)
        self.assertEqual(response["state"]["crisis"]["choices"], ["tough"])
        if stop_at == 7:
            return self.snapshot(), self.service._rng
        response = self.command("crisis_choice", {"choice": "tough"})
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["state"]["tutorial"]["step"], 8)
        self.assertEqual(response["state"]["crisis"]["level"], 7)
        self.assertEqual(response["state"]["crisis"]["choices"], ["loose"])
        if stop_at == 8:
            return self.snapshot(), self.service._rng
        response = self.command("crisis_choice", {"choice": "loose"})
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["state"]["tutorial"]["step"], 9)
        self.assertEqual(response["state"]["crisis"]["choices"], ["continue"])
        if stop_at == 9:
            return self.snapshot(), self.service._rng
        response = self.command("crisis_choice", {"choice": "continue"})
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["state"]["tutorial"]["step"], 10)
        self.assertTrue(response["state"]["tutorial"]["finished"])
        self.assertFalse(response["state"]["crisis"]["active"])
        return self.snapshot(), self.service._rng

    def test_practice_crisis_uses_original_rules_and_never_allows_further_escalation(self):
        from Net.State import clone_world
        self.start(side=1)
        campaign, campaign_rng = self.snapshot(), self.service._rng
        factory = Mock(side_effect=AssertionError("practice must stay offline"))
        self.service.model_client_factory = factory
        self._complete_tutorial(stop_at=6)
        facts = self.service.view()["tutorial"]["crisis_practice"]
        self.assertEqual(facts["opening_risk"], 0)
        self.assertEqual(facts["policy_before"], 0)
        self.assertEqual(facts["policy_proposed"], 1)
        self.assertIn("prepared", self.service.view()["tutorial"]["lesson_en"])
        self.assertIn("подготовленная", self.service.view()["tutorial"]["lesson_ru"])
        before, rng = self.snapshot(), self.service._rng
        rejected = self.command("crisis_choice", {"choice": "tough"})
        self.assertFalse(rejected["ok"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.service._rng, rng)
        self.command("tutorial_ack")
        reference = GameService()
        reference.world = clone_world(self.service.world)
        reference._rng = self.service._rng
        reference._restore_presenter(self.service._presenter_state())
        with reference._random_context():
            CrisisHandler.doCHumanTough(reference.presenter.newsWindow, reference.world, reference.world.crisis.whichHead)
        response = self.command("crisis_choice", {"choice": "tough"})
        self.assertTrue(response["ok"], response)
        self.assertEqual(self.snapshot(), self.snapshot(reference))
        self.assertEqual(self.service._rng, reference._rng)
        self.assertEqual(response["state"]["crisis"]["level"], 7)
        self.assertEqual(response["state"]["tutorial"]["crisis_practice"]["risk_after_escalation"], 12)
        before, rng = self.snapshot(), self.service._rng
        self.assertFalse(self.command("crisis_choice", {"choice": "tough"})["ok"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.service._rng, rng)
        with reference._random_context():
            CrisisHandler.doCHumanLoose(reference.presenter.newsWindow, reference.world, reference.world.crisis.whichHead)
        response = self.command("crisis_choice", {"choice": "loose"})
        self.assertEqual(self.snapshot(), self.snapshot(reference))
        facts = response["state"]["tutorial"]["crisis_practice"]
        self.assertEqual((facts["prestige_before"], facts["prestige_after"], facts["observed_loss"]), (749, 736, 13))
        self.assertEqual(facts["policy_current"], facts["policy_before"])
        self.assertIn("13", response["state"]["tutorial"]["lesson_en"])
        self.assertIn("12", response["state"]["tutorial"]["lesson_ru"])
        self.command("crisis_choice", {"choice": "continue"})
        self.assertEqual(self.service.world.year, 1982)
        self.assertFalse(self.service.view()["nuclear"])
        self.command("tutorial_end")
        self.assertEqual(self.snapshot(), campaign)
        self.assertEqual(self.service._rng, campaign_rng)
        factory.assert_not_called()

    def test_return_from_each_practice_stage_restores_pending_campaign_exactly(self):
        self._human_crisis()
        campaign, rng, view = self.snapshot(), self.service._rng, self.service.view()
        for step in (6, 7, 8, 9, 10):
            with self.subTest(step=step):
                self._complete_tutorial(stop_at=step)
                self.assertEqual(self.service.view()["tutorial"]["step"], step)
                self.assertTrue(self.command("tutorial_end")["ok"])
                self.assertEqual(self.snapshot(), campaign)
                self.assertEqual(self.service._rng, rng)
                self.assertEqual(self.service.view(), view)

    def test_both_crisis_directions_get_fresh_english_fallback_advice(self):
        from Net.State import clone_world
        self._human_crisis()
        for actor_side in (0, 1):
            if actor_side == 1:
                self.start()
                world = self.service.world
                with self.service._random_context():
                    doPolicy(world, world.USSR, world.country[2], 3, 1)
                index = next(i for i, n in enumerate(world.news) if n.actor.id == 1 and n.target.id == 2 and n.action == 3)
                for field in self.service.presenter.newsWindow.advice:
                    field.text = "STALE ADVICE"
                self.assertTrue(self.command("question", {"news_id": index})["ok"])
            before, rng = self.snapshot(), self.service._rng
            copied = clone_world(self.service.world)
            expected = [CrisisHandler.getAdvisorOpinion(copied, copied.crisis.whichHead, i + 1,
                        reversed=actor_side == copied.human) for i in range(4)]
            response = self.command("crisis_dialogue", {"language": "en"})
            self.assertTrue(response["ok"], response)
            self.assertEqual(response["dialogue"]["advice"], expected)
            self.assertTrue(all(response["dialogue"]["advice"]))
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(self.service._rng, rng)

    def test_resolved_crisis_is_history_not_current_advisor_briefing(self):
        self._human_crisis()
        self.command("crisis_choice", {"choice": "loose"})
        self.command("crisis_choice", {"choice": "continue"})
        self.assertFalse(self.service.presenter.newsWindow.locked)
        self.assertIsNotNone(self.service.world.crisis.whichHead)
        client = self._conversation_client()
        self.service.model_client_factory = lambda: client
        before, rng = self.snapshot(), self.service._rng
        response = self.command("advisor", {"index": 0, "question": "What matters for Mexico now?", "language": "en"})
        self.assertTrue(response["ok"], response)
        self.assertNotIn("THE QUESTION ON THE TABLE", client.messages[-1][1]["content"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.service._rng, rng)

    def test_russian_fallback_uses_actual_verdicts_both_directions_and_resolved_state(self):
        import Local
        from EngineBridge.localization import _ADVISORY_RU, country_name, crisis_advice_ru
        from Net.State import clone_world
        for side in (0, 1):
            self._human_crisis()
            if side == 1:
                self.start()
                world = self.service.world
                with self.service._random_context():
                    doPolicy(world, world.USSR, world.country[3], 3, 1)
                index = next(i for i, n in enumerate(world.news) if n.actor.id == 1 and n.target.id == 3 and n.action == 3)
                with patch.object(CrisisHandler, "randint", return_value=32767):
                    self.assertTrue(self.command("question", {"news_id": index})["ok"])
            before, rng = self.snapshot(), self.service._rng
            copied = clone_world(self.service.world)
            verdicts = [CrisisHandler.getAdvisorOpinion(copied, copied.crisis.whichHead, i + 1,
                        reversed=side == copied.human) for i in range(4)]
            response = self.command("crisis_dialogue", {"language": "ru"})
            self.assertTrue(response["ok"], response)
            result = response["dialogue"]
            for text, verdict in zip(result["advice"], verdicts):
                self.assertIn(_ADVISORY_RU[Local.strings[Local.ADVISORY].index(verdict)], text)
                self.assertNotIn("STALE", text)
            self.assertIn("защищает своё изменение" if side == 0 else "оспаривает чужое изменение", result["advice"][0])
            self.assertIn(country_name(copied.crisis.whichHead.target.id), result["advice"][0])
            self.assertIn(str(self.service.world.crisis.level), result["advice"][1])
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(self.service._rng, rng)
            # Every translated category matches the core's table, including its
            # extreme opinions, rather than substituting four generic slogans.
            panel = self.service._presenter_state()
            for index, verdict in enumerate(Local.strings[Local.ADVISORY]):
                self.assertIn(_ADVISORY_RU[index], crisis_advice_ru(copied, panel, [verdict] * 4)[0])
            prepared = self.service._prepare_advice("crisis_dialogue", {"language": "ru"})
            prepared["world"].nastiness = 1
            low = self.service._fallback_dialogue(prepared, "ru")
            prepared["world"].nastiness = 127
            self.assertEqual(low, self.service._fallback_dialogue(prepared, "ru"))
            self.assertTrue(self.command("crisis_choice", {"choice": "loose"})["ok"])
            resolved = self.command("crisis_dialogue", {"language": "ru"})
            self.assertTrue(resolved["ok"], resolved)
            self.assertTrue(all("Кризис завершён" in text for text in resolved["dialogue"]["advice"]))
            self.assertIn("отступила", resolved["dialogue"]["reaction"])

    def test_russian_crisis_fallback_observes_practice_rung_risk_and_advisor_index(self):
        self.start()
        self._complete_tutorial(stop_at=7)
        opening = self.command("crisis_dialogue", {"language": "ru"})
        self.assertTrue(opening["ok"], opening)
        self.assertEqual(opening["dialogue"]["status_code"], "training")
        self.assertIn("0 очков престижа", opening["dialogue"]["advice"][1])
        self.assertTrue(self.command("crisis_choice", {"choice": "tough"})["ok"])
        escalated = self.command("crisis_dialogue", {"language": "ru"})
        self.assertIn("Ступень 7", escalated["dialogue"]["advice"][1])
        self.assertIn("12 очков престижа", escalated["dialogue"]["advice"][1])
        before, rng = self.snapshot(), self.service._rng
        for index in range(4):
            response = self.command("advisor", {"index": index, "question": "Что делать в этом кризисе?", "language": "ru"})
            self.assertTrue(response["ok"], response)
            self.assertFalse(response["advice"]["used_model"])
            self.assertIn(escalated["dialogue"]["advice"][index], response["advice"]["text"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.service._rng, rng)

    def test_advisor_history_is_read_only_without_model_or_memory_creation(self):
        self.start()
        factory = Mock(side_effect=AssertionError("history must not call a model"))
        self.service.model_client_factory = factory
        before, rng, revision = self.snapshot(), self.service._rng, self.service.revision
        response = self.service.handle({"id": "empty-history", "command": "advisor_history", "args": {"index": 2, "language": "ru"}})
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["history"]["history"], [])
        self.assertEqual(response["history"]["statistics"]["resolved"], 0)
        self.assertFalse(self.service.conversations.records)
        factory.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.service._rng, rng)
        self.assertEqual(self.service.revision, revision)
        client = self._conversation_client()
        self.service.model_client_factory = lambda: client
        self.assertTrue(self.command("advisor", {"index": 2, "question": "Explain Mexico", "language": "en"})["ok"])
        count = len(client.messages)
        book = copy.deepcopy(self.service.conversations.records)
        dumped = copy.deepcopy(self.service.conversations.dump())
        history = self.command("advisor_history", {"index": 2, "language": "en"})
        self.assertTrue(history["ok"], history)
        self.assertTrue(any("Explain Mexico" in row["content"] for row in history["history"]["history"]))
        self.assertEqual(len(client.messages), count)
        self.assertEqual(self.service.conversations.dump(), dumped)
        # Compare data, not object identity of the copied memory instance.
        self.assertEqual(self.service.conversations.records.keys(), book.keys())
        self.assertFalse(self.command("advisor_history", {"index": 4})["ok"])

    def test_model_status_distinguishes_configuration_and_failures(self):
        from types import SimpleNamespace
        self.start()
        for code in ("disabled", "offline", "unconfigured", "failed"):
            class Factory:
                def resolve_advisor(self):
                    return None, code
            self.service.model_client_factory = Factory()
            response = self.command("advisor", {"question": "Как обстоят дела в Мексике?", "language": "ru"})
            self.assertTrue(response["ok"], response)
            self.assertEqual(response["advice"]["status_code"], code)
            self.assertFalse(response["advice"]["used_model"])
        options_path = Path(self.directory.name) / "status-options.dat"
        options_path.write_text(json.dumps([True] * 12))
        for offline, usable, code in ((True, True, "offline"), (False, False, "unconfigured")):
            config = SimpleNamespace(offline=offline, usable=usable)
            with patch("GameLogic.LLMClient.LLMConfig", return_value=config), \
                 patch("GameLogic.AdvisorChat.chat_config", return_value=config), \
                 patch("Paths.user_file", return_value=str(options_path)), \
                 patch("GameLogic.LLMClient.LLMClient", side_effect=AssertionError("must not create client")):
                self.assertEqual(configured_client_factory().resolve_advisor(), (None, code))
        self._human_crisis()
        client = self._conversation_client()
        client.chat = Mock(side_effect=RuntimeError("secret must never be public"))
        self.service.model_client_factory = lambda: client
        response = self.command("crisis_dialogue", {"language": "ru"})
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["dialogue"]["status_code"], "failed")
        self.assertNotIn("secret must never", json.dumps(response))

    def test_committed_year_resolves_forecasts_before_next_advisor_question(self):
        self.start(level=1, seed=3)
        reply = self.command("advisor", {"index": 0, "question": "Mexico alignment next year?", "language": "en"})
        self.assertTrue(reply["ok"], reply)
        previous = self.command("advisor_history", {"index": 0, "language": "en"})["history"]
        self.assertEqual(previous["statistics"]["open"], 1)
        year = self.service.world.year
        self.assertTrue(self.command("end_turn")["ok"])
        for _ in range(30):
            state = self.service.view()
            if not state["crisis"]["active"]:
                break
            choice = "continue" if "continue" in state["crisis"]["choices"] else "loose"
            self.assertTrue(self.command("crisis_choice", {"choice": choice})["ok"])
        self.assertGreater(self.service.world.year, year)
        current = self.command("advisor_history", {"index": 0, "language": "ru"})["history"]
        self.assertEqual(current["statistics"]["open"], 0)
        self.assertEqual(current["statistics"]["resolved"], 1)
        self.assertEqual(current["history"], [])  # Transcript language is separate.
        self.assertTrue(current["recent"])

    def test_tutorial_restores_exact_campaign_including_pending_crisis_and_rng(self):
        self._human_crisis()
        original_world, original_panel = self.service.world, self.service.presenter
        original_snapshot, original_rng, original_view = self.snapshot(), self.service._rng, self.service.view()
        factory = unittest.mock.Mock(side_effect=AssertionError("training must never request a model"))
        self.service.model_client_factory = factory
        self._complete_tutorial()
        for command in ("save", "load", "new_game"):
            response = self.command(command)
            self.assertEqual(response["error"]["code"], "tutorial_active")
        response = self.command("tutorial_end")
        self.assertTrue(response["ok"], response)
        self.assertIs(self.service.world, original_world)
        self.assertIs(self.service.presenter, original_panel)
        self.assertEqual(self.snapshot(), original_snapshot)
        self.assertEqual(self.service._rng, original_rng)
        self.assertEqual(self.service.view(), original_view)
        factory.assert_not_called()

    def test_tutorial_fixed_path_replays_and_restart_keeps_original_campaign(self):
        self.start(side=1)
        original_snapshot, original_rng = self.snapshot(), self.service._rng
        first_snapshot, first_rng = self._complete_tutorial()
        self.command("tutorial_start")  # Restart keeps the first campaign snapshot.
        self.command("tutorial_end")
        self.assertEqual(self.snapshot(), original_snapshot)
        self.assertEqual(self.service._rng, original_rng)
        second_snapshot, second_rng = self._complete_tutorial()
        self.assertEqual(first_snapshot, second_snapshot)
        self.assertEqual(first_rng, second_rng)
        self.command("tutorial_end")
        self.assertEqual(self.snapshot(), original_snapshot)
        self.assertEqual(self.service._rng, original_rng)

    def _conversation_client(self):
        from GameLogic.LLMClient import LLMConfig
        class Client:
            config = LLMConfig(offline=False, api_key="unit-test-not-a-real-key", model="unit-test-chat", backend="chat")
            def __init__(self):
                self.messages = []
                self.entered = None
                self.release = None
            def chat(self, messages, **kwargs):
                self.messages.append(copy.deepcopy(messages))
                if self.entered is not None:
                    self.entered.set()
                    self.release.wait(4)
                return "I recommend careful support.\nPREDICTION: Mexico hold 60"
        return Client()

    def test_advisor_follow_up_uses_prior_turns_and_history_survives_save_load(self):
        self.start()
        client = self._conversation_client()
        self.service.model_client_factory = lambda: client
        before, rng = self.snapshot(), self.service._rng
        first = self.command("advisor", {"index": 0, "question": "First question about Mexico", "language": "en"})
        self.assertTrue(first["ok"], first)
        self.assertTrue(first["advice"]["used_model"])
        self.assertEqual(first["advice"]["country_id"], 2)
        self.assertEqual(first["advice"]["year"], self.service.world.year)
        second = self.command("advisor", {"index": 0, "question": "Why did you recommend that?", "language": "en"})
        self.assertTrue(second["ok"], second)
        messages = client.messages[-1]
        self.assertTrue(any(m["role"] == "user" and "First question about Mexico" in m["content"] for m in messages))
        self.assertTrue(any(m["role"] == "assistant" and "careful support" in m["content"] for m in messages))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.service._rng, rng)
        self.assertIsNone(self.service.world.advisorGameId)
        self.assertTrue(self.command("save")["ok"])
        self.command("new_game", {"side": 1})
        self.assertFalse(self.service.conversations.records)
        self.assertTrue(self.command("load")["ok"])
        third = self.command("advisor", {"index": 0, "question": "Continue the earlier explanation", "language": "en"})
        self.assertTrue(third["ok"], third)
        self.assertTrue(any("First question about Mexico" in m["content"] for m in client.messages[-1]))
        # A different advisor has an independent conversation.
        self.assertTrue(self.command("advisor", {"index": 1, "question": "Your view on Mexico?", "language": "en"})["ok"])
        self.assertFalse(any("First question about Mexico" in m["content"] for m in client.messages[-1]))

    def test_stale_advisor_response_never_commits_history_into_new_game(self):
        self.start()
        client = self._conversation_client()
        client.entered, client.release = threading.Event(), threading.Event()
        self.service.model_client_factory = lambda: client
        results = []
        worker = threading.Thread(target=lambda: results.append(self.command("advisor", {
            "index": 0, "question": "Old game question about Mexico", "language": "en"})))
        worker.start()
        self.assertTrue(client.entered.wait(1))
        self.assertTrue(self.command("new_game", {"side": 1})["ok"])
        client.release.set()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0]["error"]["code"], "stale_advice")
        self.assertFalse(self.service.conversations.records)
        self.assertIsNone(self.service.world.advisorGameId)
        client.entered = None
        self.assertTrue(self.command("advisor", {"index": 0, "question": "New game question about Mexico", "language": "en"})["ok"])
        self.assertFalse(any("Old game question" in m["content"] for m in client.messages[-1]))

    def test_tutorial_conversation_is_offline_and_restores_campaign_history(self):
        self.start()
        client = self._conversation_client()
        self.service.model_client_factory = lambda: client
        self.assertTrue(self.command("advisor", {"index": 0, "question": "Campaign question about Mexico", "language": "en"})["ok"])
        book = self.service.conversations
        self.command("tutorial_start")
        self.assertIsNot(self.service.conversations, book)
        self.assertFalse(self.service.conversations.records)
        training = self.command("advisor", {"index": 0, "question": "Training question about Mexico", "language": "en"})
        self.assertTrue(training["ok"], training)
        self.assertFalse(training["advice"]["used_model"])
        self.assertEqual(len(client.messages), 1)
        self.assertTrue(self.service.conversations.records)
        self.command("tutorial_end")
        self.assertIs(self.service.conversations, book)
        self.assertTrue(self.command("advisor", {"index": 0, "question": "Continue the campaign explanation", "language": "en"})["ok"])
        latest = client.messages[-1]
        self.assertTrue(any("Campaign question about Mexico" in m["content"] for m in latest))
        self.assertFalse(any("Training question" in m["content"] for m in latest))


if __name__ == "__main__":
    unittest.main()
