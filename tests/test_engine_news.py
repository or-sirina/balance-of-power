"""Presentation must preserve engine meanings, command ids and question rules."""
import _isolate  # noqa: F401
import copy
import tempfile
import unittest

from EngineBridge import GameService
from EngineBridge.news import present_news
from GameLogic import CrisisHandler
from GameLogic.News import News
from GameLogic.HistoricalEvents import EVENTS
from Net.State import world_to_state
from constants import WORLD_EVENT


class NewsPresentationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.service = GameService(save_dir=self.directory.name)
        response = self.service.handle({"id": "start", "command": "new_game",
                                       "args": {"side": 0, "level": 4, "seed": 7}, "expected_revision": 0})
        self.assertTrue(response["ok"], response)
        self.world = self.service.world

    def render(self):
        return present_news(self.world, lambda n: CrisisHandler.canQuestion(self.world, n))

    def test_policy_preserves_rules_values_order_and_world(self):
        w = self.world
        w.addNews(w.country[1], w.country[3], w.country[3], 2, 0, 2, False)
        before = copy.deepcopy(world_to_state(w))
        rows = self.render()
        self.assertEqual(world_to_state(w), before)
        for i, (row, news) in enumerate(zip(rows, w.news)):
            self.assertEqual(row["id"], i)
            self.assertEqual(row["questionable"], CrisisHandler.canQuestion(w, news))
            self.assertEqual(row["importance"], news.importance)
        row = next(r for r in rows if r["actor"] == 1 and r["target"] == 3 and r["action"] == 2)
        self.assertEqual(row["category"], "policy")
        self.assertTrue(row["new_text"])
        self.assertIn("млн", row["new_text_ru"])
        self.assertIsNone(row["year"])
        self.assertEqual(row["country_id"], 3)
        self.assertIn("increased", row["headline"])
        self.assertIn("повышение военной помощи", row["headline_ru"])
        self.assertLess(len(row["headline_ru"]), len(row["text_ru"]))
        self.assertIn("government", row["context"])
        self.assertNotEqual(row["headline"], row["text"])

    def test_domestic_war_and_alignment_are_not_policy_levels(self):
        w = self.world
        w.news = [News(w.country[3], 2, 0, 1, w.country[3], w.country[3], False),
                  News(w.country[4], 6, 2, 1, w.country[3], w.country[3], False),
                  News(w.country[0], 0, 0, 0, w.country[3], w.country[3], True)]
        rows = self.render()
        self.assertEqual([r["category"] for r in rows], ["domestic", "war", "diplomacy"])
        self.assertEqual([r["country_id"] for r in rows], [3, 3, 3])
        for row in rows:
            self.assertEqual(row["old_text"], "")
            self.assertEqual(row["new_text_ru"], "")
            self.assertIsNone(row["year"])

    def test_known_history_date_and_duplicate_identities(self):
        w = self.world
        event = next(e for e in EVENTS if isinstance(e.headline, str))
        a = w.country[event.actor]
        h = w.country[event.victim if event.victim is not None else event.actor]
        known = News(h, WORLD_EVENT, 0, 0, a, h, False, text=event.headline)
        unknown = News(h, WORLD_EVENT, 0, 0, a, h, False, text="Custom report")
        w.news = [known, copy.copy(known), unknown]
        rows = self.render()
        self.assertEqual(rows[0]["year"], event.year)
        self.assertIsNone(rows[2]["year"])
        self.assertEqual(len({r["story_key"] for r in rows}), 3)
        self.assertEqual(rows, self.render())

    def test_identity_survives_policy_amendment_but_not_feed_year(self):
        w = self.world
        n = News(w.country[3], 2, 0, 1, w.country[1], w.country[3], False)
        w.news = [n]
        key = self.render()[0]["story_key"]
        n.new = 2
        n.setStrings()
        self.assertEqual(self.render()[0]["story_key"], key)
        self.assertIn("increased", self.render()[0]["headline"])
        n.new = 0
        n.setStrings()
        self.assertIn("unchanged", self.render()[0]["headline"])
        n.new, n.old = 0, 2
        n.setStrings()
        self.assertIn("reduced", self.render()[0]["headline"])
        self.assertIn("снижение", self.render()[0]["headline_ru"])
        w.year += 1
        self.assertNotEqual(self.render()[0]["story_key"], key)


if __name__ == "__main__":
    unittest.main()
