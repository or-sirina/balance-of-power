"""Qt-free host authority, hotseat and legacy portable mail transport.

TCP uses the existing BOP1 framing; only the host executes rule functions.
No model client, provider credential or RNG state is transmitted to peers.
"""
import copy
import json
import hashlib
import random
import socket
import threading
import time
import secrets
import uuid

from Net.Protocol import FrameReader, encode_message, ProtocolError
from Net.State import world_to_state, apply_state
from GameLogic.World import World
from GameLogic import MovePlanner, Objectives
from GameLogic.CrisisDuel import CrisisDuel, CrisisPrompt, contestable_news, prestige_at_risk
from GameLogic.Globals import doPolicy
from GameLogic.PolicyRules import check_request
from .presenter import Presenter
from .conversations import ConversationBook


class MultiplayerController:
    def __init__(self, service):
        self.service = service
        self.mode = ""
        self.status = "offline"
        self.local_side = 0
        self.ready = set()
        self.duel = None
        self.queue = []
        self.chat = []
        self.listener = None
        self.peer = None
        self.port = 0
        self.mail = None
        self.io_lock = threading.Lock()
        self.token = ''
        self.remote_revision = None
        self.endpoint = None
        self.games = []
        self.beacon = None
        self._resume_status = 'lobby'
        self._peer_responses = {}

    @property
    def active(self):
        return bool(self.mode)

    def local_crisis_context(self):
        """Detached, local-player crisis facts for explicit display-only advice.

        Guest payloads are re-bound against its mirror. Never lend the service's
        world or a live duel to importance/advisor calculations or a model.
        """
        if self.service.world is None:
            return None
        if self.mode == 'guest':
            payload = copy.deepcopy(getattr(self, 'remote_duel', None))
            if not payload:
                return None
            world = copy.deepcopy(self.service.world)
            prompt = CrisisPrompt(world, payload)
            news = prompt.news
            news.text = payload.get('headline', '')
        elif self.duel:
            world, duel = copy.deepcopy((self.service.world, self.duel))
            payload = duel.prompt()
            news = duel.news
            prompt = CrisisPrompt(world, payload, news)
        else:
            return None
        world.human, world.cmptr = self.local_side, 1-self.local_side
        world.crisis.hasBegun, world.crisis.backDown = True, False
        world.crisis.level, world.crisis.whichHead = prompt.level, news
        world.crisis.who, world.crisis.victim = news.actor, news.target
        from GameLogic.CrisisHandler import getAdvisorOpinion
        advice = [getAdvisorOpinion(world, news, i+1, reversed=news.actor.id != self.local_side)
                  for i in range(4)]
        deciding_risk = prompt.prestige_at_risk()
        local_risk = 0 if prompt.is_challenge_phase else prestige_at_risk(world, news, world.country[self.local_side], prompt.level)
        from .localization import crisis_advice_ru
        advice_ru = crisis_advice_ru(world, {'risk': [str(local_risk)], 'dialogue': None}, advice)
        fields = ('phase','level','decider','actor','challenged','victim','action','old','new','headline','summitBy')
        context = json.dumps({key: payload.get(key) for key in fields}, sort_keys=True)
        payload.update(advice=advice, advice_ru=advice_ru, prestige_at_risk=deciding_risk,
                       local_prestige_at_risk=local_risk)
        return dict(world=world, prompt=payload, headline=news, advice=advice, advice_ru=advice_ru,
                    prestige_at_risk=local_risk, context=context)

    def state(self):
        context = self.local_crisis_context()
        prompt = context['prompt'] if context else None
        return dict(active=self.active, mode=self.mode, status=self.status, local_side=self.local_side,
                    ready=sorted(self.ready), duel=prompt, chat=self.chat[-50:], port=self.port,
                    can_act=self.status == "playing" and prompt is None and self.local_side not in self.ready and (self.mode != "mail" or self.mail_to_move == self.local_side),
                    mail=getattr(self, "mail_status", None), games=self.games, transport="engine-bridge-v1")

    def _error(self, code, message):
        from .service import CommandError
        raise CommandError(code, message)

    def _response(self, request, ok=True, error=None):
        out = self.service._response(request.get("id"), ok, error, self.service._events)
        out["multiplayer"] = self.state()
        if out.get("state") is not None:
            out["state"]["multiplayer"] = self.state()
        return out

    def route(self, request):
        if not isinstance(request, dict):
            return None
        cmd, args = request.get("command"), request.get("args", {})
        controlled = cmd in ("policy", "end_turn", "intelligence", "crisis_choice", "question")
        if not (isinstance(cmd, str) and cmd.startswith("multiplayer_")) and not (self.active and controlled):
            if self.active and cmd in ("new_game", "tutorial_start", "tutorial_end"):
                return self._response(request, False, dict(code="multiplayer_active", message="Leave multiplayer first."))
            return None
        s = self.service
        try:
            if not isinstance(args, dict) or not isinstance(request.get("id"), str) or not 1 <= len(request['id']) <= 128:
                self._error("invalid_request", "A request id and object arguments are required.")
            fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode('utf8')).hexdigest()
            with s.lock:
                if request['id'] in s._responses:
                    previous, response = s._responses[request['id']]
                    if previous != fingerprint:
                        self._error('duplicate_id', 'Request id already used for different arguments.')
                    return copy.deepcopy(response)
            if cmd == 'multiplayer_discover':
                self._discover(args)
                with s.lock:
                    response = self._response(request)
                    s._remember(request['id'], fingerprint, response)
                return response
            if cmd in ("multiplayer_poll", "multiplayer_mail_poll"):
                response = self._poll(request)
                if response['ok']:
                    with s.lock:
                        s._remember(request['id'], fingerprint, response)
                return response
            with s.lock:
                fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode('utf8')).hexdigest()
                if request['id'] in getattr(self, '_seen', {}):
                    previous, response = self._seen[request['id']]
                    if previous != fingerprint:
                        self._error('duplicate_id', 'Request id already used for different arguments.')
                    return copy.deepcopy(response)
                if request.get("expected_revision") != s.revision:
                    self._error("stale_revision", "Refresh the position before acting.")
                s._events = []
                if controlled and self.mode == "guest":
                    result = self._remote(request)
                    if result['ok']:
                        if not hasattr(self, '_seen'):
                            self._seen = {}
                        self._seen[request['id']] = (fingerprint, copy.deepcopy(result))
                        s._remember(request['id'], fingerprint, result)
                    return result
                old_world = s.world
                backup = copy.deepcopy((s.world, self.duel, self.queue))
                old_campaign = (s.selected_country, s._turn_start, s._undo,
                                s._undo_used, s._tutorial_undo)
                old_chat, old_resume = self.chat, self._resume_status
                old_endpoint, old_port = self.endpoint, self.port
                old_rng, old_ready, old_side = s._rng, set(self.ready), self.local_side
                old_mode, old_status, old_presenter = self.mode, self.status, s.presenter
                old_conversations, old_source = s.conversations, s._opponent_source
                old_runtime = s.model_client_factory.capture_runtime() if hasattr(s.model_client_factory, 'capture_runtime') else None
                try:
                    with s._random_context():
                        if controlled:
                            self._action(cmd, args, self.local_side)
                        else:
                            self._command(cmd, args)
                except Exception:
                    if not old_mode and self.mode:
                        self.close()
                    self.mode, self.status, s.presenter = old_mode, old_status, old_presenter
                    s.conversations, s._opponent_source = old_conversations, old_source
                    if old_runtime is not None:
                        s.model_client_factory.restore_runtime(old_runtime)
                    # Session creation replaces the world rather than mutating
                    # the old campaign. Retain its graph and presenter references.
                    replaced_world = s.world is not old_world
                    s.world, self.duel, self.queue = backup
                    if replaced_world:
                        s.world = old_world
                    (s.selected_country, s._turn_start, s._undo,
                     s._undo_used, s._tutorial_undo) = old_campaign
                    self.chat, self._resume_status = old_chat, old_resume
                    self.endpoint, self.port = old_endpoint, old_port
                    s._events = []
                    s._rng, self.ready, self.local_side = old_rng, old_ready, old_side
                    raise
                if any(event['type'] == 'turn_completed' for event in s._events):
                    s.conversations.observe(s.world)
                if self.mode != 'guest':
                    s.revision += 1
                if self.mode == 'hotseat':
                    s._track_turn('new_game' if cmd == 'multiplayer_hotseat' else cmd)
                result = self._response(request)
                if not hasattr(self, '_seen'):
                    self._seen = {}
                self._seen[request['id']] = (fingerprint, copy.deepcopy(result))
                s._remember(request['id'], fingerprint, result)
                if len(self._seen) > 128:
                    self._seen.pop(next(iter(self._seen)))
                return result
        except Exception as exc:
            if self.mode == 'guest' and isinstance(exc, OSError):
                self.status = 'disconnected'
            return self._response(request, False, dict(code=getattr(exc, 'code', 'multiplayer_error'), message=str(exc)))

    def _new(self, args):
        s = self.service
        if s.tutorial.active:
            self._error('tutorial_active', 'Return to the campaign before starting multiplayer.')
        side, level, seed = args.get('side', 0), args.get('level', 1), args.get('seed', 1982)
        if type(side) is not int or side not in (0, 1) or type(level) is not int or level not in range(1, 6) or type(seed) is not int:
            self._error('invalid_argument', 'Invalid side, level or seed.')
        random.seed(seed)
        self.local_side = side
        s.world = World(level, True, side).repair()
        s.presenter = Presenter(s)
        s.conversations = ConversationBook()
        s._opponent_source = None
        if s.model_client_factory is not None and hasattr(s.model_client_factory, 'reset_game'):
            s.model_client_factory.reset_game()
        s.selected_country = None
        s._turn_start = s._undo = None
        MovePlanner.prePlanMove(s.world)
        MovePlanner.mainMove(s.presenter, s.world)
        Objectives.ensure_state(s.world)
        Objectives.snapshot(s.world)
        self.ready.clear()
        self.chat = []
        self._resume_status = 'lobby'
        self.queue = []
        self.duel = None
        s.emit('game_started', side=side, level=level, year=s.world.year)

    def _command(self, cmd, args):
        if cmd == 'multiplayer_leave':
            self.close()
            return
        if cmd == 'multiplayer_chat':
            text = args.get('text', '')
            if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1000:
                self._error('invalid_argument', 'Chat must contain 1 to 1000 characters.')
            if self.mode == 'guest':
                reply = self._rpc(dict(command=cmd, args=args))
                self._install(reply)
            else:
                self.chat.append(dict(side=self.local_side, text=text.strip()))
            return
        if cmd == 'multiplayer_reconnect':
            if self.mode != 'guest' or not self.endpoint:
                self._error('not_guest', 'Only a guest can reconnect.')
            self._connect()
            return
        if self.active and cmd not in ('multiplayer_start', 'multiplayer_mail_submit'):
            self._error('multiplayer_active', 'Leave the current session first.')
        if cmd in ('multiplayer_host', 'multiplayer_host_relay'):
            self._new(args)
            self.mode, self.status = 'host', 'waiting'
            if cmd == 'multiplayer_host_relay':
                self.endpoint = (str(args.get('address', '127.0.0.1')), int(args.get('port', 27835)))
                self.port = self.endpoint[1]
                threading.Thread(target=self._relay_loop, daemon=True).start()
            else:
                listener = socket.socket()
                try:
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    listener.bind((args.get('bind', '0.0.0.0'), int(args.get('port', 27835))))
                    listener.listen(1)
                except Exception:
                    listener.close()
                    raise
                self.listener, self.port = listener, listener.getsockname()[1]
                threading.Thread(target=self._accept, daemon=True).start()
                self._start_beacon()
        elif cmd == 'multiplayer_join':
            if self.service.tutorial.active:
                self._error('tutorial_active', 'Return to the campaign before joining multiplayer.')
            self.endpoint = (str(args.get('address', '127.0.0.1')), int(args.get('port', 27835)))
            self.token = ''
            self.mode, self.status = 'guest', 'connecting'
            self._connect()
            self.service.conversations = ConversationBook()
            self.service.selected_country = None
        elif cmd == 'multiplayer_start':
            if self.mode != 'host' or self.peer is None or self.status != 'lobby':
                self._error('not_ready', 'A guest must join before the host starts.')
            self.status = self._resume_status = 'playing'
        elif cmd == 'multiplayer_hotseat':
            self._new(args)
            self.mode, self.status = 'hotseat', 'playing'
        elif cmd in ('multiplayer_mail_create', 'multiplayer_mail_join'):
            from Net.MailGame import MailSession, default_marker_path, legacy_marker_paths
            self._new(args)
            self.mail = MailSession(args['directory'], args['game_id'], self.local_side,
                marker_path=default_marker_path(args['game_id'], self.local_side, args['directory']),
                legacy_markers=legacy_marker_paths(self.local_side, args['game_id']))
            self.mail.mailbox.ensure()
            if cmd.endswith('create'):
                self.mail.start_game(world_to_state(self.service.world))
            else:
                self.mail.load_marker()
                moves, problems = self.mail.mailbox.scan()
                if problems:
                    self._error('mail_error', '; '.join(p.describe() for p in problems))
                if not moves:
                    self._error('mail_error', 'No opening move in the folder.')
                if self.mail.pending_moves():
                    self.mail.apply_next(self.service.world)
                else:
                    from Net import GameFile
                    GameFile.install_into(self.service.world, moves[-1].loaded(retries=1))
            self.mail_to_move = self.service.world.human
            self.service.world.human, self.service.world.cmptr = self.local_side, 1-self.local_side
            self.mode, self.status = 'mail', 'playing'
            self._mail_status()
        elif cmd == 'multiplayer_mail_submit':
            if self.mode != 'mail':
                self._error('not_mail', 'Open a mail game first.')
            state = world_to_state(self.service.world)
            state['world']['human'], state['world']['cmptr'] = self.mail_to_move, 1-self.mail_to_move
            self.mail.submit(state)
            self._mail_status()
        else:
            self._error('unknown_command', 'Unknown multiplayer command.')

    def _action(self, cmd, args, side):
        s, w = self.service, self.service.world
        if self.status != 'playing' or w is None or s.ended:
            self._error('not_playing', 'The session is not playing.')
        if cmd == 'crisis_choice':
            if self.duel is None or self.duel.decider.id != side:
                self._error('wrong_side', 'The other player must decide.')
            choice = args.get('choice')
            if choice not in self.duel.choices():
                self._error('illegal_choice', 'Choose a current crisis option.')
            finished = self.duel.decide(choice)
            if w.NWFlag and not w.ANWFlag:
                w.warStarter = side
            if finished:
                self.duel.finish()
                self.duel = None
                self._next_crisis()
            if self.mode == 'hotseat' and self.duel:
                self.local_side = self.duel.decider.id
            w.human, w.cmptr = self.local_side, 1-(self.local_side)
            return
        if self.duel or side in self.ready:
            self._error('turn_locked', 'Wait for the other player or resolve the crisis.')
        if self.mode == 'mail' and self.mail_to_move != side:
            self._error('wrong_side', 'Load the opponent move before playing.')
        if cmd == 'policy':
            target, action, value = args.get('target'), args.get('action'), args.get('value')
            if any(type(v) is not int for v in (target, action, value)) or target not in range(2,80) or action not in range(9) or value not in range(6):
                self._error('invalid_argument', 'Invalid policy values.')
            ok, reason = check_request(w, w.country[side], action, target, value)
            if not ok:
                self._error('illegal_policy', reason)
            doPolicy(w, w.country[side], w.country[target], action, value)
            s.emit('policy_applied', actor=side, target=target, action=action, new=value)
        elif cmd == 'intelligence':
            value = args.get('level')
            if type(value) is not int or value not in range(6):
                self._error('invalid_argument', 'Invalid intelligence level.')
            old = w.intel[side]
            w.intel[side] = value
            s.emit('intelligence_changed', old=old, new=value)
        elif cmd == 'end_turn':
            self.ready.add(side)
            if self.mode == 'mail':
                self.ready.clear()
                MovePlanner.prePlanMove(w)
                self._accumulate_nastiness()
                MovePlanner.continueNextTurn(s.presenter, w)
                self.mail_to_move = 1-side
            elif len(self.ready) == 2:
                self.ready.clear()
                MovePlanner.prePlanMove(w)
                self._accumulate_nastiness()
                self.queue = list(contestable_news(w))
                self._next_crisis()
            elif self.mode == 'hotseat':
                self.local_side = 1-side
                w.human, w.cmptr = self.local_side, 1-(self.local_side)
        else:
            self._error('unsupported_action', 'Two-player crises are queued when both players end the year.')

    def _accumulate_nastiness(self):
        from constants import DESTAB, INGSINTV, INSGAID, PRESSURE
        w = self.service.world
        for n in w.news:
            if n.action in (DESTAB, INGSINTV, INSGAID, PRESSURE) and n.actor.id < 2:
                w.nastiness = max(1, min(127, w.nastiness+n.new-n.old))

    def _next_crisis(self):
        w = self.service.world
        if w.NWFlag or w.ANWFlag:
            self.queue.clear()
            return
        while self.queue:
            news = self.queue.pop(0)
            if not news.crisisVal:
                self.duel = CrisisDuel(w, news)
                if self.mode == 'hotseat':
                    self.local_side = self.duel.decider.id
                    w.human, w.cmptr = self.local_side, 1-(self.local_side)
                return
        MovePlanner.continueNextTurn(self.service.presenter, w)

    def _wire(self, ok=True, error=None):
        return dict(ok=ok, error=error, revision=self.service.revision,
                    world=world_to_state(self.service.world) if self.service.world else None,
                    multiplayer=self.state())

    def _accept(self):
        listener = self.listener
        while self.listener is listener and self.mode == 'host':
            try:
                peer, _ = listener.accept()
            except OSError:
                return
            self._serve_peer(peer)

    def _relay_loop(self):
        endpoint = self.endpoint
        while self.mode == 'host' and self.endpoint == endpoint:
            try:
                peer = socket.create_connection(endpoint, timeout=5)
                peer.sendall(b'BOPR host\n')
                peer.settimeout(None)
                self._serve_peer(peer)
            except OSError:
                self.status = 'disconnected'
            # Short bounded wait; the daemon stops as soon as its session closes.
            for _ in range(20):
                if self.mode != 'host' or self.endpoint != endpoint:
                    return
                time.sleep(.1)

    def _serve_peer(self, peer):
        self.peer = peer
        identified = False
        reader = FrameReader()
        peer.settimeout(10)
        try:
            while self.mode == 'host':
                data = peer.recv(65536)
                if not data:
                    break
                for request in reader.feed(data):
                    with self.service.lock:
                        backup = copy.deepcopy((self.service.world, self.duel, self.queue))
                        old_rng, old_ready = self.service._rng, set(self.ready)
                        try:
                            if not isinstance(request, dict):
                                self._error('invalid_request', 'Expected an object.')
                            cmd = request.get('command')
                            if not identified:
                                if cmd != 'hello' or request.get('transport') != 'engine-bridge-v1':
                                    self._error('protocol_mismatch', 'This port requires the Godot engine bridge protocol.')
                                if self.token and not secrets.compare_digest(str(request.get('token', '')), self.token):
                                    self._error('seat_reserved', 'Reconnect requires the original guest token.')
                                if not self.token:
                                    self.token = secrets.token_hex(24)
                                identified = True
                                self.peer = peer
                                self.status = self._resume_status
                            request_id = request.get('id')
                            fingerprint = json.dumps(request, sort_keys=True)
                            if request_id in self._peer_responses:
                                old, reply = self._peer_responses[request_id]
                                if old != fingerprint:
                                    self._error('duplicate_id', 'Peer request id already used.')
                                peer.sendall(encode_message(reply))
                                continue
                            if cmd not in ('hello', 'poll'):
                                self.service._events = []
                                if request.get('revision') != self.service.revision:
                                    self._error('stale_revision', 'Refresh the host position before acting.')
                                with self.service._random_context():
                                    if cmd == 'multiplayer_chat':
                                        text = request.get('args', {}).get('text', '')
                                        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1000:
                                            self._error('invalid_argument', 'Invalid chat.')
                                        self.chat.append(dict(side=1-self.local_side, text=text.strip()))
                                    elif cmd in ('policy', 'intelligence', 'end_turn', 'crisis_choice'):
                                        self._action(cmd, request.get('args', {}), 1-self.local_side)
                                    else:
                                        self._error('unsupported_action', 'Unsupported peer command.')
                                if any(event['type'] == 'turn_completed' for event in self.service._events):
                                    self.service.conversations.observe(self.service.world)
                                self.service.revision += 1
                            reply = self._wire()
                            if cmd == 'hello':
                                reply['token'] = self.token
                            if cmd not in ('hello', 'poll') and isinstance(request_id, str):
                                self._peer_responses[request_id] = (fingerprint, copy.deepcopy(reply))
                                if len(self._peer_responses) > 128:
                                    self._peer_responses.pop(next(iter(self._peer_responses)))
                        except Exception as exc:
                            self.service.world, self.duel, self.queue = backup
                            self.service._rng, self.ready = old_rng, old_ready
                            reply = self._wire(False, dict(code=getattr(exc,'code','multiplayer_error'), message=str(exc)))
                            if not identified:
                                reply['world'] = None
                        peer.sendall(encode_message(reply))
                        if not identified:
                            return
        except (OSError, ValueError, ProtocolError):
            pass
        finally:
            peer.close()
            with self.service.lock:
                if self.peer is peer and self.mode == 'host':
                    if identified:
                        self._resume_status = self.status
                        self.status = 'disconnected'
                    self.peer = None

    def _connect(self):
        if self.peer:
            try:
                self.peer.close()
            except OSError:
                pass
        self.peer = socket.create_connection(self.endpoint, timeout=5)
        reply = self._rpc(dict(command='hello', args={}, token=self.token, transport='engine-bridge-v1'))
        if not reply.get('ok'):
            self._error(reply.get('error', {}).get('code', 'connection_error'), reply.get('error', {}).get('message', 'Connection refused.'))
        self.token = reply['token']
        self._install(reply)

    def _rpc(self, request):
        with self.io_lock:
            self.peer.sendall(encode_message(dict(request, revision=self.remote_revision if self.mode == 'guest' else self.service.revision)))
            reader = FrameReader()
            while True:
                data = self.peer.recv(65536)
                if not data:
                    self.status = 'disconnected'
                    raise OSError('The host disconnected.')
                messages = reader.feed(data)
                if messages:
                    return messages[0]

    def _install(self, reply):
        if reply.get('world') is not None:
            if self.service.world is None:
                self.service.world = World(1, True, 0).repair()
            apply_state(self.service.world, reply['world'])
            remote = reply['multiplayer']
            self.local_side = 1-remote['local_side']
            self.service.world.human, self.service.world.cmptr = self.local_side, 1-(self.local_side)
            self.status, self.ready, self.chat = remote['status'], set(remote['ready']), remote['chat']
            self.remote_duel = remote['duel']
            self.service.presenter = Presenter(self.service)
        previous_revision = self.remote_revision
        self.remote_revision = reply['revision']
        if previous_revision is None or previous_revision != self.remote_revision:
            self.service.revision += 1

    def _remote(self, request):
        reply = self._rpc(dict(id=request.get('id'), command=request['command'], args=request.get('args', {})))
        self._install(reply)
        return self._response(request, reply['ok'], reply.get('error'))

    def _poll(self, request):
        with self.service.lock:
            if self.mode == 'guest':
                try:
                    if self.status == 'disconnected':
                        self._connect()
                    return self._remote(dict(request, command='poll'))
                except OSError:
                    self.status = 'disconnected'
                    raise
            if self.mode == 'mail':
                if self.mail.pending_moves():
                    candidate = copy.deepcopy(self.service.world)
                    self.mail.apply_next(candidate)
                    self.service.world = candidate
                    self.mail_to_move = self.service.world.human
                    self.service.world.human, self.service.world.cmptr = self.local_side, 1-self.local_side
                    self.service.presenter = Presenter(self.service)
                    self.service.revision += 1
                self._mail_status()
            return self._response(request)

    def _mail_status(self):
        status = self.mail.status()
        self.mail_status = {key: status.get(key) for key in ('ok','folder','game','local_side','applied_seq','latest_seq','pending','to_move','my_turn','game_over','conflict')}
        self.mail_status['problems'] = [p.describe() for p in status.get('problems', [])]

    def close(self):
        listener, peer = self.listener, self.peer
        self.listener = self.peer = None
        self.mode, self.status = '', 'offline'
        self.endpoint = None
        self.token = ''
        self.remote_revision = None
        self._resume_status = 'lobby'
        self._peer_responses.clear()
        if self.beacon:
            self.beacon.close()
            self.beacon = None
        self.ready.clear()
        self.duel, self.queue, self.mail = None, [], None
        for connection in (peer, listener):
            if connection:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                connection.close()
        # A detached two-human world must not silently become a solo campaign.
        if self.service.world is not None and self.service.world.twoPFlag:
            self.service.world = None
            self.service.selected_country = None
        self.service._turn_start = self.service._undo = None

    def capture_local(self):
        """Portable hotseat state; network sessions are never locally restorable."""
        if self.mode != 'hotseat':
            return None
        w = self.service.world
        data = dict(mode='hotseat', local_side=self.local_side, ready=sorted(self.ready),
                    queue=[w.news.index(n) for n in self.queue], duel=None)
        if self.duel:
            d = self.duel
            data['duel'] = dict(news=w.news.index(d.news), level=d.level, phase=d.phase,
                decider=d.decider.id, resolved=d.resolved, nuclear=d.nuclear,
                accepted=d.accepted, reverted=d.reverted, outcome=d.outcome, log=copy.deepcopy(d.log),
                summit_by=None if d.summit_by is None else d.summit_by.id,
                summit=dict(d.summit), summit_used=sorted(d.summit_used))
        return data

    def restore_local(self, data):
        if not isinstance(data, dict) or data.get('mode') != 'hotseat':
            self._error('unsupported_save', 'Invalid hotseat metadata.')
        w = self.service.world
        side = data.get('local_side')
        ready = data.get('ready', [])
        if type(side) is not int or side not in (0,1) or any(type(v) is not int or v not in (0,1) for v in ready):
            self._error('unsupported_save', 'Invalid hotseat sides.')
        self.mode, self.status, self.local_side = 'hotseat', 'playing', side
        self.ready = set(ready)
        indices = data.get('queue', [])
        if not isinstance(indices, list) or any(type(i) is not int or not 0 <= i < len(w.news) for i in indices):
            self._error('unsupported_save', 'Invalid saved crisis queue.')
        self.queue = [w.news[i] for i in indices]
        self.duel = None
        if data.get('duel'):
            value = data['duel']
            if not isinstance(value, dict) or type(value.get('news')) is not int or not 0 <= value['news'] < len(w.news):
                self._error('unsupported_save', 'Invalid saved crisis headline.')
            for name in ('decider',):
                if type(value.get(name)) is not int or value[name] not in (0,1):
                    self._error('unsupported_save', 'Invalid saved crisis side.')
            if value.get('summit_by') is not None and (type(value['summit_by']) is not int or value['summit_by'] not in (0,1)):
                self._error('unsupported_save', 'Invalid summit side.')
            if type(value.get('level')) is not int or value['level'] not in range(1,10):
                self._error('unsupported_save', 'Invalid crisis level.')
            if any(type(value.get(name)) is not bool for name in ('resolved','nuclear','accepted','reverted')):
                self._error('unsupported_save', 'Invalid crisis flags.')
            if not isinstance(value.get('outcome'), str) or not isinstance(value.get('log'), list) or any(not isinstance(row,(list,tuple)) or len(row)!=2 or not isinstance(row[0],str) or type(row[1]) is not int for row in value['log']):
                self._error('unsupported_save', 'Invalid crisis log.')
            if not isinstance(value.get('summit'), dict) or any(str(k) not in ('0','1') or type(v) is not bool for k,v in value['summit'].items()):
                self._error('unsupported_save', 'Invalid summit votes.')
            if not isinstance(value.get('summit_used'), list) or any(type(v) is not int or v not in (0,1) for v in value['summit_used']):
                self._error('unsupported_save', 'Invalid summit history.')
            self.duel = CrisisDuel(w, w.news[value['news']])
            for name in ('level','phase','resolved','nuclear','accepted','reverted','outcome','log'):
                setattr(self.duel, name, copy.deepcopy(value[name]))
            self.duel.decider = w.country[value['decider']]
            self.duel.summit_by = None if value['summit_by'] is None else w.country[value['summit_by']]
            self.duel.summit = {int(k):v for k,v in value['summit'].items()}
            self.duel.summit_used = set(value['summit_used'])
            if self.duel.phase not in ('challenge','escalate','summit') or self.duel.level not in range(1,10):
                self._error('unsupported_save', 'Invalid saved crisis.')
        w.twoPFlag = True
        w.human, w.cmptr = side, 1-side

    def _start_beacon(self):
        from Net import DISCOVERY_MAGIC, DISCOVERY_PORT
        beacon = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        beacon.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            beacon.bind(('', DISCOVERY_PORT))
            beacon.settimeout(1)
        except OSError:
            beacon.close()
            return  # Manual address remains usable if UDP is occupied.
        self.beacon = beacon
        def serve():
            while self.beacon is beacon and self.mode == 'host':
                try:
                    data, address = beacon.recvfrom(8192)
                    probe = json.loads(data.decode('utf8'))
                    if not isinstance(probe, dict) or probe.get('magic') != DISCOVERY_MAGIC or not probe.get('probe'):
                        continue
                    reply = dict(magic=DISCOVERY_MAGIC, probe=False, game=dict(
                        port=self.port, name='Balance of Power · Godot', transport='engine-bridge-v1',
                        side=self.local_side, level=self.service.world.level, status=self.status))
                    beacon.sendto(json.dumps(reply).encode('utf8'), address)
                except socket.timeout:
                    continue
                except (OSError, ValueError, AttributeError):
                    if self.beacon is not beacon:
                        return
        threading.Thread(target=serve, daemon=True).start()

    def _discover(self, args):
        from Net import DISCOVERY_MAGIC, DISCOVERY_PORT
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        probe.bind(('',0))
        probe.settimeout(.15)
        found = {}
        try:
            payload = json.dumps(dict(magic=DISCOVERY_MAGIC, probe=True)).encode('utf8')
            for address in (args.get('address', '255.255.255.255'), '127.0.0.1'):
                probe.sendto(payload, (address, DISCOVERY_PORT))
            deadline = time.monotonic()+.6
            while time.monotonic() < deadline:
                try:
                    data, address = probe.recvfrom(8192)
                    reply = json.loads(data.decode('utf8'))
                    game = reply.get('game', {})
                    if reply.get('magic') == DISCOVERY_MAGIC and game.get('transport') == 'engine-bridge-v1':
                        game['address'] = address[0]
                        found['%s:%s' % (address[0], game.get('port'))] = game
                except (socket.timeout, ValueError, AttributeError):
                    continue
            self.games = list(found.values())
        finally:
            probe.close()
