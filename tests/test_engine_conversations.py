#!/usr/bin/env python3
"""Campaign calibration survives bounded, validated bridge save/load metadata."""

import _isolate  # noqa: F401 -- never touch user memory/configuration or providers

import copy
import json
import os
from pathlib import Path
import pickle
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import Local
from EngineBridge.conversations import ConversationBook, MAX_METADATA_BYTES
from EngineBridge.service import GameService
from GameLogic.AdvisorMemory import ALIGNMENT_BASIS, MAX_PENDING
from GameLogic.Advisors import roster
from GameLogic.World import World
from Net import GameFile
from Net.State import world_to_state


class ConversationTests(unittest.TestCase):
    def world(self, side=0):
        world = World(5, False, side)
        world.year = 1982
        return world

    def prediction(self, book, world, index=0, language="en", country=9, direction=1, confidence=80):
        pending = book.prepare(index, language)
        copied = copy.deepcopy(world)
        copied.advisorGameId = book.generation
        pending["memory"].observe(copied, copied.human)
        pending["memory"].predict(copied, copied.human, roster(copied.human)[index].key,
                                  country, direction, confidence, Local.countryName(country))
        pending["history"] += [{"role": "user", "content": "Should we help %s?" % Local.countryName(country)},
                               {"role": "assistant", "content": "We should be cautious.\nPREDICTION: %s up %d" % (Local.countryName(country), confidence)}]
        self.assertTrue(book.commit(pending))

    def test_pending_prediction_and_resolved_record_survive_json_reload_both_sides(self):
        for side in (0, 1):
            with self.subTest(side=side):
                world, book = self.world(side), ConversationBook()
                world.country[9].diplOpinion[side] = -40
                self.prediction(book, world)
                loaded = ConversationBook.load(json.loads(json.dumps(book.dump())))
                self.assertNotEqual(loaded.generation, book.generation)
                self.assertEqual(loaded.details(0, "en")["statistics"]["open"], 1)
                world.year += 1
                world.country[9].diplOpinion[side] += 25
                self.assertTrue(loaded.observe(world))
                details = loaded.details(0, "en")
                self.assertEqual(details["statistics"]["resolved"], 1)
                self.assertEqual(details["statistics"]["hits"], 1)
                self.assertAlmostEqual(details["statistics"]["hit_rate"], 1)
                self.assertAlmostEqual(details["statistics"]["mean_confidence"], .8)
                self.assertAlmostEqual(details["statistics"]["brier"], .04)
                self.assertEqual(details["recent"][0]["delta"], 25)
                again = ConversationBook.load(json.loads(json.dumps(loaded.dump())))
                self.assertEqual(again.details(0, "en"), details)
                self.assertFalse(again.observe(world))
                self.assertEqual(again.details(0, "en")["statistics"]["resolved"], 1)

    def test_follow_up_after_load_keeps_prior_record_and_new_forecast(self):
        world, book = self.world(), ConversationBook()
        self.prediction(book, world, direction=0)
        world.year += 1
        book.observe(world)
        loaded = ConversationBook.load(book.dump())
        self.prediction(loaded, world, country=10, direction=-1, confidence=60)
        details = loaded.details(0, "en")
        self.assertEqual((details["statistics"]["resolved"], details["statistics"]["hits"], details["statistics"]["open"]), (1, 1, 1))
        self.assertEqual(details["pending"][0]["country_id"], 10)

    def test_languages_share_calibration_but_keep_transcripts_separate(self):
        world, book = self.world(), ConversationBook()
        self.prediction(book, world, language="en")
        self.assertEqual(book.details(0, "ru")["statistics"]["open"], 1)
        self.assertEqual(book.details(0, "ru")["history"], [])
        self.prediction(book, world, language="ru", country=10)
        for language in ("en", "ru"):
            self.assertEqual(book.details(0, language)["statistics"]["open"], 2)
            self.assertEqual(len(book.details(0, language)["history"]), 2)
        before = pickle.dumps(book)
        dumped = book.dump()
        self.assertEqual(pickle.dumps(book), before)
        self.assertEqual(sum("memory" in row for row in dumped), 1)
        loaded = ConversationBook.load(dumped)
        self.assertEqual(loaded.details(0, "ru")["statistics"]["open"], 2)

    def test_concurrent_language_or_observation_commit_cannot_overwrite_record(self):
        world, book = self.world(), ConversationBook()
        self.prediction(book, world)
        english, russian = book.prepare(0, "en"), book.prepare(0, "ru")
        self.assertTrue(book.commit(english))
        self.assertFalse(book.commit(russian))
        pending = book.prepare(0, "en")
        world.year += 1
        book.observe(world)
        self.assertFalse(book.commit(pending))
        self.assertEqual(book.details(0, "en")["statistics"]["resolved"], 1)

    def test_details_empty_and_populated_are_read_only_and_no_legacy_file_io(self):
        world, book = self.world(), ConversationBook()
        before = pickle.dumps(book)
        real_open = open
        def no_legacy_file(path, *args, **kwargs):
            if str(path) == "unused" or str(path).endswith("advisors_memory.json"):
                raise AssertionError("legacy memory I/O")
            return real_open(path, *args, **kwargs)
        with patch("builtins.open", side_effect=no_legacy_file):
            empty = book.details(0, "ru")
            self.assertEqual(pickle.dumps(book), before)
            self.assertEqual(empty["statistics"], {"resolved": 0, "hits": 0, "open": 0,
                                                  "hit_rate": None, "mean_confidence": None, "brier": None})
            self.prediction(book, world)
            before = pickle.dumps(book)
            details = book.details(0, "en")
            self.assertEqual(pickle.dumps(book), before)
            self.assertNotIn("PREDICTION", json.dumps(details["history"]))
            self.assertIn("ожидает проверки", details["pending"][0]["summary_ru"])

    def test_observe_and_round_trip_do_not_mutate_live_world_or_rng(self):
        world, book = self.world(), ConversationBook()
        self.prediction(book, world)
        world.year += 1
        before, rng = pickle.dumps(world), random.getstate()
        book.observe(world)
        loaded = ConversationBook.load(book.dump())
        loaded.details(0, "en")
        self.assertEqual(pickle.dumps(world), before)
        self.assertEqual(random.getstate(), rng)

    def test_history_only_legacy_rows_still_load_and_unsafe_roles_are_removed(self):
        book = ConversationBook.load([{"index": 0, "language": "ru", "history": [
            {"role": "system", "content": "PRIVATE SYSTEM PROMPT"},
            {"role": "tool", "content": "private tool result"},
            {"role": "user", "content": "api_key: fake-private-key"},
            {"role": "assistant", "content": "Действуйте осторожно.\nPREDICTION: Poland hold 60"}]}])
        details = book.details(0, "ru")
        rendered = json.dumps(details, ensure_ascii=False)
        self.assertNotIn("PRIVATE SYSTEM", rendered)
        self.assertNotIn("private tool", rendered)
        self.assertNotIn("fake-private-key", rendered)
        self.assertNotIn("PREDICTION", rendered)
        self.assertEqual(details["statistics"]["resolved"], 0)
        self.assertEqual(len(details["history"]), 2)

    def test_malformed_memory_types_nonfinite_values_and_unknown_schema_are_safe(self):
        base = {"index": 0, "language": "en", "history": []}
        bad = [None, [], "bad", {"schema": True}, {"schema": 99},
               {"schema": 1, "alignment_basis": "wrong direction"},
               {"schema": 1, "alignment_basis": ALIGNMENT_BASIS, "records": [], "pending": {}, "events": 3},
               {"schema": 1, "alignment_basis": ALIGNMENT_BASIS,
                "records": {"0:shultz": {"resolved": 10 ** 1000, "hits": float("nan")}},
                "pending": [[True, 1982, -1, 1, float("inf"), 0], [0, 1982, 999, 8, 101, -500]],
                "snapshot": {"alignment_basis": ALIGNMENT_BASIS, "year": float("nan"), "side": 0}}]
        for memory in bad:
            with self.subTest(memory_type=type(memory).__name__):
                book = ConversationBook.load([dict(base, memory=memory)])
                details = book.details(0, "en")
                self.assertEqual(details["statistics"]["resolved"], 0)
                self.assertEqual(details["statistics"]["open"], 0)
                json.dumps(book.dump(), allow_nan=False)
        self.assertFalse(ConversationBook.load({"wrong": "container"}).records)
        self.assertFalse(ConversationBook.load([{"index": True, "language": "en"}]).records)

    def test_imported_text_is_utf8_safe_and_redaction_stays_bounded(self):
        book = ConversationBook.load([{"index": 0, "language": "ru", "history": [
            {"role": "user", "content": "\ud800\x00 API-ключ: private-value"},
            {"role": "assistant", "content": "sk-a " * 1200}]}])
        details = book.details(0, "ru")
        text = json.dumps(details, ensure_ascii=False).encode("utf-8")
        self.assertNotIn(b"private-value", text)
        self.assertNotIn(b"sk-a", text)
        self.assertTrue(all(len(row["content"]) <= 6000 for row in details["history"]))

    def test_metadata_budget_keeps_aggregate_and_pending_forecasts(self):
        world, book = self.world(), ConversationBook()
        for index in range(4):
            pending = book.prepare(index, "en")
            copied = copy.deepcopy(world)
            copied.advisorGameId = book.generation
            pending["memory"].observe(copied, 0)
            for country in range(2, 2 + MAX_PENDING):
                pending["memory"].predict(copied, 0, roster(0)[index].key, country, 0, 70)
            pending["memory"].records["0:" + roster(0)[index].key] = {
                "resolved": 50, "hits": 35, "confidence_sum": 3500,
                "hit_confidence_sum": 2450, "brier_sum": 8, "recent": []}
            pending["history"] = [{"role": "user" if i % 2 == 0 else "assistant", "content": "Ж" * 6000} for i in range(12)]
            self.assertTrue(book.commit(pending))
            russian = book.prepare(index, "ru")
            russian["history"] = copy.deepcopy(pending["history"])
            self.assertTrue(book.commit(russian))
        before = pickle.dumps(book)
        dumped = book.dump()
        self.assertEqual(pickle.dumps(book), before)
        self.assertLessEqual(len(json.dumps(dumped, ensure_ascii=True).encode()), MAX_METADATA_BYTES)
        payload = GameFile.dumps(world_to_state(world), meta={"bridge": {
            "version": 1, "rng": random.getstate(), "presenter": {}, "conversations": dumped}})
        self.assertLess(len(payload.split(b"\n", 2)[1]), 64 * 1024)
        loaded = ConversationBook.load(dumped)
        for index in range(4):
            stats = loaded.details(index, "ru")["statistics"]
            self.assertEqual((stats["resolved"], stats["hits"], stats["open"]), (50, 35, MAX_PENDING))

    def test_actual_gamefile_header_round_trip_keeps_calibration(self):
        world, book = self.world(), ConversationBook()
        self.prediction(book, world)
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "campaign.bop"
            GameFile.write_game(str(filename), world_to_state(world), meta={"bridge": {"conversations": book.dump()}})
            document = GameFile.read_game(str(filename))
            loaded = ConversationBook.load(document["meta"]["bridge"]["conversations"])
        self.assertEqual(loaded.details(0, "en")["statistics"]["open"], 1)

    def test_training_uses_separate_calibration_and_restores_exact_campaign(self):
        service = GameService()
        request = lambda identity, command: service.handle({"id": identity, "command": command,
                                                           "expected_revision": service.revision})
        self.assertTrue(request("new", "new_game")["ok"])
        campaign = service.conversations
        self.prediction(campaign, service.world)
        before = campaign.dump()
        self.assertTrue(request("training", "tutorial_start")["ok"])
        self.assertIsNot(service.conversations, campaign)
        self.assertEqual(service.conversations.details(0, "en")["statistics"]["open"], 0)
        self.prediction(service.conversations, service.world, country=10)
        self.assertTrue(request("return", "tutorial_end")["ok"])
        self.assertIs(service.conversations, campaign)
        self.assertEqual(service.conversations.dump(), before)


if __name__ == "__main__":
    unittest.main()
