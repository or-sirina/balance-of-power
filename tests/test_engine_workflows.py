"""Portable local campaign workflows and command-boundary overhead contracts."""
import _isolate  # noqa: F401
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from EngineBridge.service import GameService
from Net import GameFile
from Net.State import world_to_state


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.game = GameService(save_dir=self.tmp.name)
        self.counter = 0

    def cmd(self, command, args=None):
        self.counter += 1
        return self.game.handle(dict(id=str(self.counter), command=command,
                                     args=args or {}, expected_revision=self.game.revision))

    def start(self, level=3):
        self.assertTrue(self.cmd('new_game', dict(level=level, seed=7))['ok'])

    def snapshot(self):
        return GameFile.canonical_state_bytes(world_to_state(self.game.world))

    def test_named_slots_default_and_delete(self):
        self.start()
        before = self.snapshot()
        self.assertTrue(self.cmd('save')['ok'])
        self.assertTrue((Path(self.tmp.name) / 'prototype.bop').exists())
        self.assertTrue(self.cmd('save', {'slot': 'Кампания 1'})['ok'])
        listed = self.cmd('save_list')
        self.assertEqual(listed['last_slot'], 'Кампания 1')
        self.assertEqual(len(listed['saves']), 2)
        self.cmd('end_turn')
        self.assertTrue(self.cmd('load', {'slot': 'Кампания 1'})['ok'])
        self.assertEqual(before, self.snapshot())
        self.assertTrue(self.cmd('save_delete', {'slot': 'Кампания 1'})['ok'])
        self.assertEqual(len(self.cmd('save_list')['saves']), 1)
        damaged = Path(self.tmp.name) / 'damaged.bop'
        payload = (Path(self.tmp.name) / 'prototype.bop').read_bytes()
        damaged.write_bytes(payload[:-20])
        self.assertEqual(self.cmd('save_list')['last_slot'], 'prototype')

    def test_slot_traversal_and_symlink(self):
        self.start()
        for slot in ['../escape', '/tmp/escape', 'bad.bop', '', ' space', 'a\\b']:
            self.assertEqual(self.cmd('save', {'slot': slot})['error']['code'], 'invalid_slot')
        link = Path(self.tmp.name) / 'linked.bop'
        link.symlink_to(Path(self.tmp.name) / 'other.bop')
        self.assertFalse(self.cmd('save', {'slot': 'linked'})['ok'])

    def test_portable_roundtrip_and_invalid_import_preserves_campaign(self):
        self.start()
        self.cmd('select_country', {'country_id': 42})
        self.cmd('advisor', {'question': 'What next?', 'index': 0})
        state, rng = self.snapshot(), self.game._rng
        conversation = self.game.conversations.dump()
        presenter = self.game._presenter_state()
        path = Path(self.tmp.name) / 'portable.bopg'
        self.assertTrue(self.cmd('export_game', {'path': str(path)})['ok'])
        self.cmd('end_turn')
        self.assertTrue(self.cmd('import_game', {'path': str(path)})['ok'])
        self.assertEqual(state, self.snapshot())
        self.assertEqual(rng, self.game._rng)
        self.assertEqual(conversation, self.game.conversations.dump())
        self.assertEqual(presenter, self.game._presenter_state())
        self.assertEqual(self.game.selected_country, 42)
        path.write_bytes(b'not a game')
        self.assertFalse(self.cmd('import_game', {'path': str(path)})['ok'])
        self.assertEqual(state, self.snapshot())
        self.assertEqual(rng, self.game._rng)
        self.assertFalse(self.cmd('export_game', {'path': '../relative.bopg'})['ok'])

    def test_undo_restores_turn_start_and_exact_rng_replay(self):
        self.start()
        opening, rng = self.snapshot(), self.game._rng
        conversations = self.game.conversations.dump()
        self.cmd('intelligence', {'level': 5})
        self.cmd('advisor', {'question': 'What next?', 'index': 0})
        self.cmd('end_turn')
        self.assertTrue(self.game.undo_available)
        self.assertTrue(self.cmd('undo')['ok'])
        self.assertEqual(opening, self.snapshot())
        self.assertEqual(rng, self.game._rng)
        self.assertEqual(conversations, self.game.conversations.dump())
        self.assertFalse(self.cmd('undo')['ok'])
        self.cmd('end_turn')
        replay = self.snapshot()
        self.assertTrue(self.cmd('undo')['ok'])
        self.cmd('end_turn')
        self.assertEqual(replay, self.snapshot())

    def test_undo_guards_and_read_commands_skip_graph_snapshot(self):
        self.start()
        self.cmd('end_turn')
        self.game.world.winFlag = True
        self.assertFalse(self.game.undo_available)
        self.game.world.winFlag = False
        self.assertTrue(self.cmd('tutorial_start')['ok'])
        self.assertFalse(self.game.undo_available)
        self.assertFalse(self.cmd('undo')['ok'])
        self.assertTrue(self.cmd('tutorial_end')['ok'])
        self.assertTrue(self.game.undo_available)
        with patch('EngineBridge.service.world_to_state', side_effect=AssertionError('unnecessary graph snapshot')):
            self.assertTrue(self.cmd('state')['ok'])
            self.assertTrue(self.cmd('select_country', {'country_id': 42})['ok'])

    def test_network_session_blocks_local_campaign_workflows(self):
        self.start()
        self.cmd('end_turn')
        self.game.multiplayer.mode = 'host'
        self.assertFalse(self.game.undo_available)
        for command in ('save', 'load', 'save_delete', 'undo'):
            self.assertEqual(self.cmd(command)['error']['code'], 'network_active')
        self.assertTrue(self.cmd('save_list')['ok'])

    def test_hotseat_save_ready_side_and_undo_previous_year(self):
        self.assertTrue(self.cmd('multiplayer_hotseat', {'level': 3, 'seed': 7})['ok'])
        opening, rng = self.snapshot(), self.game._rng
        self.assertTrue(self.cmd('end_turn')['ok'])
        ready = self.game.multiplayer.capture_local()
        self.assertEqual(ready['ready'], [0])
        self.assertEqual(ready['local_side'], 1)
        self.assertTrue(self.cmd('save', {'slot': 'Hotseat'})['ok'])
        self.assertTrue(self.cmd('end_turn')['ok'])
        self.assertTrue(self.game.undo_available)
        self.assertTrue(self.cmd('undo')['ok'])
        self.assertEqual(opening, self.snapshot())
        self.assertEqual(rng, self.game._rng)
        self.assertEqual(self.game.multiplayer.local_side, 0)
        self.assertFalse(self.cmd('undo')['ok'])
        self.assertTrue(self.cmd('load', {'slot': 'Hotseat'})['ok'])
        self.assertEqual(ready, self.game.multiplayer.capture_local())
        self.assertTrue(self.game.world.twoPFlag)

    def test_opponent_log_readonly_redacted_delayed_and_no_client_calls(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        empty = self.cmd('opponent_log')
        self.assertTrue(empty['ok'])
        self.assertEqual(empty['opponent_log']['status'], 'no_game')
        self.start(level=5)
        year = self.game.world.year
        secret = 'private-gateway-credential'
        config = SimpleNamespace(api_key=secret, base_url='https://internal.example/api', usable=True)
        plan = SimpleNamespace(source='llm', actions=[('economic_aid', 42, 2)],
                               reasoning='Explain ' + secret + ' https://internal.example/api')
        client = Mock()
        client.config = config
        opponent = SimpleNamespace(config=config, client=client, disabled=False, offline=False,
            turn_log=[(year-1, plan.actions, plan.reasoning), (year, [(0, 2, 3)], 'CURRENT SECRET PLAN')],
            last_plan=plan, stats=dict(turns=2, llm=1, fallback=1, actions=4, api_key=secret),
            last_error='HTTP failed ' + secret + ' sk-fake-key https://internal.example/api')
        self.game.presenter.llm_opponent = opponent
        self.game._opponent_source = 'llm'
        before, rng, revision = self.snapshot(), self.game._rng, self.game.revision
        with patch('EngineBridge.service.world_to_state', side_effect=AssertionError('read-only command must not snapshot')):
            response = self.cmd('opponent_log')
        self.assertTrue(response['ok'])
        result = response['opponent_log']
        self.assertEqual(len(result['entries']), 1)
        self.assertIsNone(result['last_plan'])
        encoded = str(result)
        for value in (secret, 'internal.example', 'sk-fake-key', 'CURRENT SECRET PLAN'):
            self.assertNotIn(value, encoded)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(rng, self.game._rng)
        self.assertEqual(revision, self.game.revision)
        self.assertEqual(client.mock_calls, [])
        opponent.turn_log.pop()
        response = self.cmd('opponent_log')
        self.assertEqual(response['opponent_log']['last_plan']['actions'][0]['action'], 1)
        self.assertNotIn(secret, str(response['opponent_log']['last_plan']))

    def human_duel(self):
        from GameLogic.CrisisDuel import CrisisDuel
        from GameLogic.Globals import doPolicy
        self.assertTrue(self.cmd('multiplayer_hotseat', {'level': 4, 'seed': 7})['ok'])
        world = self.game.world
        doPolicy(world, world.USA, world.country[10], 3, 1)
        news = next(n for n in world.news if n.actor.id == 0 and n.target.id == 10)
        self.game.multiplayer.duel = CrisisDuel(world, news)
        return self.game.multiplayer.duel

    def test_human_crisis_briefing_four_advisors_local_context_and_validation(self):
        import json
        from GameLogic.LLMClient import LLMConfig
        duel = self.human_duel()
        duel.decide('contest')
        duel.decide('summit')
        class Client:
            config = LLMConfig(offline=False, api_key='fake-local-only-key', model='test', backend='chat')
            facts = None
            calls = 0
            malformed = False
            def chat(self, messages, **kwargs):
                self.calls += 1
                self.facts = json.loads(messages[-1]['content'])
                advisors = {a['key']: 'Recorded advice.' for a in self.facts['advisors']}
                if self.malformed: advisors.pop(next(iter(advisors)))
                return json.dumps({'reaction': 'Recorded reaction.', 'advisors': advisors})
        client = Client()
        before, rng = self.snapshot(), self.game._rng
        # Reading the UI context or asking without a configured client is local.
        result = self.cmd('crisis_dialogue', {'language': 'ru'})
        self.assertTrue(result['ok'])
        self.assertFalse(result['dialogue']['used_model'])
        self.assertEqual(len(result['dialogue']['advice']), 4)
        context = self.game.multiplayer.local_crisis_context()
        for index in range(4):
            response = self.cmd('advisor', {'index': index, 'question': 'Что делать?', 'language': 'ru'})
            self.assertTrue(response['ok'])
            self.assertIn(context['advice_ru'][index], response['advice']['text'])
        self.game.model_client_factory = lambda: client
        result = self.cmd('crisis_dialogue')
        self.assertTrue(result['ok'])
        self.assertTrue(result['dialogue']['used_model'])
        self.assertEqual(len(result['dialogue']['advice']), 4)
        self.assertEqual(client.facts['human_crisis']['phase'], 'summit')
        self.assertEqual(client.facts['human_crisis']['decider'], duel.decider.id)
        self.assertEqual(client.facts['human_crisis']['summitBy'], duel.summit_by.id)
        self.assertEqual(len(client.facts['advisors']), 4)
        self.assertFalse(client.facts['crisis_ended'])
        self.assertNotIn(client.config.api_key, json.dumps(client.facts))
        client.malformed = True
        result = self.cmd('crisis_dialogue')
        self.assertFalse(result['dialogue']['used_model'])
        self.assertEqual(result['dialogue']['status_code'], 'failed')
        self.assertEqual(len(result['dialogue']['advice']), 4)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(rng, self.game._rng)
        self.assertEqual(client.calls, 2)

    def test_human_crisis_reply_rejected_if_identity_changes_without_revision(self):
        import json
        import threading
        from GameLogic.LLMClient import LLMConfig
        duel = self.human_duel()
        entered, release = threading.Event(), threading.Event()
        class Client:
            config = LLMConfig(offline=False, api_key='fake-local-only-key', model='test', backend='chat')
            def chat(self, messages, **kwargs):
                facts = json.loads(messages[-1]['content'])
                entered.set()
                if not release.wait(5): raise RuntimeError('test release timed out')
                return json.dumps({'reaction': 'Old reaction.', 'advisors': {a['key']: 'Old advice.' for a in facts['advisors']}})
        self.game.model_client_factory = lambda: Client()
        result = []
        worker = threading.Thread(target=lambda: result.append(self.cmd('crisis_dialogue')))
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            duel.decide('contest')
            after_transition, rng = self.snapshot(), self.game._rng
        finally:
            release.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertFalse(result[0]['ok'])
        self.assertEqual(result[0]['error']['code'], 'stale_advice')
        self.assertEqual(after_transition, self.snapshot())
        self.assertEqual(rng, self.game._rng)

    def test_valid_envelope_invalid_metadata_preserves_campaign(self):
        self.start()
        before, rng = self.snapshot(), self.game._rng
        doc = self.game._capture_document()
        doc['meta']['bridge']['rng'] = [1]
        path = Path(self.tmp.name) / 'bad.bopg'
        GameFile.write_game(str(path), doc['state'], meta=doc['meta'])
        self.assertFalse(self.cmd('import_game', {'path': str(path)})['ok'])
        self.assertEqual(before, self.snapshot())
        self.assertEqual(rng, self.game._rng)


if __name__ == '__main__':
    unittest.main()
