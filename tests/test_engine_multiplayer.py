import _isolate  # noqa: F401
import unittest
import tempfile
from pathlib import Path
import sys
import uuid

from EngineBridge.service import GameService


def call(service, command, **args):
    return service.handle(dict(id=uuid.uuid4().hex, command=command, args=args, expected_revision=service.revision))


class MultiplayerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)

    def test_loopback_authority_turn_chat_and_disconnect(self):
        tmp_path = self.tmp_path
        host, guest = GameService(tmp_path/'h'), GameService(tmp_path/'g')
        try:
            assert call(host, 'multiplayer_host', bind='127.0.0.1', port=0)['ok']
            assert call(guest, 'multiplayer_join', address='127.0.0.1', port=host.multiplayer.port)['ok']
            assert call(host, 'multiplayer_start')['ok']
            assert call(guest, 'multiplayer_poll')['ok']
            assert guest.world.human == 1 and host.world.human == 0
            assert host.world.twoPFlag and guest.world.twoPFlag
            assert call(guest, 'intelligence', level=3)['ok']
            assert host.world.intel[1] == 3 and host.world.intel[0] != 3
            # Guest actor arguments cannot impersonate the host.
            result = call(guest, 'intelligence', level=4, actor=0)
            assert result['ok'] and host.world.intel[1] == 4
            assert call(host, 'multiplayer_chat', text='hello')['ok']
            assert call(guest, 'multiplayer_poll')['ok']
            assert guest.multiplayer.chat[-1]['text'] == 'hello'
            year = host.world.year
            assert call(host, 'end_turn')['ok']
            assert host.world.year == year
            assert not call(host, 'intelligence', level=2)['ok']
            assert call(guest, 'multiplayer_poll')['ok']
            assert call(guest, 'end_turn')['ok']
            # Resolve actual policy-generated crises if any.
            for _ in range(12):
                duel = host.multiplayer.duel
                if duel is None:
                    break
                service = host if duel.decider.id == 0 else guest
                if service is guest:
                    assert call(guest, 'multiplayer_poll')['ok']
                assert call(service, 'crisis_choice', choice=duel.choices()[0])['ok']
            assert host.world.year == year+1
            assert call(guest, 'multiplayer_poll')['ok']
            assert guest.world.year == host.world.year
            assert not call(guest, 'new_game')['ok']
            assert call(guest, 'multiplayer_leave')['ok']
        finally:
            host.multiplayer.close()
            guest.multiplayer.close()


    def test_hotseat_both_sides_and_stale(self):
        tmp_path = self.tmp_path
        service = GameService(tmp_path)
        assert call(service, 'multiplayer_hotseat')['ok']
        year = service.world.year
        assert call(service, 'end_turn')['ok']
        assert service.world.human == 1
        assert call(service, 'intelligence', level=5)['ok']
        assert call(service, 'end_turn')['ok']
        assert service.world.year == year+1
        request = dict(id='stale', command='intelligence', args={'level': 1}, expected_revision=0)
        assert service.handle(request)['error']['code'] == 'stale_revision'
        assert service.world.intel[1] == 5


    def test_legacy_mail_roundtrip_without_qt(self):
        tmp_path = self.tmp_path
        host, guest = GameService(tmp_path/'h'), GameService(tmp_path/'g')
        directory = str(tmp_path/'mail')
        assert call(host, 'multiplayer_mail_create', directory=directory, game_id='test-game', side=0)['ok']
        assert call(guest, 'multiplayer_mail_join', directory=directory, game_id='test-game', side=1)['ok']
        assert not call(guest, 'intelligence', level=5)['ok']
        assert call(host, 'intelligence', level=4)['ok']
        assert call(host, 'end_turn')['ok']
        assert call(host, 'multiplayer_mail_submit')['ok']
        assert call(guest, 'multiplayer_mail_poll')['ok']
        assert guest.world.intel[0] == 4
        assert call(guest, 'intelligence', level=5)['ok']
        assert call(guest, 'end_turn')['ok']
        assert call(guest, 'multiplayer_mail_submit')['ok']
        assert call(host, 'multiplayer_mail_poll')['ok']
        assert host.world.intel[1] == 5
        import subprocess
        subprocess.run([sys.executable, '-c', "import sys; from EngineBridge.service import GameService; from Net.MailGame import MailSession; assert not any(n.startswith('PyQt5') for n in sys.modules)"], check=True)


    def test_actual_policy_and_duel_authority(self):
        tmp_path = self.tmp_path
        from GameLogic.CrisisDuel import CrisisDuel
        from GameLogic.PolicyRules import check_request
        host, guest = GameService(tmp_path/'h'), GameService(tmp_path/'g')
        try:
            assert call(host, 'multiplayer_host', bind='127.0.0.1', port=0, level=4)['ok']
            assert call(guest, 'multiplayer_join', address='127.0.0.1', port=host.multiplayer.port)['ok']
            assert call(host, 'multiplayer_start')['ok']
            assert call(guest, 'multiplayer_poll')['ok']
            before = list(host.world.USSR.govtAid)
            found = None
            for action in (3, 1, 0, 2, 4, 5, 6, 7, 8):
                for target in range(2,80):
                    for value in range(1,6):
                        if check_request(host.world, host.world.USSR, action, target, value)[0]:
                            found = dict(action=action, target=target, value=value)
                            break
                    if found:
                        break
                if found:
                    break
            assert found
            assert call(guest, 'policy', **found)['ok']
            news = next(n for n in host.world.news if n.actor.id == 1 and n.target.id == found['target'] and n.action == found['action'])
            host.multiplayer.duel = CrisisDuel(host.world, news)
            host.revision += 1
            assert call(guest, 'multiplayer_poll')['ok']
            assert not call(guest, 'crisis_choice', choice='contest')['ok']
            assert call(host, 'crisis_choice', choice='contest')['ok']
            assert call(guest, 'multiplayer_poll')['ok']
            assert call(guest, 'crisis_choice', choice='summit')['ok']
            assert call(host, 'crisis_choice', choice='yes')['ok']
            assert host.multiplayer.duel is None
            assert call(guest, 'multiplayer_poll')['ok']
            assert guest.world.year == host.world.year
        finally:
            host.multiplayer.close()
            guest.multiplayer.close()


    def test_discovery_reconnect_and_idempotency(self):
        tmp_path = self.tmp_path
        import socket
        host, guest = GameService(tmp_path/'h'), GameService(tmp_path/'g')
        try:
            assert call(host, 'multiplayer_host', bind='127.0.0.1', port=0)['ok']
            assert call(guest, 'multiplayer_discover', address='127.0.0.1')['ok']
            assert any(g['port'] == host.multiplayer.port for g in guest.multiplayer.games)
            assert call(guest, 'multiplayer_join', address='127.0.0.1', port=host.multiplayer.port)['ok']
            assert call(host, 'multiplayer_start')['ok']
            assert call(guest, 'multiplayer_poll')['ok']
            request = dict(id='repeat-ready', command='end_turn', args={}, expected_revision=guest.revision)
            first = guest.handle(request)
            assert first['ok']
            assert guest.handle(request) == first
            conflicting = dict(request, args={'actor':0})
            assert guest.handle(conflicting)['error']['code'] == 'duplicate_id'
            token = guest.multiplayer.token
            guest.multiplayer.peer.shutdown(socket.SHUT_RDWR)
            guest.multiplayer.peer.close()
            guest.multiplayer.status = 'disconnected'
            assert call(guest, 'multiplayer_reconnect')['ok']
            assert guest.multiplayer.token == token
            assert guest.multiplayer.ready == {1}
            assert guest.multiplayer.status == 'playing'
            assert call(host, 'end_turn')['ok']
            assert call(guest, 'multiplayer_poll')['ok']
            assert guest.world.year == host.world.year
        finally:
            host.multiplayer.close()
            guest.multiplayer.close()


    def test_teacher_relay_transport(self):
        tmp_path = self.tmp_path
        from relay import RelayServer
        relay = RelayServer(bind='127.0.0.1', first=0, count=1)
        host, guest = GameService(tmp_path/'h'), GameService(tmp_path/'g')
        relay.start()
        try:
            port = relay.ports[0]
            assert call(host, 'multiplayer_host_relay', address='127.0.0.1', port=port)['ok']
            assert call(guest, 'multiplayer_join', address='127.0.0.1', port=port)['ok']
            assert call(host, 'multiplayer_start')['ok']
            assert call(guest, 'multiplayer_poll')['ok']
            assert call(guest, 'intelligence', level=5)['ok']
            assert host.world.intel[1] == 5
            import socket
            guest.multiplayer.peer.shutdown(socket.SHUT_RDWR)
            guest.multiplayer.peer.close()
            guest.multiplayer.status = 'disconnected'
            assert call(guest, 'multiplayer_reconnect')['ok']
            assert guest.multiplayer.status == 'playing'
            assert call(host, 'end_turn')['ok']
            assert call(guest, 'multiplayer_poll')['ok']
            assert call(guest, 'end_turn')['ok']
            assert guest.world.year == host.world.year
        finally:
            host.multiplayer.close()
            guest.multiplayer.close()
            relay.stop()


    def test_hotseat_duel_portable_restore(self):
        tmp_path = self.tmp_path
        from GameLogic.CrisisDuel import CrisisDuel
        from GameLogic.Globals import doPolicy
        from Net.State import world_to_state
        service = GameService(tmp_path)
        assert call(service, 'multiplayer_hotseat', level=4)['ok']
        w = service.world
        doPolicy(w, w.USA, w.country[10], 3, 1)
        news = next(n for n in w.news if n.actor.id == 0 and n.target.id == 10)
        service.multiplayer.duel = CrisisDuel(w, news)
        service.multiplayer.duel.decide('contest')
        snapshot = service.multiplayer.capture_local()
        service.multiplayer.duel.decide('tough')
        assert snapshot['duel']['log'] != service.multiplayer.duel.log
        service.multiplayer.restore_local(snapshot)
        assert service.multiplayer.duel.phase == 'escalate'
        assert service.multiplayer.duel.decider.id == 0
        before = world_to_state(w)
        service.multiplayer.state()
        assert world_to_state(w) == before
        assert call(service, 'save', slot='duel')['ok']
        assert call(service, 'crisis_choice', choice='summit')['ok']
        assert call(service, 'load', slot='duel')['ok']
        assert service.multiplayer.duel.phase == 'escalate'
        assert service.multiplayer.duel.decider.id == 0
        assert call(service, 'crisis_choice', choice='back_down')['ok']

    def test_intelligence_cost_and_failed_policy_are_transactional(self):
        from Net.State import world_to_state
        from GameLogic.Globals import intel_cost, INTEL_COST_PER_LEVEL
        service = GameService(self.tmp_path)
        self.assertTrue(call(service, 'multiplayer_hotseat')['ok'])
        actor = service.world.USA
        before = actor.getAvailableAid()
        self.assertTrue(call(service, 'intelligence', level=5)['ok'])
        self.assertEqual(intel_cost(actor), 5*INTEL_COST_PER_LEVEL)
        self.assertEqual(actor.getAvailableAid(), max(0, before-10*INTEL_COST_PER_LEVEL))
        state, rng, revision = world_to_state(service.world), service._rng, service.revision
        failed = call(service, 'policy', action=99, target=10, value=3)
        self.assertFalse(failed['ok'])
        self.assertEqual(world_to_state(service.world), state)
        self.assertEqual(service._rng, rng)
        self.assertEqual(service.revision, revision)

    def test_duel_context_and_guest_advisors_are_readonly(self):
        from GameLogic.CrisisDuel import CrisisDuel
        from GameLogic.Globals import doPolicy
        from Net.State import world_to_state
        import random
        host, guest = GameService(self.tmp_path/'h'), GameService(self.tmp_path/'g')
        self.addCleanup(host.multiplayer.close)
        self.addCleanup(guest.multiplayer.close)
        self.assertTrue(call(host, 'multiplayer_host', bind='127.0.0.1', port=0, level=4)['ok'])
        self.assertTrue(call(guest, 'multiplayer_join', address='127.0.0.1', port=host.multiplayer.port)['ok'])
        self.assertTrue(call(host, 'multiplayer_start')['ok'])
        w = host.world
        doPolicy(w, w.USA, w.country[10], 3, 1)
        news = next(n for n in w.news if n.actor.id == 0 and n.target.id == 10)
        host.multiplayer.duel = CrisisDuel(w, news)
        host.multiplayer.duel.decide('contest')
        host.revision += 1
        self.assertTrue(call(guest, 'multiplayer_poll')['ok'])
        for service in (host, guest):
            state, rng, ambient = world_to_state(service.world), service._rng, random.getstate()
            context = service.multiplayer.local_crisis_context()
            dto = service.multiplayer.state()['duel']
            self.assertEqual(len(context['advice']), 4)
            self.assertEqual(len(dto['advice_ru']), 4)
            self.assertEqual(context['world'].human, service.multiplayer.local_side)
            self.assertIsNot(context['headline'].actor, service.world.country[context['headline'].actor.id])
            self.assertEqual(context['world'].crisis.level, dto['level'])
            self.assertEqual(world_to_state(service.world), state)
            self.assertEqual(service._rng, rng)
            self.assertEqual(random.getstate(), ambient)
            self.assertNotIn('token', dto)
            self.assertNotIn('rng', dto)
        old_context = host.multiplayer.local_crisis_context()['context']
        self.assertTrue(call(host, 'crisis_choice', choice='summit')['ok'])
        self.assertNotEqual(host.multiplayer.local_crisis_context()['context'], old_context)

    def test_guest_campaign_revision_stays_monotonic_and_host_rejects_stale(self):
        from Net.State import world_to_state
        host, guest = GameService(self.tmp_path/'h'), GameService(self.tmp_path/'g')
        self.addCleanup(host.multiplayer.close)
        self.addCleanup(guest.multiplayer.close)
        self.assertTrue(call(guest, 'new_game', seed=44)['ok'])
        for country in range(10, 20):
            self.assertTrue(call(guest, 'select_country', country_id=country)['ok'])
        old_revision = guest.revision
        self.assertTrue(call(host, 'multiplayer_host', bind='127.0.0.1', port=0)['ok'])
        response = call(guest, 'multiplayer_join', address='127.0.0.1', port=host.multiplayer.port)
        self.assertTrue(response['ok'])
        self.assertGreater(response['revision'], old_revision)
        self.assertTrue(call(host, 'multiplayer_start')['ok'])
        self.assertTrue(call(guest, 'multiplayer_poll')['ok'])
        self.assertTrue(call(host, 'end_turn')['ok'])
        state, rng, revision = world_to_state(host.world), host._rng, host.revision
        response = call(guest, 'intelligence', level=4)
        self.assertFalse(response['ok'])
        self.assertEqual(response['error']['code'], 'stale_revision')
        self.assertEqual(world_to_state(host.world), state)
        self.assertEqual(host._rng, rng)
        self.assertEqual(host.revision, revision)
        self.assertTrue(call(guest, 'multiplayer_poll')['ok'])
        self.assertTrue(call(guest, 'intelligence', level=4)['ok'])
        self.assertEqual(host.world.intel[1], 4)

    def test_partial_rule_failure_restores_world_rng_and_revision(self):
        from unittest.mock import patch
        from Net.State import world_to_state
        from GameLogic.PolicyRules import check_request
        from GameLogic.Globals import doPolicy
        import random
        service = GameService(self.tmp_path)
        self.assertTrue(call(service, 'multiplayer_hotseat', level=4)['ok'])
        target = next(i for i in range(2,80) if check_request(service.world, service.world.USA, 3, i, 1)[0])
        before, rng, revision = world_to_state(service.world), service._rng, service.revision
        def fail_after_mutating(*args, **kwargs):
            doPolicy(*args, **kwargs)
            random.random()
            raise RuntimeError('injected rule failure')
        with patch('EngineBridge.multiplayer.doPolicy', side_effect=fail_after_mutating):
            response = call(service, 'policy', action=3, target=target, value=1)
        self.assertFalse(response['ok'])
        self.assertEqual(world_to_state(service.world), before)
        self.assertEqual(service._rng, rng)
        self.assertEqual(service.revision, revision)
        self.assertEqual(service.multiplayer.ready, set())


    def test_failed_host_setup_preserves_campaign_and_undo(self):
        import socket
        from Net.State import world_to_state
        service = GameService(self.tmp_path)
        self.assertTrue(call(service, 'new_game')['ok'])
        self.assertTrue(call(service, 'end_turn')['ok'])
        self.assertTrue(call(service, 'select_country', country_id=3)['ok'])
        self.assertTrue(service.undo_available)
        world = service.world
        state, rng, revision = world_to_state(world), service._rng, service.revision
        turn_start, undo = service._turn_start, service._undo
        # A real occupied port exercises failure after _new has reset campaign
        # state, without relying on an external service or network.
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0))
            occupied.listen()
            response = call(service, 'multiplayer_host', bind='127.0.0.1',
                            port=occupied.getsockname()[1])
        self.assertFalse(response['ok'])
        self.assertEqual(response['events'], [])
        self.assertIs(service.world, world)
        self.assertEqual(world_to_state(service.world), state)
        self.assertEqual(service._rng, rng)
        self.assertEqual(service.revision, revision)
        self.assertEqual(service.selected_country, 3)
        self.assertIs(service._turn_start, turn_start)
        self.assertIs(service._undo, undo)
        self.assertTrue(service.undo_available)
        self.assertFalse(service.multiplayer.active)
        self.assertTrue(call(service, 'undo')['ok'])
        self.assertEqual(service.world.year, 1982)
