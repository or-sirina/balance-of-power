"""Game master lifecycle through the authoritative service; all models are fake."""
import _isolate  # noqa: F401
import copy
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from EngineBridge import GameService
from GameLogic.LLMClient import LLMError
from Net.State import world_to_state


class FakeClient:
    def __init__(self, failure=False, gate=None):
        self.calls = []
        self.failure = failure
        self.gate = gate
        self.started = threading.Event()

    def chat_json(self, messages):
        context = json.loads(messages[-1]['content'])
        self.calls.append(context)
        self.started.set()
        if self.gate is not None:
            if not self.gate.wait(5):
                raise LLMError('fake model timeout')
        if self.failure:
            raise LLMError('fake model failure')
        return dict(candidate_id=context['candidates'][0]['candidate_id'],
                    headline='Fictional regional development', headline_ru='Вымышленное региональное событие')


class FakeFactory:
    def __init__(self, client):
        self.client = client

    def resolve_gamemaster(self):
        return self.client, 'ready'


class EngineGameMasterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.client = FakeClient()
        self.service = GameService(save_dir=self.directory.name, model_client_factory=FakeFactory(self.client))
        self.serial = 0

    def command(self, name, args=None, service=None):
        service = service or self.service
        self.serial += 1
        return service.handle(dict(id='gm-%d' % self.serial, command=name, args=args or {},
                                   expected_revision=service.revision))

    def start(self, enabled=True):
        response = self.command('new_game', dict(side=0, level=3, seed=7, gamemaster_enabled=enabled))
        self.assertTrue(response['ok'], response)
        return response

    def test_opt_in_and_exactly_one_event_per_year(self):
        response = self.start(False)
        self.assertEqual(self.client.calls, [])
        self.assertFalse(response['state']['gamemaster']['enabled'])
        response = self.command('gamemaster_set_enabled', {'enabled':True})
        self.assertTrue(response['ok'], response)
        response = self.command('gamemaster_generate')
        self.assertTrue(response['ok'], response)
        self.assertEqual(len(self.client.calls), 1)
        history = copy.deepcopy(response['state']['gamemaster']['history'])
        response = self.command('gamemaster_generate')
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(response['state']['gamemaster']['history'], history)
        response = self.command('end_turn')
        self.assertTrue(response['ok'], response)
        self.assertEqual(len(self.client.calls), 2)
        self.assertEqual(len(response['state']['gamemaster']['history']), 2)

    def test_start_auto_and_save_load_do_not_repeat_year(self):
        response = self.start()
        self.assertEqual(len(self.client.calls), 1)
        history = copy.deepcopy(response['state']['gamemaster']['history'])
        self.assertTrue(self.command('save')['ok'])
        self.assertTrue(self.command('end_turn')['ok'])
        response = self.command('load')
        self.assertTrue(response['ok'], response)
        self.assertEqual(response['state']['gamemaster']['history'], history)
        calls = len(self.client.calls)
        self.command('gamemaster_generate')
        self.assertEqual(len(self.client.calls), calls)

    def test_portable_import_preserves_annual_guard(self):
        response = self.start()
        history = copy.deepcopy(response['state']['gamemaster']['history'])
        path = os.path.join(self.directory.name, 'director.bopg')
        response = self.command('export_game', {'path':path})
        self.assertTrue(response['ok'], response)
        self.start(False)
        response = self.command('import_game', {'path':path})
        self.assertTrue(response['ok'], response)
        self.assertEqual(response['state']['gamemaster']['history'], history)
        calls = len(self.client.calls)
        self.command('gamemaster_generate')
        self.assertEqual(len(self.client.calls), calls)

    def test_tutorial_and_hotseat_cannot_generate(self):
        self.start(False)
        self.assertTrue(self.command('tutorial_start')['ok'])
        calls = len(self.client.calls)
        self.command('gamemaster_set_enabled', {'enabled':True})
        self.command('gamemaster_generate')
        self.assertEqual(len(self.client.calls), calls)
        service = GameService(save_dir=self.directory.name, model_client_factory=FakeFactory(self.client))
        self.addCleanup(service.multiplayer.close)
        response = self.command('multiplayer_hotseat', {}, service)
        self.assertTrue(response['ok'], response)
        self.command('gamemaster_set_enabled', {'enabled':True}, service)
        self.command('gamemaster_generate', {}, service)
        self.assertEqual(len(self.client.calls), calls)

    def test_failure_has_no_partial_effects_and_is_visible(self):
        self.start(False)
        self.command('gamemaster_set_enabled', {'enabled':True})
        before = world_to_state(self.service.world)
        self.client.failure = True
        response = self.command('gamemaster_generate')
        after = world_to_state(self.service.world)
        before['world'].pop('gameMasterState', None)
        after['world'].pop('gameMasterState', None)
        self.assertEqual(before, after)
        gm = response['state']['gamemaster']
        self.assertEqual(gm['history'], [])
        self.assertTrue(gm['last_error'])
        self.assertEqual(gm['last_attempt_year'], self.service.world.year)
        self.command('gamemaster_generate')
        self.assertEqual(len(self.client.calls), 1)

    def test_no_factory_fails_soft(self):
        service = GameService(save_dir=self.directory.name)
        response = self.command('new_game', dict(side=0, level=3, seed=7, gamemaster_enabled=True), service)
        self.assertTrue(response['ok'], response)
        self.assertEqual(response['state']['gamemaster']['history'], [])
        self.assertNotEqual(response['state']['gamemaster']['status'], 'ready')

    def test_application_exception_rolls_back_partial_event(self):
        self.start(False)
        self.command('gamemaster_set_enabled', {'enabled': True})
        before = world_to_state(self.service.world)
        def broken_apply(world, proposal, language):
            world.country[2].govtPopul -= 2
            world.news.clear()
            raise ValueError('injected failure after partial mutation')
        with patch('EngineBridge.service.game_master.apply', side_effect=broken_apply):
            response = self.command('gamemaster_generate')
        self.assertTrue(response['ok'], response)
        after = world_to_state(self.service.world)
        before['world'].pop('gameMasterState', None)
        after['world'].pop('gameMasterState', None)
        self.assertEqual(before, after)
        self.assertEqual(response['state']['gamemaster']['reason'], 'request_failed')

    def test_factory_failure_does_not_abort_campaign_start(self):
        class BrokenFactory:
            def resolve_gamemaster(self):
                raise RuntimeError('fake resolver failure')
        service = GameService(save_dir=self.directory.name, model_client_factory=BrokenFactory())
        response = self.command('new_game', dict(side=0, level=3, seed=7, gamemaster_enabled=True), service)
        self.assertTrue(response['ok'], response)
        self.assertEqual(response['state']['gamemaster']['history'], [])
        self.assertEqual(response['state']['gamemaster']['reason'], 'request_failed')
        self.assertTrue(response['state']['gamemaster']['last_error'])
        year = service.world.year
        response = self.command('end_turn', service=service)
        self.assertTrue(response['ok'], response)
        self.assertEqual(service.world.year, year + 1)
        self.assertEqual(response['state']['gamemaster']['history'], [])
        self.assertEqual(response['state']['gamemaster']['reason'], 'request_failed')

    def test_offline_factory_fails_soft_without_request(self):
        class OfflineFactory:
            def resolve_gamemaster(self):
                return None, 'offline'
        service = GameService(save_dir=self.directory.name, model_client_factory=OfflineFactory())
        response = self.command('new_game', dict(side=0, level=3, seed=7, gamemaster_enabled=True), service)
        self.assertTrue(response['ok'], response)
        self.assertEqual(response['state']['gamemaster']['history'], [])
        self.assertEqual(response['state']['gamemaster']['reason'], 'offline')

    def test_settings_revision_invalidates_pending_model_result(self):
        self.start(False)
        self.command('gamemaster_set_enabled', {'enabled':True})
        gate = threading.Event()
        self.addCleanup(gate.set)
        self.client.gate = gate
        before = copy.deepcopy(world_to_state(self.service.world))
        output = []
        worker = threading.Thread(target=lambda: output.append(self.command('gamemaster_generate')), daemon=True)
        worker.start()
        self.assertTrue(self.client.started.wait(3))
        response = self.command('settings_apply', {'offline':True})
        self.assertTrue(response['ok'], response)
        gate.set()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertFalse(output[0]['ok'])
        self.assertEqual(world_to_state(self.service.world), before)

    def test_model_wait_allows_reads_and_new_game_rejects_stale_result(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        self.client.gate = gate
        output = []
        worker = threading.Thread(target=lambda: output.append(self.command('new_game', dict(side=0, level=3, seed=7, gamemaster_enabled=True))), daemon=True)
        worker.start()
        self.assertTrue(self.client.started.wait(3))
        response = self.command('state')
        self.assertTrue(response['ok'], response)
        replacement = self.command('new_game', dict(side=0, level=3, seed=8, gamemaster_enabled=False))
        self.assertTrue(replacement['ok'], replacement)
        expected = copy.deepcopy(world_to_state(self.service.world))
        gate.set()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertFalse(output[0]['ok'])
        self.assertEqual(output[0]['error']['code'], 'stale_simulation')
        self.assertEqual(world_to_state(self.service.world), expected)
        self.assertEqual(self.service.view()['gamemaster']['history'], [])


if __name__ == '__main__':
    unittest.main()
