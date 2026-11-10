"""Offline director effects and normal challenge workflow, no provider calls."""
import _isolate  # noqa: F401
import copy
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from EngineBridge import game_master as gm
from GameLogic.World import World
from GameLogic.CrisisHandler import canQuestion, crisisEligible, doCHumanLoose, doCrisis
from EngineBridge.presenter import NewsPresenter
from GameLogic.Globals import doPolicy
from Net.State import world_to_state


class StandIn:
    def __init__(self, candidate):
        self.candidate = candidate
        self.calls = 0

    def chat_json(self, messages):
        self.calls += 1
        return dict(candidate_id=self.candidate['candidate_id'], headline='Fictional regional development',
                    headline_ru='Вымышленное региональное событие')


class GameMasterTests(unittest.TestCase):
    def setUp(self):
        self.world = World(4, False, 0)

    def proposal(self, kind):
        context = gm.prepare(self.world)
        candidate = next(c for c in context['candidates'] if c['kind'] == kind)
        client = StandIn(candidate)
        result = gm.request(client, context)
        self.assertEqual(client.calls, 1)
        return candidate, result

    def test_bounded_mechanical_events(self):
        for kind in ('unrest', 'economic_shock', 'diplomatic_incident'):
            with self.subTest(kind=kind):
                self.setUp()
                event, proposal = self.proposal(kind)
                outcome = gm.apply(self.world, proposal, 'ru')
                country = self.world.country[event['target']]
                actual = {'unrest': country.govtPopul, 'economic_shock': country.GNP,
                          'diplomatic_incident': country.diplOpinion[self.world.cmptr]}[kind]
                self.assertEqual(actual, event['new'])
                self.assertEqual(outcome['source'], 'ai_generated')
                self.assertTrue(any(n.text.startswith(gm.PREFIX_RU) for n in self.world.news))
                self.assertFalse(self.world.NWFlag)

    def test_economic_shock_preserves_each_sectors_spending_units(self):
        event, proposal = self.proposal('economic_shock')
        target = self.world.country[event['target']]
        old_spending = list(target.gnpSpnd)
        gm.apply(self.world, proposal)
        self.assertEqual(target.gnpSpnd, [v * event['new'] // event['old'] for v in old_spending])
        if old_spending[2] >= 100:
            self.assertGreaterEqual(target.gnpSpnd[2], old_spending[2] * 98 // 100)

    def test_flashpoint_is_real_reversible_policy_and_questionable(self):
        event, proposal = self.proposal('crisis_flashpoint')
        gm.apply(self.world, proposal)
        news = next(n for n in self.world.news if n.customText and n.customText.startswith(gm.PREFIX))
        self.assertTrue(crisisEligible(news))
        self.assertTrue(canQuestion(self.world, news))
        self.assertEqual(news.new, news.old + 1)
        self.assertFalse(self.world.crisis.hasBegun)
        # The regular opening calculation can make the opponent concede; that
        # must reverse this synthetic policy through hangLoose/doPolicy.
        parent = SimpleNamespace(world=self.world, llm_opponent=None)
        panel = NewsPresenter(parent)
        with patch('GameLogic.CrisisHandler.gimpt', return_value=10000):
            doCrisis(panel, self.world, news)
        self.assertTrue(news.crisisVal)
        self.assertTrue(self.world.crisis.backDown)
        self.assertFalse(self.world.crisis.hasBegun)
        from GameLogic.PolicyRules import policy_info
        self.assertEqual(policy_info(self.world, news.actor, news.action, news.target).old, event['old'])

    def test_invalid_is_atomic_and_duplicate_stale_rejected(self):
        event, proposal = self.proposal('unrest')
        before = world_to_state(self.world)
        bad = dict(proposal, arbitrary='code')
        with self.assertRaises(gm.GameMasterError):
            gm.apply(self.world, bad)
        self.assertEqual(world_to_state(self.world), before)
        with self.assertRaises(gm.GameMasterError):
            gm.apply(self.world, dict(proposal, headline='x' * 241))
        gm.apply(self.world, proposal)
        saved = copy.deepcopy(self.world.gameMasterState)
        with self.assertRaises(gm.GameMasterError):
            gm.apply(self.world, proposal)
        self.assertEqual(self.world.gameMasterState, saved)
        self.world.year += 1
        with self.assertRaisesRegex(gm.GameMasterError, 'stale_response'):
            gm.apply(self.world, proposal)
        self.assertNotIn(event['target'], {c['target'] for c in gm.prepare(self.world)['candidates']})

    def test_generated_news_provenance_and_bilingual_presentation(self):
        from EngineBridge.news import present_news
        for kind in ('unrest', 'economic_shock', 'diplomatic_incident', 'crisis_flashpoint'):
            with self.subTest(kind=kind):
                self.setUp()
                event, proposal = self.proposal(kind)
                gm.apply(self.world, proposal, 'ru')
                news = next(n for n in self.world.news if getattr(n, 'source', '') == 'ai_generated')
                self.assertEqual(news.gmYear, self.world.year)
                self.assertEqual(news.gmKind, kind)
                rows = present_news(self.world, lambda n: canQuestion(self.world, n))
                row = next(r for r in rows if r['source'] == 'ai_generated')
                self.assertIn('AI-generated', row['headline'])
                self.assertIn('Создано ИИ', row['headline_ru'])
                self.assertIn(proposal['headline'], row['text'])
                self.assertIn(proposal['headline_ru'], row['text_ru'])
                self.assertNotIn('Историческое', row['type_ru'])
                self.assertNotIn('historical', row['category'])
                self.assertEqual(row['year'], self.world.year)
                self.assertEqual(row['category'] == 'policy', kind == 'crisis_flashpoint')
                self.assertEqual(row['questionable'], kind == 'crisis_flashpoint')
                self.assertEqual(gm.validate_state(self.world), self.world.gameMasterState)

    def test_every_event_survives_gamefile_roundtrip_without_repeat(self):
        from Net import GameFile
        from Net.State import clone_world
        from EngineBridge.news import present_news
        for kind in ('unrest', 'economic_shock', 'diplomatic_incident', 'crisis_flashpoint'):
            with self.subTest(kind=kind):
                self.setUp()
                _, proposal = self.proposal(kind)
                gm.apply(self.world, proposal)
                document = GameFile.loads(GameFile.dumps(world_to_state(self.world)))
                restored = clone_world(self.world)
                GameFile.install_into(restored, document)
                self.assertEqual(gm.validate_state(restored), self.world.gameMasterState)
                rows = present_news(restored, lambda n: canQuestion(restored, n))
                row = next(r for r in rows if r['source'] == 'ai_generated')
                self.assertEqual(row['questionable'], kind == 'crisis_flashpoint')
                with self.assertRaisesRegex(gm.GameMasterError, 'already_generated'):
                    gm.apply(restored, proposal)
                news = next(n for n in restored.news if getattr(n, 'source', '') == 'ai_generated')
                news.gmHeadline = ['malformed']
                with self.assertRaisesRegex(gm.GameMasterError, 'invalid_state'):
                    gm.validate_state(restored)

    def test_save_state_validation_rejects_unbounded_or_malformed_values(self):
        self.assertEqual(gm.validate_state(self.world), {})
        _, proposal = self.proposal('unrest')
        gm.apply(self.world, proposal)
        good = copy.deepcopy(self.world.gameMasterState)
        invalid = [dict(good, enabled=1), dict(good, language='zz'), dict(good, status='secret'),
                   dict(good, reason='Bearer token'), dict(good, last_attempt_year=True),
                   dict(good, unknown='value'), dict(good, history=good['history'] * 17)]
        for field, value in [('year', True), ('candidate_id', 'bad'), ('target', -1),
                             ('old', '10'), ('headline_ru', 'x' * 241), ('source', 'historical')]:
            bad = copy.deepcopy(good)
            bad['history'][0][field] = value
            invalid.append(bad)
        for state in invalid:
            self.world.gameMasterState = state
            with self.subTest(state=state), self.assertRaises(gm.GameMasterError):
                gm.validate_state(self.world)
        self.world.gameMasterState = good
        detached = gm.validate_state(self.world)
        detached['history'].clear()
        self.assertEqual(self.world.gameMasterState, good)

    def test_public_context_excludes_secrets_and_changed_candidates(self):
        event, proposal = self.proposal('unrest')
        context = gm.prepare(self.world)
        self.assertEqual(set(context), {'year', 'locale', 'countries', 'candidates'})
        self.world.country[event['target']].govtPopul += 1
        with self.assertRaisesRegex(gm.GameMasterError, 'invalid_candidate'):
            gm.apply(self.world, proposal)


if __name__ == '__main__':
    unittest.main()
