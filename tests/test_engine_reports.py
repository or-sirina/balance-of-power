"""Report parity, read-only guarantees, secrecy and settings command routing."""

import _isolate  # noqa: F401 -- must precede game imports and model settings

import copy
import json
import random
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from EngineBridge import GameService, configured_client_factory
from EngineBridge.reports import build_report, mode_registry
from EngineBridge.settings import SettingsService
from GameLogic import Objectives
from GameLogic.Globals import tdiv
from GameLogic.LLMClient import LLMClient
from GameLogic.PolicyRules import policy_info
from MapPainter import MapPainter
from Net.State import clone_world, world_to_state
from Net.GameFile import canonical_state_bytes
from constants import AVL_ACTIONS, INAVL_MAP_MODES


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = GameService(save_dir=self.temp.name)
        self.serial = 0
        self.start(4)

    def command(self, command, args=None, revision=True):
        self.serial += 1
        request = {"id": "report-%d" % self.serial, "command": command, "args": args or {}}
        if revision:
            request["expected_revision"] = self.service.revision
        return self.service.handle(request)

    def start(self, level):
        response = self.command("new_game", {"side": 0, "level": level, "seed": 27})
        self.assertTrue(response["ok"], response)

    def snapshot(self):
        return canonical_state_bytes(world_to_state(self.service.world))

    def test_all_original_map_values_and_colors_match_qt_calculations(self):
        import Theme
        previous = Theme.colour_blind()
        Theme.set_colour_blind(False)
        self.addCleanup(Theme.set_colour_blind, previous)
        world = self.service.world
        painter = MapPainter(None, world)
        snapshot, rng, process_rng = self.snapshot(), self.service._rng, random.getstate()
        for mode in range(58):
            with self.subTest(mode=mode):
                response = self.command("report", {"kind": "map", "mode": mode, "country_id": 0}, revision=False)
                self.assertTrue(response["ok"], response.get("error"))
                report = response["report"]
                expected = [painter.getDisplayedValue(c.id, mode, 0) for c in world.country]
                self.assertEqual([row["value"] for row in report["countries"]], expected)
                self.assertEqual([row["color"] for row in report["countries"]],
                                 [color.name() for color in painter.color_for(mode, expected)])
                self.assertTrue(all(row["label_ru"] for row in report["countries"]))
                self.assertTrue(all("color" in item for item in report["scale"]["legend"]))
        self.assertEqual(self.snapshot(), snapshot)
        self.assertEqual(self.service._rng, rng)
        self.assertEqual(random.getstate(), process_rng)

    def test_map_availability_enforced_and_registry_is_bilingual(self):
        for level in (1, 2, 3, 4, 5):
            self.start(level)
            registry = mode_registry(self.service.world)
            self.assertEqual([row["id"] for row in registry], list(range(60)))
            for entry in registry:
                self.assertTrue(entry["label"])
                self.assertRegex(entry["label_ru"], "[А-Яа-я]")
                self.assertEqual(entry["available"], entry["id"] not in INAVL_MAP_MODES[level - 1])
            before, revision = self.snapshot(), self.service.revision
            for mode in INAVL_MAP_MODES[level - 1]:
                response = self.command("report", {"kind": "map", "mode": mode}, revision=False)
                self.assertFalse(response["ok"])
                self.assertEqual(response["error"]["code"], "mode_unavailable")
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(self.service.revision, revision)

    def test_directional_opinions_trade_and_minor_sources(self):
        world = self.service.world
        world.USA.diplOpinion[2], world.country[2].diplOpinion[0] = -111, 88
        out = build_report(world, {"kind": "map", "mode": 8, "country_id": 0})
        incoming = build_report(world, {"kind": "map", "mode": 17, "country_id": 0})
        self.assertEqual(out["countries"][2]["raw_value"], -111)
        self.assertEqual(incoming["countries"][2]["raw_value"], 88)
        world.USA.trade[2] = 4
        world.USSR.trade[2] = 2
        trade_out = build_report(world, {"kind": "map", "mode": 58, "country_id": 0})
        trade_in = build_report(world, {"kind": "map", "mode": 59, "country_id": 2})
        self.assertEqual(trade_out["countries"][2]["value"], 4)
        self.assertEqual([row["value"] for row in trade_in["countries"][:2]], [4, 2])
        for mode in (13, 14, 15, 16, 58):
            self.assertEqual({row["value"] for row in build_report(world, {"kind": "map", "mode": mode, "country_id": 2})["countries"]}, {0})

    def test_country_history_policy_units_and_incoming_score_contribution(self):
        self.command("end_turn")
        world, country = self.service.world, self.service.world.country[2]
        world.USA.diplOpinion[2], country.diplOpinion[0] = -11, 61
        before, rng = self.snapshot(), self.service._rng
        report = self.command("report", {"kind": "country", "country_id": 2}, revision=False)["report"]
        self.assertEqual(report["relations"][0]["opinion_of_country"], -11)
        self.assertEqual(report["relations"][0]["country_opinion_of_side"], 61)
        self.assertEqual(report["relations"][0]["score_contribution"], tdiv(61 * country.prestigeVal, 1024))
        self.assertEqual(report["relations"][0]["legacy_closeup_value"], tdiv(-11 * country.prestigeVal, 1024))
        for policy in report["policies"]:
            info = policy_info(world, world.country[policy["side"]], policy["action"], country)
            self.assertEqual(policy["steps"], info.steps())
            self.assertEqual(policy["ceiling"], info.ceiling)
        series = {row["id"]: row for row in report["history"]["series"]}
        self.assertEqual(series["opinion_0"]["values"], country.history.diplOpinion[0])
        self.assertEqual(series["gnp"]["raw_values"], country.history.GNP[0])
        self.assertEqual(series["gnp"]["values"][-1], country.getNominalGNP(3) * 100)
        self.assertEqual(report["history"]["years"], [1982, 1983])
        self.assertEqual(len(report["encyclopedia"]), 23)
        self.assertTrue(all("value_text_ru" in row for row in report["encyclopedia"]))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.service._rng, rng)

    def test_unavailable_country_indicators_and_history_are_not_exposed(self):
        self.start(1)
        report = build_report(self.service.world, {"kind": "country", "country_id": 2})
        self.assertNotIn("government_stability", {row["id"] for row in report["rows"]})
        self.assertTrue(all(row["finlandization_raw"] is None for row in report["relations"]))
        for series in report["history"]["series"]:
            if not series["available"]:
                self.assertEqual(series["values"], [])
                self.assertEqual(series["raw_values"], [])
        self.assertEqual({policy["action"] for policy in report["policies"]}, set(AVL_ACTIONS[0]))

    def test_scores_use_last_scored_history_after_nuclear_war(self):
        world = self.service.world
        world.USA.historyScore = [12, 22]
        world.USSR.historyScore = [-2, 5]
        world.USA.score, world.USA.initScore = 999, -999
        world.NWFlag = True
        report = build_report(world, {"kind": "scores"})
        self.assertTrue(report["nuclear"])
        self.assertIsNone(report["winner"])
        self.assertIsNone(report["leader"])
        self.assertEqual([row["standing"] for row in report["rows"]], [22, 5])
        self.assertEqual([row["delta"] for row in report["rows"]], [10, 7])
        self.assertEqual([row["objective_bonus"] for row in report["rows"]], [0, 0])
        objectives = build_report(world, {"kind": "objectives"})
        self.assertTrue(objectives["void"])
        self.assertEqual(objectives["bonus"], 0)
        self.assertTrue(all(row["status"] == "void" and not row["met"] for row in objectives["rows"]))

    def test_objective_predicates_cannot_mutate_live_world_or_reveal_true_tension(self):
        world = self.service.world
        world.nastiness, world.knownNastiness[0] = 72, 4
        before = self.snapshot()
        report = build_report(world, {"kind": "objectives"})
        calm = next(row for row in report["rows"] if row["id"] == "calm_world")
        self.assertIn("4 ±", calm["progress"])
        self.assertNotIn("72", calm["progress"])
        self.assertEqual(self.snapshot(), before)
        world.nastiness = 120
        before = self.snapshot()
        breached = build_report(world, {"kind": "objectives"})
        self.assertFalse(next(row for row in breached["rows"] if row["id"] == "calm_world")["met"])
        self.assertEqual(self.snapshot(), before)  # calm_world mutates only the clone
        for kind in ("country", "scores", "objectives", "map"):
            payload = json.dumps(build_report(world, {"kind": kind, "country_id": 2, "mode": 0}))
            for forbidden in ('"nastiness"', '"true_tension"', '"knownPugnacity"'):
                self.assertNotIn(forbidden, payload)


class SettingsRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paths = patch("Paths.user_file", side_effect=lambda name: str(Path(self.temp.name) / name))
        self.paths.start()
        self.addCleanup(self.paths.stop)
        self.serial = 0

    def command(self, service, command, args=None):
        self.serial += 1
        return service.handle({"id": "settings-route-%d" % self.serial, "command": command, "args": args or {}})

    def test_settings_work_without_game_and_offline_probe_has_no_transport(self):
        forbidden = Mock(side_effect=AssertionError("offline test must never construct a transport"))
        settings = SettingsService(chat_factory=forbidden, decisions_factory=forbidden)
        service = GameService(save_dir=self.temp.name, settings_service=settings)
        current = self.command(service, "settings_get")
        self.assertTrue(current["ok"])
        self.assertIn("settings", current)
        applied = self.command(service, "settings_apply", {"offline": True, "expected_generation": current["settings"]["generation"]})
        self.assertTrue(applied["ok"], applied)
        tested = self.command(service, "settings_test", {"expected_generation": applied["settings"]["generation"]})
        self.assertTrue(tested["ok"], tested)
        self.assertTrue(tested["test"]["ok"])
        forbidden.assert_not_called()
        self.assertIsNone(service.world)

    def test_apply_rebuilds_clients_and_breakers_preserving_game_budget_and_usage(self):
        settings = SettingsService()
        settings.apply({"offline": True})
        models = configured_client_factory()
        service = GameService(save_dir=self.temp.name, model_client_factory=models, opponent_factory=models.opponent,
                              settings_service=settings)
        response = service.handle({"id": "start", "command": "new_game", "args": {"level": 5}, "expected_revision": 0})
        self.assertTrue(response["ok"], response)
        opponent = service.presenter.llm_opponent
        budget, old_client, old_jev = opponent.config.game_budget, opponent.client, opponent.jev
        budget.used = 7
        old_client.usage["requests"] = 4
        old_jev.usage["requests"] = 2
        chat = LLMClient(opponent.config)
        chat.usage["requests"] = 3
        chat.advisor_breaker.tripped = True
        models.restore_runtime((opponent.config, chat))
        stats = copy.deepcopy(opponent.stats)
        opponent.disabled = True
        applied = self.command(service, "settings_apply", {"offline": True, "model": "unit-test-reconfigured", "timeout": 15, "max_requests": 12})
        self.assertTrue(applied["ok"], applied)
        self.assertIs(service.presenter.llm_opponent, opponent)
        self.assertIs(opponent.config.game_budget, budget)
        self.assertEqual(budget.used, 7)
        self.assertEqual(opponent.stats, stats)
        self.assertFalse(opponent.disabled)
        self.assertIsNot(opponent.client, old_client)
        self.assertEqual(opponent.client.usage["requests"], 4)
        self.assertEqual(opponent.jev.usage["requests"], 2)
        self.assertNotEqual(old_client.config.model, "unit-test-reconfigured")
        new_config, new_chat = models.capture_runtime()
        self.assertIsNot(new_chat, chat)
        self.assertFalse(new_chat.advisor_breaker.tripped)
        self.assertEqual(new_chat.usage["requests"], 3)
        self.assertIs(new_config.game_budget, budget)
        self.assertEqual(opponent.client.budget_left(), 5)
        self.assertEqual(opponent.jev.budget_left(), 5)

    def test_probe_waits_outside_game_lock_and_settings_change_discards_result(self):
        entered, release = threading.Event(), threading.Event()
        class SlowSettings(SettingsService):
            def run_test(self, prepared):
                entered.set()
                release.wait(4)
                return super().run_test(prepared)
        settings = SlowSettings()
        settings.apply({"offline": True})
        service = GameService(settings_service=settings)
        results = []
        worker = threading.Thread(target=lambda: results.append(self.command(service, "settings_test")))
        worker.start()
        self.assertTrue(entered.wait(1))
        self.assertTrue(self.command(service, "state")["ok"])
        self.assertTrue(self.command(service, "settings_apply", {"offline": True, "timeout": 15})["ok"])
        release.set()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0]["error"]["code"], "settings_changed")
        self.assertTrue(results[0]["error"]["message_ru"])


if __name__ == "__main__":
    unittest.main()
