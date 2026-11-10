#!/usr/bin/env python3
"""Advisor facts must match authoritative policy rules and opinion direction."""

import _isolate  # noqa: F401 -- isolate user settings and keys before game imports

import os
import pickle
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from GameLogic import AdvisorChat as AC
from GameLogic import AdvisorMemory as AM
from GameLogic.LLMClient import LLMConfig, LLMError
from GameLogic.PolicyRules import check_request, policy_info
from GameLogic.World import World


class TransientMemory:
    def __init__(self):
        self.last_error = ""
        self.predictions = []

    def observe(self, world, side):
        pass

    def prompt_block(self, world, question, side):
        return ""

    def predict(self, *args):
        self.predictions.append(args)

    def stats(self, *args):
        return {"resolved": 0, "hits": 0, "open": len(self.predictions)}


class FakeClient:
    def __init__(self, config, error=False):
        self.config = config
        self.messages = None
        self.error = error
        self.reply = "Предлагаю действовать осторожно.\nPREDICTION: Poland hold 70"

    def chat(self, messages, **kwargs):
        self.messages = messages
        if self.error:
            raise LLMError("local fake transport failure")
        return self.reply


class AdvisorFactsTests(unittest.TestCase):
    def setUp(self):
        AC.set_ai_advisors(True)
        self.world = World(5, False, 0)

    def tearDown(self):
        AC.set_ai_advisors(True)

    def test_asymmetric_opinions_are_explicit_and_standing_uses_incoming(self):
        target = self.world.country[9]
        self.world.USA.diplOpinion[9] = -77
        self.world.USSR.diplOpinion[9] = 66
        target.diplOpinion[0], target.diplOpinion[1] = 31, -42
        for side in (0, 1):
            with self.subTest(side=side):
                facts = AC.country_facts(self.world, side, 9)
                self.assertEqual(facts["our_standing"], (31, -42)[side])
                self.assertEqual(facts["their_standing"], (-42, 31)[side])
                self.assertEqual(facts["country_opinion_of_us"], facts["our_standing"])
                self.assertEqual(facts["our_opinion_of_country"], (-77, 66)[side])
                self.assertEqual(facts["their_opinion_of_country"], (66, -77)[side])
                text = AC.facts_block(self.world, side, countries=[9])
                self.assertIn("country's opinion of us %+d" % facts["our_standing"], text)
                self.assertIn("our opinion of this country %+d" % facts["our_opinion_of_country"], text)

    def test_advisor_standing_tracks_actual_score_direction(self):
        target = self.world.country[9]
        target.prestigeVal = 1024
        before = self.world.USA.prestige(self.world)
        self.world.USA.diplOpinion[9] += 10
        self.assertEqual(self.world.USA.prestige(self.world), before)
        target.diplOpinion[0] += 10
        self.assertEqual(self.world.USA.prestige(self.world), before + 10)
        self.assertEqual(AC.country_facts(self.world, 0, 9)["our_standing"], target.diplOpinion[0])

    def test_prestige_weight_matches_original_map_and_country_report_for_both_sides(self):
        from EngineBridge.reports import build_report
        from MapPainter import MapPainter
        from constants import M_PRESTIGE
        # Include both display-unit boundaries and raw values with a remainder:
        # no perspective or opinion may turn this weight into a score instead.
        values = (0, 7, 8, 63, 64, 65, 8199)
        for cid, raw in enumerate(values, 2):
            target = self.world.country[cid]
            target.prestigeVal = raw
            target.diplOpinion[0], target.diplOpinion[1] = -91, 37
        original_map = MapPainter(None, self.world)
        report_map = build_report(self.world, {"kind": "map", "mode": M_PRESTIGE})
        for cid, raw in enumerate(values, 2):
            report = build_report(self.world, {"kind": "country", "country_id": cid})
            displayed = next(row["value"] for row in report["rows"] if row["id"] == "prestige")
            self.assertEqual(displayed, original_map.getDisplayedValue(cid, M_PRESTIGE, None))
            self.assertEqual(displayed, report_map["countries"][cid]["value"])
            for side in (0, 1):
                with self.subTest(raw=raw, side=side):
                    facts = AC.country_facts(self.world, side, cid)
                    self.assertEqual(facts["prestige_value"], displayed)
                    self.assertEqual(facts["worth"], displayed)
                    text = AC.facts_block(self.world, side, countries=[cid])
                    self.assertIn("displayed prestige weight %d" % displayed, text)
                    if raw >= 8:
                        contribution = report["relations"][side]["score_contribution"]
                        self.assertNotEqual(displayed, contribution)
        session, _client = self.session(offline=True)
        target = self.world.country[8]
        answer = session.ask(self.world, AC.country_name(self.world, target), language="en")
        self.assertIn("displayed prestige weight is %d" % (target.prestigeVal // 8), answer)
        answer = session.ask(self.world, AC.country_name(self.world, target), language="ru")
        self.assertIn("вес в престиже: %d" % (target.prestigeVal // 8), answer)

    def test_memory_and_calibration_follow_incoming_opinion_for_both_sides(self):
        for side in (0, 1):
            with self.subTest(side=side), tempfile.TemporaryDirectory() as directory:
                world = World(5, False, side)
                target, actor = world.country[9], world.country[side]
                actor.diplOpinion[9], target.diplOpinion[side] = 80, -40
                memory = AM.AdvisorMemory(path=os.path.join(directory, "memory.json"))
                memory.observe(world, side)
                self.assertEqual(memory.snapshot["align"]["9"], -40)
                memory.predict(world, side, "test", 9, AM.UP, 80)
                world.year += 1
                actor.diplOpinion[9] -= 70
                target.diplOpinion[side] += 30
                added = memory.observe(world, side)
                stats = memory.stats(side, "test")
                self.assertEqual((stats["hits"], stats["resolved"]), (1, 1))
                self.assertTrue(any("towards you" in line for line in added))
                self.assertEqual(AM.alignment(world, side, 9), -10)

    def test_loading_legacy_memory_does_not_score_incompatible_pending_baseline(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "memory.json")
            key = AM.game_key(self.world)
            old = {"records": {"0:test": {"hits": 2, "resolved": 3}},
                   "games": {key: {"pending": [{"side": 0, "key": "test", "year": 1980,
                                                  "country_id": 9, "alignment": 99}],
                                    "snapshot": {"year": 1980, "align": {"9": 99}}}}}
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(old, handle)
            memory = AM.AdvisorMemory(path=path, game=key)
            self.assertEqual(memory.pending, [])
            self.assertIsNone(memory.snapshot)
            self.assertEqual(memory.stats(0, "test")["resolved"], 3)

    def test_russian_selected_country_names_resolve_with_english_simulation_locale(self):
        poland = AC.resolve_country(self.world, "Poland")
        self.assertEqual(AC.find_countries(self.world, "Что предпринять? Польша"), [poland.id])
        self.assertEqual(AC.resolve_country(self.world, "США").id, 0)
        session, _client = self.session(offline=True)
        answer = session.ask(self.world, "Польша", language="ru")
        self.assertIn("Польша:", answer)
        self.assertEqual(session.last_prediction["country_id"], poland.id)

    def test_every_verb_side_level_and_resource_state_matches_policy_authority(self):
        for level in range(1, 6):
            for side in (0, 1):
                for scarce in (False, True):
                    world = World(level, False, side)
                    actor, target = world.country[side], world.country[9]
                    actor.diplOpinion[9] = 70
                    actor.treaty[9], actor.trade[9] = 4, 3
                    actor.govtIntv[9], actor.govtAid[9] = 2, 2
                    actor.contig[9] = True
                    target.strengthRatio = 1
                    actor.gnpSpnd[2] = 0 if scarce else 8000
                    actor.totalGovtAid = -500 if scarce else 0
                    actor.milMen, actor.totalIntv = (20, 50) if scarce else (2000, 0)
                    policy = AC.my_policy(world, side, 9)
                    for name, rule in policy["rules"].items():
                        verb = rule["verb"]
                        with self.subTest(level=level, side=side, scarce=scarce, verb=verb):
                            authority = policy_info(world, actor, verb, target)
                            allowed = [step for step in range(6)
                                       if check_request(world, actor, verb, 9, step)[0]]
                            self.assertEqual(rule["legal_steps"], allowed)
                            self.assertEqual(policy["legal_choices"][name], allowed)
                            self.assertEqual(policy["ceiling_" + name], authority.ceiling)
                            self.assertEqual(policy[name], authority.old)
                            self.assertEqual(rule["resource_available"], authority.avail)

    def test_treaty_uses_integrity_plus_opinion_minus_pugnacity(self):
        actor = self.world.USA
        actor.integrity, actor.pugnacity, actor.diplOpinion[9] = 60, 100, 20
        actor.treaty[9] = actor.trade[9] = 0
        policy = AC.my_policy(self.world, 0, 9)
        self.assertEqual(policy["ceiling_treaty"], 1)
        self.assertEqual(policy["ceiling_trade"], 1)
        self.assertEqual(policy["legal_choices"]["treaty"], [0, 1])
        # A held treaty/trade level cannot be lowered even after goodwill falls.
        actor.treaty[9], actor.trade[9] = 4, 5
        policy = AC.my_policy(self.world, 0, 9)
        self.assertEqual(policy["legal_choices"]["treaty"], [4])
        self.assertEqual(policy["legal_choices"]["trade"], [5])
        self.assertIn("trade Full trade partnership / Full trade partnership", policy["summary"])
        self.assertIn("treaty Conventional defense / Conventional defense", policy["summary"])

    def test_budget_exhaustion_limits_intervention_but_held_steps_are_legal(self):
        actor = self.world.USA
        actor.treaty[9], actor.govtIntv[9] = 5, 2
        actor.milMen, actor.totalIntv = 20, 5
        policy = AC.my_policy(self.world, 0, 9)
        self.assertEqual(policy["ceiling_government_intervention"], 0)
        self.assertEqual(policy["legal_choices"]["government_intervention"], [0, 1, 2])
        self.assertEqual(policy["rules"]["government_intervention"]["resource_available"], 0)
        self.assertEqual(policy["available_troops_thousands"], 0)

    def test_superpower_targets_have_no_legal_policy_choices(self):
        for side in (0, 1):
            policy = AC.my_policy(self.world, side, 1 - side)
            self.assertTrue(policy["ok"])
            self.assertTrue(all(not choices for choices in policy["legal_choices"].values()))

    def test_fact_lookup_is_read_only_and_preserves_random_sequence(self):
        before, rng = pickle.dumps(self.world), random.getstate()
        AC.country_facts(self.world, 0, 9)
        AC.my_policy(self.world, 0, 9)
        AC.facts_block(self.world, 0, countries=[9])
        self.assertEqual(pickle.dumps(self.world), before)
        self.assertEqual(random.getstate(), rng)

    def test_briefing_uses_side_intelligence_estimate_and_uncertainty(self):
        from GameLogic.MovePlanner import estimate_error
        self.world.nastiness = 112
        self.world.knownNastiness = [4, 23]
        self.world.intel = [5, 0]
        for side in (0, 1):
            with self.subTest(side=side):
                text = AC.situation_text(self.world, side)
                self.assertIn("estimates world tension at %d out of 127" % self.world.knownNastiness[side], text)
                self.assertIn("uncertainty +/- %d" % estimate_error(self.world.intel[side]), text)
                self.assertNotIn("112", text)

    def session(self, offline=False, error=False):
        config = LLMConfig(model="test/chat", api_key="fake-local-key", offline=offline)
        client = FakeClient(config, error)
        session = AC.AdvisorSession(0, 0, config=config, client=client, memory=TransientMemory())
        return session, client

    def test_chosen_language_is_explicit_in_model_prompt_and_prediction_survives(self):
        session, client = self.session()
        reply = session.ask(self.world, "What about Poland?", language="ru")
        self.assertIn("Write ALL spoken advice in Russian", client.messages[0]["content"])
        self.assertNotIn("PREDICTION", reply)
        self.assertEqual(session.last_prediction["confidence"], 70)
        self.assertIn("Прогноз", session.prediction_note())
        session.ask(self.world, "Poland?", language="en")
        self.assertIn("Write ALL spoken advice in English", client.messages[0]["content"])

    def test_russian_offline_and_transport_fallback_are_factual_and_scored(self):
        for offline, error in ((True, False), (False, True)):
            with self.subTest(offline=offline, error=error):
                session, client = self.session(offline, error)
                reply = session.ask(self.world, "Poland?", language="ru")
                self.assertIn("Допустимые уровни", reply)
                self.assertIn("отношение к нам", reply)
                self.assertNotIn("PREDICTION", reply)
                self.assertNotIn("My concern", reply)
                self.assertNotIn("cannot reach", reply)
                self.assertIsNotNone(session.last_prediction)
                self.assertEqual(len(session.memory.predictions), 1)
                if offline:
                    self.assertIsNone(client.messages)

    def test_english_only_model_reply_to_russian_question_falls_back(self):
        session, client = self.session()
        client.reply = "We should negotiate.\nPREDICTION: Poland up 80"
        answer = session.ask(self.world, "Польша", language="ru")
        self.assertIn("Модель не ответила по-русски", answer)
        self.assertIn("Допустимые уровни", answer)
        self.assertEqual(session.history, [])
        self.assertIsNotNone(session.last_prediction)

    def test_policy_values_and_free_budgets_use_actual_money_and_personnel_units(self):
        from GameLogic.Globals import econConv, intvConv, mAidConv
        for language in ("en", "ru"):
            for step in range(6):
                with self.subTest(language=language, step=step):
                    compact = lambda value: value.replace(",", "").replace(" ", "")
                    self.assertIn(str(econConv(step) * 200), compact(AC.policy_value(1, step, language)))
                    for verb in (2, 3):
                        self.assertIn(str(mAidConv(step) * 20), compact(AC.policy_value(verb, step, language)))
                    for verb in (4, 5):
                        self.assertIn(str(intvConv(step) * 1000), compact(AC.policy_value(verb, step, language)))
            with patch.object(self.world.USA, "getAvailableAid", return_value=844), \
                 patch.object(self.world.USA, "getAvailableMen", return_value=300):
                session, client = self.session(offline=True)
                answer = session.ask(self.world, "Poland", language=language)
                self.assertIsNone(client.messages)
                self.assertIn("8 440 млн долларов в год" if language == "ru" else "8,440 million USD/year", answer)
                self.assertIn("300 000 военнослужащих" if language == "ru" else "300,000 personnel", answer)
                self.assertNotIn("[0, 1", answer)
                self.assertNotIn("бюджет военной помощи: 844", answer)
                self.assertNotIn("budget units", answer)
                self.assertIn("военные базы" if language == "ru" else "Military bases", answer)
        policy = AC.my_policy(self.world, 0, 9)
        economic = policy["available_economic_aid"] * 100
        self.assertIn(AC._money(economic, "en"), policy["summary"])

    def test_beginner_advice_and_model_brief_have_only_visible_policy_groups_and_insurgency(self):
        self.world = World(1, False, 0)
        facts = AC.country_facts(self.world, 0, 9)
        self.assertEqual(facts["insurgency"], self.world.country[9].getInsurgency())
        self.assertNotIn("government_stability", facts)
        for language in ("en", "ru"):
            session, client = self.session(offline=True)
            answer = session.ask(self.world, "Poland", language=language)
            self.assertIsNone(client.messages)
            self.assertIn("повстанческая активность" if language == "ru" else "insurgency:", answer)
            for hidden in ("стабильность", "устойчивость правительства", "stability", "договор:", "торговля:",
                           "экономическая помощь:", "дестабилизация:", "давление:", "treaty:", "trade:",
                           "economic aid:", "destabilization:", "pressure:"):
                self.assertNotIn(hidden, answer)
        briefing = AC.situation_text(self.world, 0, facts=AC.facts_block(self.world, 0, countries=[9]))
        for hidden in ("stability", "economic aid", "destabilization", "treaty", "trade", "pressure", "budget step", "troops step"):
            self.assertNotIn(hidden, briefing)
        self.assertIn("insurgency:", briefing)
        self.assertIn("million USD/year", briefing)
        self.assertNotIn("[0, 1", briefing)

    def test_offline_fallback_wording_is_read_only_for_both_languages(self):
        before, rng = pickle.dumps(self.world), random.getstate()
        for language in ("en", "ru"):
            session, _client = self.session(offline=True)
            session.ask(self.world, "Poland", language=language)
        self.assertEqual(pickle.dumps(self.world), before)
        self.assertEqual(random.getstate(), rng)


if __name__ == "__main__":
    unittest.main()
