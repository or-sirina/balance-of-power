"""Run paired full single-player campaigns through the bridge command boundary.

Run: python3 tests/test_engine_campaigns.py
"""
import _isolate  # noqa: F401 -- before any game imports

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from EngineBridge import GameService
from constants import GAME_END_YEAR
from GameLogic.LLMClient import LLMConfig
from GameLogic.LLMOpponent import LLMOpponent
from Net.GameFile import canonical_state_bytes
from Net.State import world_to_state


class Campaigns(unittest.TestCase):
    serial = 0

    def command(self, game, command, args=None):
        self.serial += 1
        request = {"id": str(self.serial), "command": command, "args": args or {},
                   "expected_revision": game.revision}
        response = game.handle(request)
        self.assertTrue(response['ok'], (command, args, response.get('error')))
        return response['state']

    def same(self, first, second):
        self.assertEqual(canonical_state_bytes(world_to_state(first.world)),
                         canonical_state_bytes(world_to_state(second.world)))
        self.assertEqual(first._rng, second._rng)
        a, b = first.view(), second.view()
        for key in ('year', 'side', 'level', 'scores', 'crisis', 'ended', 'nuclear'):
            self.assertEqual(a[key], b[key], key)

    def pair(self, first, second, command, args=None):
        a = self.command(first, command, args)
        self.command(second, command, args)
        self.same(first, second)
        return a

    def test_campaigns(self):
        for side in (0, 1):
            for level in range(1, 6):
                with self.subTest(side=side, level=level), tempfile.TemporaryDirectory() as directory:
                    # The original level-five opponent runs in explicitly offline mode.
                    factory = lambda: LLMOpponent(config=LLMConfig(offline=True))
                    first = GameService(save_dir=directory, opponent_factory=factory)
                    second = GameService(save_dir=directory, opponent_factory=factory)
                    state = self.pair(first, second, 'new_game', {'side': side, 'level': level, 'seed': 1234 + level * 10 + side})
                    saved = False
                    pending_saved = False
                    changes = questions = 0
                    years = [state['year']]
                    for turn in range(32):
                        if state['ended']:
                            break
                        # Respond until the crisis has actually released the turn.
                        for _ in range(40):
                            crisis = state['crisis']
                            if not crisis['active']:
                                break
                            if not pending_saved:
                                self.command(second, 'save')
                                self.command(second, 'load')
                                self.same(first, second)
                                pending_saved = saved = True
                            choices = crisis['choices']
                            self.assertTrue(choices, crisis)
                            choice = 'loose' if 'loose' in choices else 'continue'
                            state = self.pair(first, second, 'crisis_choice', {'choice': choice})
                            if state['ended']:
                                break
                        else:
                            self.fail('crisis did not finish')
                        if state['ended']:
                            break
                        if state['year'] not in years:
                            self.assertEqual(state['year'], years[-1] + 1)
                            years.append(state['year'])
                        if not saved and state['year'] >= 1988:
                            self.command(second, 'save')
                            self.command(second, 'load')
                            self.same(first, second)
                            saved = True
                        # Choose a legal change from the bridge's own policy menu.
                        target = 2 + (turn * 7 + level + side) % 78
                        state = self.pair(first, second, 'select_country', {'country_id': target})
                        policy = next(((p['action'], value) for p in state['selection']['policies']
                                       for value in p['steps'] if value != p['old']), None)
                        if policy:
                            state = self.pair(first, second, 'policy', {'target': target, 'action': policy[0], 'value': policy[1]})
                            changes += 1
                        if turn % 3 == 0:
                            news = next((item for item in state['news'] if item['questionable']), None)
                            if news:
                                state = self.pair(first, second, 'question', {'news_id': news['id']})
                                questions += 1
                                if state['crisis']['active']:
                                    continue
                        state = self.pair(first, second, 'end_turn')
                    self.assertTrue(state['ended'], (side, level, state['year']))
                    self.assertFalse(state['nuclear'], (side, level, state['year']))
                    self.assertEqual(state['year'], GAME_END_YEAR)
                    if state['year'] != years[-1]:
                        self.assertEqual(state['year'], years[-1] + 1)
                        years.append(state['year'])
                    self.assertEqual(years, list(range(1982, GAME_END_YEAR + 1)))
                    self.assertTrue(saved)
                    self.assertTrue(pending_saved)
                    self.assertGreater(questions, 0)
                    self.assertGreater(changes, 0)
                    print('side=%d level=%d years=%s changes=%d questions=%d pending_save=%s' %
                          (side, level, years, changes, questions, pending_saved), flush=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
