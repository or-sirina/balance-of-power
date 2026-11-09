"""Authoritative, revisioned command boundary for desktop engine frontends."""

import copy
import hashlib
import json
import random
import re
import threading
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import Local
import Paths
from constants import AVL_ACTIONS
from GameLogic import CrisisHandler, MovePlanner, Objectives
from GameLogic.Globals import doPolicy
from GameLogic.PolicyRules import check_request, policy_info
from GameLogic.World import World
from Net import GameFile
from Net.State import apply_state, clone_world, world_to_state

from .news import present_news
from .presenter import Presenter
from .localization import country_name, crisis_advice_ru, error_ru, model_status, news_ru, reason_ru, reaction_ru
from .tutorial import TutorialSession
from .conversations import ConversationBook
from .reports import ReportError, build_report
from .multiplayer import MultiplayerController
from .map_scene import build_map_scene
from .settings import SettingsError, SettingsService


_RANDOM_LOCK = threading.RLock()


class CommandError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise CommandError("invalid_argument", "%s must be an integer from %d to %d" % (name, low, high))
    return value


def _tuples(value):
    return tuple(_tuples(x) for x in value) if isinstance(value, list) else value


class GameService:
    """One local single-player game. All core mutation is serialized.

    model_client_factory is optional and called only after an explicit advice
    command. Injecting it allows tests to prove no remote call runs on startup.
    """

    def __init__(self, save_dir=None, model_client_factory=None, opponent_factory=None, settings_service=None):
        self.world = None
        self.revision = 0
        self.selected_country = None
        self.lock = threading.RLock()
        self._events = []
        self._responses = OrderedDict()
        self._inflight = set()
        self._busy = None
        self._rng = random.Random().getstate()
        self._save_dir = Path(save_dir) if save_dir is not None else None
        self.model_client_factory = model_client_factory
        self.opponent_factory = opponent_factory
        self._opponent_source = None
        self.presenter = Presenter(self)
        self.tutorial = TutorialSession()
        self.conversations = ConversationBook()
        self.settings = settings_service or SettingsService()
        self._settings_epoch = 0
        self._turn_start = None
        self._undo = None
        self._undo_used = False
        self._tutorial_undo = None
        self.multiplayer = MultiplayerController(self)

    def emit(self, kind, **values):
        self._events.append(dict(type=kind, **values))

    @contextmanager
    def _random_context(self):
        with _RANDOM_LOCK:
            previous = random.getstate()
            self._outside_rng = previous
            random.setstate(self._rng)
            try:
                yield
            finally:
                self._rng = random.getstate()
                random.setstate(self._outside_rng)

    def _run_remote(self, fn, timeout=None):
        """Suspend the core RNG scope while the original opponent awaits I/O.

        Called only by LLMOpponent.execute inside _random_context. Planning and
        answer sampling resume with the exact scenario stream after the wait.
        """
        current = random.getstate()
        random.setstate(self._outside_rng)
        _RANDOM_LOCK.release()
        try:
            return fn()
        finally:
            _RANDOM_LOCK.acquire()
            self._outside_rng = random.getstate()
            random.setstate(current)

    def _response(self, request_id, ok=True, error=None, events=None):
        result = {"id": request_id, "ok": ok, "revision": self.revision,
                  "state": self.view(), "events": list(events or [])}
        result["multiplayer"] = self.multiplayer.state()
        if error:
            result["error"] = dict(error)
            result["error"].setdefault("message_ru", error_ru(error["code"]))
        return result

    def handle(self, request):
        """Process one decoded request; errors never expose provider credentials."""
        request_id = request.get("id") if isinstance(request, dict) else None
        try:
            if not isinstance(request, dict) or not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
                raise CommandError("invalid_request", "id must be a nonempty string of at most 128 characters")
            command, args = request.get("command"), request.get("args", {})
            if not isinstance(command, str) or not isinstance(args, dict):
                raise CommandError("invalid_request", "command must be a string and args an object")
            routed = self.multiplayer.route(request)
            if routed is not None:
                return routed
            fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            with self.lock:
                if request_id in self._responses:
                    previous_fingerprint, response = self._responses[request_id]
                    if previous_fingerprint != fingerprint:
                        raise CommandError("duplicate_id", "request id was already used for a different request")
                    return copy.deepcopy(response)
                if request_id in self._inflight:
                    raise CommandError("request_in_progress", "this request is already being processed")
                if command not in ("state", "report", "save_list", "opponent_log", "advisor_history", "settings_get", "settings_apply", "settings_test") and request.get("expected_revision") != self.revision:
                    raise CommandError("stale_revision", "refresh state before sending this command")
                if self.tutorial.active and command in ("save", "load", "new_game", "import_game", "export_game", "undo"):
                    raise CommandError("tutorial_active", "return to the campaign before saving, loading or starting another game")
                if command in ("save", "load", "save_delete", "export_game", "import_game", "undo"):
                    self._guard_local()
                if self._busy is not None and command not in ("state", "report", "save_list", "opponent_log", "advisor_history", "settings_get", "settings_apply", "settings_test", "new_game", "load", "advisor", "crisis_dialogue"):
                    raise CommandError("turn_in_progress", "the opponent is resolving the current command")
                if command == "opponent_log":
                    response = self._response(request_id)
                    response["opponent_log"] = self._opponent_log()
                    self._remember(request_id, fingerprint, response)
                    return response
                if command == "save_list":
                    response = self._response(request_id)
                    response["saves"] = self._list_saves()
                    response["last_slot"] = response["saves"][0]["slot"] if response["saves"] else None
                    self._remember(request_id, fingerprint, response)
                    return response
                if command == "state" or (command == "select_country" and not self.tutorial.active):
                    # These commands cannot mutate the campaign graph. Avoid a
                    # complete rollback encoding merely to read or select it.
                    if command == "select_country":
                        self._require_world()
                        country_id = _integer(args.get("country_id"), "country_id", 0, len(self.world.country) - 1)
                        changed = self.selected_country != country_id
                        self.selected_country = country_id
                        if changed:
                            self.revision += 1
                        events = [{"type": "country_selected", "country_id": country_id}]
                    else:
                        events = []
                    response = self._response(request_id, events=events)
                    self._remember(request_id, fingerprint, response)
                    return response
                if command == "report":
                    self._require_world()
                    report = build_report(self.world, args, self.selected_country)
                    response = self._response(request_id)
                    response["report"] = report
                    self._remember(request_id, fingerprint, response)
                    return response
                if command == "advisor_history":
                    self._require_world()
                    index = _integer(args.get("index", 0), "index", 0, 3)
                    language = args.get("language", "en")
                    if language not in ("en", "ru"):
                        raise CommandError("invalid_argument", "language must be en or ru")
                    response = self._response(request_id)
                    response["history"] = self.conversations.details(index, language)
                    self._remember(request_id, fingerprint, response)
                    return response
                if command in ("settings_get", "settings_apply"):
                    settings = self.settings.get() if command == "settings_get" else self.settings.apply(args)
                    if command == "settings_apply":
                        self._settings_epoch += 1
                        self._refresh_model_settings()
                    response = self._response(request_id)
                    response["settings"] = settings
                    self._remember(request_id, fingerprint, response)
                    return response
                if command == "settings_test":
                    prepared = {"settings_probe": self.settings.prepare_test(args)}
                    self._inflight.add(request_id)
                elif command in ("advisor", "crisis_dialogue"):
                    prepared = self._prepare_advice(command, args)
                    self._inflight.add(request_id)
                elif self._needs_simulation(command, args):
                    simulation = self._simulation_copy()
                    prepared = {"revision": self.revision, "simulation": simulation, "settings_epoch": self._settings_epoch}
                    self._inflight.add(request_id)
                    self._busy = request_id
                else:
                    self._events = []
                    # Backup also retains exact object identity within the world.
                    old_world = self.world
                    old_state = world_to_state(old_world) if old_world is not None else None
                    old_rng, old_selection = self._rng, self.selected_country
                    old_undo = (self._turn_start, self._undo, self._undo_used, self._tutorial_undo)
                    old_presenter = self._presenter_state()
                    old_presenter_object = self.presenter
                    old_source = self._opponent_source
                    old_multiplayer = self.multiplayer
                    old_tutorial = copy.copy(self.tutorial)
                    old_conversations = self.conversations
                    old_opponent = self.presenter.llm_opponent
                    old_budget = getattr(old_opponent.config, "game_budget", None) if old_opponent is not None else None
                    model_snapshot = (self.model_client_factory.capture_runtime()
                        if hasattr(self.model_client_factory, "capture_runtime") else None)
                    try:
                        if command in ("tutorial_start", "tutorial_end"):
                            # Lifecycle switches install a whole saved RNG stream;
                            # an enclosing context would overwrite it on exit.
                            changed = self._execute(command, args)
                        else:
                            with self._random_context():
                                changed = self._execute(command, args)
                        changed = self.tutorial.observe(self, command, args, self._events) or changed
                        if any(event["type"] == "turn_completed" for event in self._events):
                            self.conversations.observe(self.world)
                        self._track_turn(command)
                    except Exception:
                        self.world, self._rng, self.selected_country = old_world, old_rng, old_selection
                        if old_world is not None and world_to_state(old_world) != old_state:
                            apply_state(old_world, old_state)
                        self.presenter = old_presenter_object
                        self._opponent_source, self.tutorial = old_source, old_tutorial
                        self.multiplayer = old_multiplayer
                        self._turn_start, self._undo, self._undo_used, self._tutorial_undo = old_undo
                        self.conversations = old_conversations
                        if old_opponent is not None:
                            old_opponent.config.game_budget = old_budget
                        if model_snapshot is not None:
                            self.model_client_factory.restore_runtime(model_snapshot)
                        self._restore_presenter(old_presenter)
                        self._bind_opponent()
                        raise
                    if changed:
                        self.revision += 1
                    if command in ("new_game", "load", "import_game"):
                        self._busy = None
                    response = self._response(request_id, events=self._events)
                    self._remember(request_id, fingerprint, response)
                    return response
            if "settings_probe" in prepared:
                try:
                    diagnostic = self.settings.run_test(prepared["settings_probe"])
                    with self.lock:
                        response = self._response(request_id)
                        response["test"] = diagnostic
                        self._remember(request_id, fingerprint, response)
                        return response
                finally:
                    with self.lock:
                        self._inflight.discard(request_id)
            if "simulation" in prepared:
                try:
                    simulation = prepared["simulation"]
                    with simulation._random_context():
                        changed = simulation._execute(command, args)
                    with self.lock:
                        if self.revision != prepared["revision"] or self._settings_epoch != prepared["settings_epoch"]:
                            raise CommandError("stale_simulation", "the game changed; the pending opponent result was discarded")
                        self.world, self._rng = simulation.world, simulation._rng
                        self.selected_country = simulation.selected_country
                        self.presenter = simulation.presenter
                        self.presenter.service = self
                        self._events = simulation._events
                        self._opponent_source = simulation._opponent_source
                        if command in ("new_game", "load", "import_game"):
                            self.conversations = simulation.conversations
                            self.multiplayer = simulation.multiplayer
                            self.multiplayer.service = self
                        if any(event["type"] == "turn_completed" for event in self._events):
                            self.conversations.observe(self.world)
                        self._track_turn(command)
                        self._bind_opponent()
                        if changed:
                            self.revision += 1
                        response = self._response(request_id, events=self._events)
                        self._remember(request_id, fingerprint, response)
                        return response
                finally:
                    with self.lock:
                        self._inflight.discard(request_id)
                        if self._busy == request_id:
                            self._busy = None
            # Remote/model waiting happens outside both the mutation lock and
            # the random context. Only copied facts and a cloned world leave it.
            try:
                event = self._run_advice(command, args, prepared)
            finally:
                with self.lock:
                    self._inflight.discard(request_id)
            with self.lock:
                if self.revision != prepared["revision"] or self._settings_epoch != prepared["settings_epoch"]:
                    raise CommandError("stale_advice", "the game changed while the advisor was answering")
                if prepared.get("human_crisis") is not None:
                    current = self.multiplayer.local_crisis_context()
                    if (current is None or current["context"] != prepared["human_crisis"]["context"]
                            or current["world"].human != prepared["world"].human):
                        raise CommandError("stale_advice", "the crisis changed while the advisor was answering")
                conversation = event.pop("_conversation", None)
                if conversation is not None and not self.conversations.commit(conversation):
                    raise CommandError("stale_advice", "this conversation changed while the advisor was answering")
                self._events = [event]
                if self.tutorial.observe(self, command, args, self._events):
                    self.revision += 1
                response = self._response(request_id, events=self._events)
                response["advice" if command == "advisor" else "dialogue"] = event["result"]
                self._remember(request_id, fingerprint, response)
                return response
        except (CommandError, ReportError) as exc:
            with self.lock:
                return self._response(request_id, False, {"code": exc.code, "message": str(exc)})
        except SettingsError as exc:
            with self.lock:
                return self._response(request_id, False, {"code": exc.code, "field": exc.field,
                    "message": exc.message, "message_ru": exc.message_ru})
        except (OSError, GameFile.GameFileError):
            with self.lock:
                return self._response(request_id, False, {"code": "save_error", "message": "The local save could not be read or written."})
        except Exception:
            with self.lock:
                return self._response(request_id, False, {"code": "command_failed", "message": "The command failed; the position was preserved."})

    def _remember(self, request_id, fingerprint, response):
        self._responses[request_id] = (fingerprint, copy.deepcopy(response))
        while len(self._responses) > 128:
            self._responses.popitem(last=False)

    def _needs_simulation(self, command, args):
        if self.opponent_factory is None:
            return False
        if command == "new_game":
            return args.get("level", 1) == 5
        if command in ("load", "import_game"):
            return True
        return self.world is not None and self.world.level == 5 and command in ("end_turn", "crisis_choice")

    def _simulation_copy(self):
        simulation = GameService(save_dir=self._save_dir, model_client_factory=self.model_client_factory,
                                 opponent_factory=self.opponent_factory)
        simulation.world = clone_world(self.world) if self.world is not None else None
        simulation.selected_country, simulation._rng = self.selected_country, self._rng
        simulation._opponent_source = self._opponent_source
        simulation._restore_presenter(self._presenter_state())
        opponent = self.presenter.llm_opponent
        if opponent is not None:
            cloned = copy.copy(opponent)
            # Clients/config hold locks and call counters. They are shared;
            # mutable strategic history and breaker counts belong to the clone.
            shared = {"config", "client", "jev", "execute", "notify", "record"}
            for key, value in opponent.__dict__.items():
                if key not in shared:
                    setattr(cloned, key, copy.deepcopy(value))
            simulation.presenter.llm_opponent = cloned
            simulation._bind_opponent()
        return simulation

    def _bind_opponent(self):
        opponent = self.presenter.llm_opponent
        if opponent is None:
            return
        opponent.execute = self._run_remote
        opponent.notify = lambda _text: self.emit("opponent_status", status="deliberating")
        opponent.record = self._record_opponent_plan
        budget = getattr(opponent.config, "game_budget", None)
        if budget is not None and hasattr(budget, "_owner"):
            import weakref
            budget._owner = weakref.ref(opponent)

    def _record_opponent_plan(self, plan):
        self._opponent_source = plan.source
        self.emit("opponent_plan", source=plan.source, actions=[list(item) for item in plan.actions])

    def _setup_opponent(self):
        if self.world.level == 5 and not self.world.twoPFlag and self.opponent_factory is not None:
            self.presenter.llm_opponent = self.opponent_factory()
            self._bind_opponent()

    def _refresh_model_settings(self):
        """Re-resolve saved settings without resetting the current call budget."""
        from GameLogic.AdvisorChat import chat_config
        from GameLogic.JevClient import JevClient
        from GameLogic.LLMClient import LLMClient, LLMConfig
        def fresh_client(client_type, config, previous):
            client = client_type(config)
            if hasattr(previous, "usage"):
                usage_lock = getattr(previous, "_lock", threading.RLock())
                with usage_lock:
                    client.usage.update(copy.deepcopy(previous.usage))
            return client
        factory = self.model_client_factory
        cached_config, cached_chat = factory.capture_runtime() if hasattr(factory, "capture_runtime") else (None, None)
        opponents = [self.presenter.llm_opponent]
        if self.tutorial.active and self.tutorial._campaign is not None:
            opponents.append(self.tutorial._campaign["presenter"].llm_opponent)
        for opponent in opponents:
            if opponent is None:
                continue
            resolved = LLMConfig()
            resolved.game_budget = getattr(opponent.config, "game_budget", None)
            opponent.config = resolved
            # Keep in-flight requests frozen on the old endpoint/configuration.
            # New clients share the existing budget and inherit usage counters.
            opponent.client = fresh_client(LLMClient, resolved, opponent.client)
            opponent.jev = fresh_client(JevClient, resolved, opponent.jev)
            opponent.backend = resolved.resolved_backend()
            opponent.reset_failures()
            if resolved.game_budget is not None and hasattr(resolved.game_budget, "_owner"):
                import weakref
                resolved.game_budget._owner = weakref.ref(opponent)
            cached_config = resolved
        if hasattr(factory, "restore_runtime"):
            resolved = cached_config if any(opponent is not None for opponent in opponents) else LLMConfig()
            if cached_config is not None:
                resolved.game_budget = getattr(cached_config, "game_budget", None)
            if cached_chat is not None:
                cached_chat = fresh_client(LLMClient, chat_config(resolved), cached_chat)
            factory.restore_runtime((resolved, cached_chat))

    def _require_world(self):
        if self.world is None:
            raise CommandError("no_game", "start or load a game first")

    def _require_turn(self):
        self._require_world()
        if self.ended:
            raise CommandError("game_ended", "this game has ended")
        if self.presenter.newsWindow.locked or self.world.beingQuestioned or self.world.crisis.hasBegun:
            raise CommandError("crisis_active", "resolve the current crisis first")

    @property
    def ended(self):
        return self.world is not None and bool(self.world.winFlag or self.world.NWFlag or self.world.ANWFlag)

    def _execute(self, command, args):
        if command == "state":
            return False
        if command == "tutorial_start":
            if not self.tutorial.active:
                self._tutorial_undo = (self._turn_start, self._undo, self._undo_used)
            self.tutorial.start(self)
            return True
        if command == "tutorial_end":
            changed = self.tutorial.end(self)
            if changed and self._tutorial_undo is not None:
                self._turn_start, self._undo, self._undo_used = self._tutorial_undo
                self._tutorial_undo = None
            return changed
        if command == "tutorial_ack":
            return self.tutorial.acknowledge(self)
        if command == "new_game":
            side = _integer(args.get("side", 0), "side", 0, 1)
            level = _integer(args.get("level", 1), "level", 1, 5)
            seed = _integer(args.get("seed", 1982), "seed", -(2**63), 2**63 - 1)
            random.seed(seed)
            if self.model_client_factory is not None and hasattr(self.model_client_factory, "reset_game"):
                self.model_client_factory.reset_game()
            self.presenter = Presenter(self)
            self.conversations = ConversationBook()
            self._opponent_source = None
            self.selected_country = None
            self.world = World(level, False, side).repair()
            Objectives.ensure_state(self.world)
            self._setup_opponent()
            MovePlanner.prePlanMove(self.world)
            MovePlanner.mainMove(self.presenter, self.world)
            Objectives.snapshot(self.world)
            self.emit("game_started", side=side, level=level, year=self.world.year)
            if level == 5 and self.presenter.llm_opponent is None:
                self.emit("opponent_fallback", reason="not_configured")
            return True
        if command in ("load", "import_game"):
            self._guard_local()
            self._load(args, portable=command == "import_game")
            return True
        if command == "save_delete":
            self._guard_local()
            self._slot(args).unlink()
            self.emit("save_deleted", slot=args.get("slot", "prototype"))
            return False
        self._require_world()
        if command == "select_country":
            country_id = _integer(args.get("country_id"), "country_id", 0, len(self.world.country) - 1)
            changed = self.selected_country != country_id
            self.selected_country = country_id
            self.emit("country_selected", country_id=country_id)
            return changed
        if command in ("save", "export_game"):
            self._guard_local()
            self._save(args, portable=command == "export_game")
            return False
        if command == "undo":
            self._guard_local()
            if not self.undo_available:
                raise CommandError("undo_unavailable", "Undo is unavailable in this position")
            self._install_document(copy.deepcopy(self._undo))
            self._undo_used = True
            self._turn_start = self._capture_document()
            self.emit("turn_undone", year=self.world.year)
            return True
        if command == "policy":
            self._require_turn()
            target = _integer(args.get("target"), "target", 2, 79)
            action = _integer(args.get("action"), "action", 0, 8)
            value = _integer(args.get("value"), "value", 0, 5)
            actor = self.world.country[self.world.human]
            ok, reason = check_request(self.world, actor, action, target, value)
            if not ok:
                raise CommandError("illegal_policy", reason)
            old = policy_info(self.world, actor, action, self.world.country[target]).old
            if old == value:
                return False
            doPolicy(self.world, actor, self.world.country[target], action, value)
            self.emit("policy_applied", actor=actor.id, target=target, action=action, old=old, new=value)
            return True
        if command == "end_turn":
            self._require_turn()
            MovePlanner.prePlanMove(self.world)
            CrisisHandler.reactNews(self.presenter, self.world)
            if self.presenter.newsWindow.locked:
                self.emit("crisis_started", level=self.world.crisis.level)
            return True
        if command == "question":
            self._require_turn()
            news_id = _integer(args.get("news_id"), "news_id", 0, len(self.world.news) - 1)
            news = self.world.news[news_id]
            if not CrisisHandler.canQuestion(self.world, news):
                raise CommandError("not_questionable", "this headline cannot be contested")
            panel = self.presenter.newsWindow
            panel.newsHline.setText(news.text)
            CrisisHandler.doCHumanTough(panel, self.world, news)
            self.emit("crisis_started", level=self.world.crisis.level, news_id=news_id)
            return True
        if command == "crisis_choice":
            panel, crisis = self.presenter.newsWindow, self.world.crisis
            if self.ended or not panel.locked or crisis.whichHead is None:
                raise CommandError("no_crisis", "there is no pending crisis decision")
            choice = args.get("choice")
            if choice not in self._crisis_choices():
                raise CommandError("illegal_choice", "choose one of the current crisis choices")
            if choice == "tough":
                CrisisHandler.doCHumanTough(panel, self.world, crisis.whichHead)
            else:
                CrisisHandler.doCHumanLoose(panel, self.world, crisis.whichHead)
            self.emit("crisis_choice_applied", choice=choice, level=self.world.crisis.level)
            return True
        if command == "intelligence":
            self._require_turn()
            level = _integer(args.get("level"), "level", 0, 5)
            old = self.world.intel[self.world.human]
            self.world.intel[self.world.human] = level
            self.emit("intelligence_changed", old=old, new=level)
            return old != level
        raise CommandError("unknown_command", "unknown command")

    def _crisis_choices(self):
        if self.world is None or self.ended or not self.presenter.newsWindow.locked:
            return []
        c, panel = self.world.crisis, self.presenter.newsWindow
        if c.backDown or not c.hasBegun:
            return self.tutorial.crisis_choices(["continue"])
        return self.tutorial.crisis_choices((["tough"] if panel.question.enabled else []) + ["loose"])

    def _presenter_state(self):
        panel = self.presenter.newsWindow
        return {"locked": panel.locked, "visible": panel.visible, "title": panel.title,
                "dialogue": copy.deepcopy(panel.dialogue),
                "fields": {name: {"text": getattr(panel, name).text, "enabled": getattr(panel, name).enabled}
                           for name in ("reactionLine", "question", "backDown", "newsHline")},
                "advice": [f.text for f in panel.advice], "risk": [f.text for f in panel.leftInfoVal]}

    def _restore_presenter(self, data):
        panel = self.presenter.newsWindow
        panel.locked, panel.visible, panel.title = data["locked"], data["visible"], data["title"]
        panel.dialogue = copy.deepcopy(data.get("dialogue"))
        for name, values in data["fields"].items():
            field = getattr(panel, name)
            field.text, field.enabled = values["text"], values["enabled"]
        for field, value in zip(panel.advice, data["advice"]):
            field.text = value
        for field, value in zip(panel.leftInfoVal, data["risk"]):
            field.text = value
        if self.world is not None:
            panel.refresh_news()

    def _opponent_log(self):
        """Existing recorded explanations only; never reveal the current plan.

        The original Qt log deliberately lags a year. No client method or
        configuration serialization belongs on this read-only boundary.
        """
        from GameLogic.LLMClient import _redact
        from GameLogic.LLMOpponent import ACTION_IDS, ACTION_NAME_ALIASES
        opponent = self.presenter.llm_opponent
        result = {"status": "no_game" if self.world is None else "unconfigured",
                  "entries": [], "stats": {}, "last_plan": None, "last_error": ""}
        if opponent is None:
            if self.world is not None and self.world.level != 5:
                result["status"] = "builtin"
            return result
        result["status"] = self._opponent_status()
        secrets = []
        for owner in (opponent, getattr(opponent, "client", None), getattr(opponent, "jev", None)):
            config = getattr(owner, "config", None)
            for key, value in vars(config).items() if hasattr(config, "__dict__") else ():
                if isinstance(value, str) and value and any(part in key.lower() for part in ("key", "secret", "token", "url", "endpoint")):
                    secrets.append(value)

        def clean(value):
            text = str(value or "")[:12000].replace("\x00", "")
            for secret in secrets:
                text = text.replace(secret, "***")
            text = _redact(text)
            text = re.sub(r"(?i)https?://[^\s<>\"']+", "[address hidden]", text)
            text = re.sub(r"(?i)\b(api[ _-]?key|token|secret|authorization)\s*[:=]\s*[^\s,;]+", r"\1: ***", text)
            return text[:6000]

        def actions(rows):
            out = []
            if not isinstance(rows, (list, tuple)):
                return out
            for row in rows[:64]:
                if not isinstance(row, (list, tuple)) or len(row) != 3:
                    continue
                action, target, value = row
                if isinstance(action, str):
                    action = ACTION_IDS.get(ACTION_NAME_ALIASES.get(action, action))
                if type(action) is int and action in range(9) and type(target) is int and target in range(80) and type(value) is int and value in range(6):
                    out.append({"action": action, "target": target, "value": value})
            return out

        log = getattr(opponent, "turn_log", [])
        for row in log[-64:] if isinstance(log, (list, tuple)) else ():
            if not isinstance(row, (list, tuple)) or len(row) != 3:
                continue
            year, policies, reasoning = row
            if type(year) is int and year < self.world.year:
                result["entries"].append({"year": year, "actions": actions(policies), "reasoning": clean(reasoning)})
        result["entries"] = result["entries"][-32:]
        stats = getattr(opponent, "stats", {})
        result["stats"] = {key: value for key in ("turns", "llm", "fallback", "actions")
                           if type(value := stats.get(key)) is int and 0 <= value <= 10**9}
        # Never expose a provider exception: it can contain request bodies,
        # gateway addresses, or credentials not recognizable as public keys.
        result["last_error"] = "model_failed" if getattr(opponent, "last_error", "") else ""
        plan = getattr(opponent, "last_plan", None)
        if plan is not None and log and type(log[-1][0]) is int and log[-1][0] < self.world.year:
            source = getattr(plan, "source", "")
            result["last_plan"] = {"source": source if source in ("llm", "jev", "mock", "fallback", "crisis") else "opponent",
                                   "actions": actions(getattr(plan, "actions", [])),
                                   "reasoning": clean(getattr(plan, "reasoning", ""))}
        return result

    def _network_active(self):
        network = getattr(self, "multiplayer", None)
        return bool(network is not None and getattr(network, "active", False)
                    and network.mode != "hotseat")

    def _guard_local(self):
        if self._network_active():
            raise CommandError("network_active", "Leave the network game before managing a local campaign")

    @property
    def undo_available(self):
        return bool(self.world is not None and self._undo is not None and not self._undo_used
                    and not self.ended and not self.tutorial.active and not self._network_active())

    def _capture_document(self):
        return {"state": world_to_state(self.world), "meta": {"bridge": {
            "version": 1, "rng": self._rng, "conversations": self.conversations.dump(),
            "selected_country": self.selected_country, "presenter": self._presenter_state(),
            "hotseat": self.multiplayer.capture_local()}}}

    def _track_turn(self, command):
        if self.world is None or self.tutorial.active or self._network_active():
            return
        if command in ("new_game", "load", "import_game"):
            self._turn_start = self._capture_document()
            self._undo, self._undo_used = None, False
        elif command != "undo" and any(event["type"] == "turn_completed" for event in self._events):
            self._undo = self._turn_start
            self._turn_start = self._capture_document()
            self._undo_used = False

    def _save_directory(self):
        directory = self._save_dir or Path(Paths.user_dir()) / "engine-bridge"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _slot(self, args):
        slot = args.get("slot", "prototype")
        if (not isinstance(slot, str) or not re.fullmatch(r"[\w -]{1,64}", slot, re.UNICODE)
                or slot != slot.strip() or any(k != "slot" for k in args)):
            raise CommandError("invalid_slot", "Use a slot name of 1–64 letters, numbers, spaces, hyphens or underscores")
        path = self._save_directory() / (slot + ".bop")
        if path.is_symlink():
            raise CommandError("invalid_slot", "Save slots cannot be symbolic links")
        return path

    def _portable_path(self, args, writing=False):
        raw = args.get("path")
        if not isinstance(raw, str) or not raw or set(args) != {"path"}:
            raise CommandError("invalid_path", "Choose a .bopg file")
        path = Path(raw)
        if not path.is_absolute() or path.suffix.lower() != ".bopg" or path.is_symlink():
            raise CommandError("invalid_path", "Choose an absolute .bopg file path")
        if writing and (not path.parent.is_dir() or (path.exists() and not path.is_file())):
            raise CommandError("invalid_path", "Choose an existing folder for the exported game")
        if not writing and (not path.is_file() or path.stat().st_size > GameFile.MAX_STATE_BYTES + 1024 * 1024):
            raise CommandError("invalid_path", "The selected game file is missing or too large")
        return path

    def _list_saves(self):
        items = []
        for path in self._save_directory().glob("*.bop"):
            try:
                self._slot({"slot": path.stem})
                if path.stat().st_size > GameFile.MAX_STATE_BYTES + 1024 * 1024:
                    continue
                header = GameFile.read_game(str(path), retries=1)
                if header.get("format") != GameFile.FORMAT_NAME or header.get("format_version") != 1:
                    continue
                meta = header.get("meta", {})
                created = header.get("created", 0)
                if type(created) not in (int, float) or not 0 <= created < 10**15:
                    continue
                items.append({"slot": path.stem, "year": meta.get("year"),
                              "side": meta.get("side"), "level": meta.get("level"),
                              "created": created})
            except (CommandError, GameFile.GameFileError, OSError, TypeError, ValueError):
                continue
        return sorted(items, key=lambda item: item["created"], reverse=True)

    def _save(self, args, portable=False):
        document = self._capture_document()
        document["meta"].update(year=self.world.year, side=self.world.human, level=self.world.level)
        # _save is executed within the service RNG context.
        document["meta"]["bridge"]["rng"] = random.getstate()
        path = self._portable_path(args, writing=True) if portable else self._slot(args)
        GameFile.write_game(str(path), document["state"], meta=document["meta"])
        self.emit("game_exported" if portable else "game_saved", slot=args.get("slot", "prototype"))

    def _load(self, args, portable=False):
        path = self._portable_path(args) if portable else self._slot(args)
        self._install_document(GameFile.read_game(str(path)))
        self.emit("game_imported" if portable else "game_loaded", slot=args.get("slot", "prototype"))

    def _install_document(self, document):
        state = document["state"]
        descriptor = state.get("world", {})
        side = _integer(descriptor.get("human"), "saved side", 0, 1)
        level = _integer(descriptor.get("level"), "saved level", 1, 5)
        candidate = World(level, False, side)
        GameFile.install_into(candidate, document)
        metadata = document.get("meta", {}).get("bridge")
        hotseat = metadata.get("hotseat") if isinstance(metadata, dict) else None
        local_controller = MultiplayerController(SimpleNamespace(world=candidate))
        if candidate.twoPFlag:
            if hotseat is None:
                raise CommandError("unsupported_save", "This multiplayer file has no hotseat session metadata")
            local_controller.restore_local(hotseat)
        elif hotseat is not None:
            raise CommandError("unsupported_save", "Hotseat metadata requires a two-player world")
        # Validate all metadata before replacing any active campaign objects.
        selected, restored_rng = None, None
        conversations = ConversationBook()
        if metadata:
            if metadata.get("version") != 1:
                raise CommandError("unsupported_save", "Unsupported bridge save version")
            restored_rng = _tuples(metadata["rng"])
            random.Random().setstate(restored_rng)
            selected = metadata.get("selected_country")
            if selected is not None:
                _integer(selected, "saved selection", 0, 79)
            conversations = ConversationBook.load(metadata.get("conversations", []))
        self.world = candidate.repair()
        self.multiplayer = local_controller
        self.multiplayer.service = self
        self.presenter = Presenter(self)
        self.conversations = conversations
        self._opponent_source = None
        self._setup_opponent()
        self.selected_country = selected
        if metadata:
            self._rng = restored_rng
            random.setstate(restored_rng)
            self._restore_presenter(metadata["presenter"])
        elif candidate.crisis.hasBegun:
            CrisisHandler.resumeCrisis(self.presenter.newsWindow, candidate)
        elif candidate.beingQuestioned:
            self.presenter.newsWindow.showUp()

    def view(self):
        if self.world is None:
            return None
        w, side = self.world, self.world.human
        actor = w.country[side]
        countries = [{"id": c.id, "name": Local.countryName(c.id),
                      "standing": c.diplOpinion[side], "our_opinion": actor.diplOpinion[c.id],
                      "prestige": c.prestigeVal, "sphere": c.dMess, "stability": c.getInsurgency()}
                     for c in w.country]
        selection = None
        if self.selected_country is not None:
            c = w.country[self.selected_country]
            selection = dict(countries[c.id], government_strength=c.govtStrength,
                             insurgent_strength=c.insgStrength, policies=[])
            if c.id >= 2:
                for action in AVL_ACTIONS[min(w.level, 5) - 1]:
                    info = policy_info(w, actor, action, c)
                    selection["policies"].append({"action": action, "old": info.old,
                        "steps": info.steps(), "ceiling": info.ceiling, "reason": info.reason,
                        "reason_ru": reason_ru(info.reason),
                        "available": info.avail})
        panel = self.presenter.newsWindow
        return {"year": w.year, "side": side, "level": w.level,
                "scores": [(p.historyScore[-1] if (w.NWFlag or w.ANWFlag) and p.historyScore else p.score - p.initScore)
                           for p in w.country[:2]],
                "tension": w.knownNastiness[side], "intelligence": w.intel[side],
                "intl_relations": w.USA.diplOpinion[1], "credibility": actor.integrity,
                "tension_error": MovePlanner.estimate_error(w.intel[side]),
                "countries": countries, "map_scene": build_map_scene(w),
                "selected_country": self.selected_country, "selection": selection,
                "news": present_news(w, lambda n: not self.ended and not panel.locked
                                     and CrisisHandler.canQuestion(w, n)),
                "crisis": {"active": panel.locked and not self.ended,
                           "headline": panel.newsHline.text, "reaction": panel.reactionLine.text,
                           "headline_ru": news_ru(w.crisis.whichHead) if w.crisis.whichHead is not None else "",
                           "reaction_ru": reaction_ru(w, panel.dialogue),
                           "choices": self._crisis_choices(), "level": w.crisis.level,
                           "started_by": None if w.crisis.who is None else w.crisis.who.id,
                           "human_is_actor": w.crisis.who is not None and w.crisis.who.id == side,
                           "speaker": None if panel.dialogue is None else panel.dialogue["speaker"],
                           "outcome": None if panel.dialogue is None else panel.dialogue["outcome"],
                           "advice": [field.text for field in panel.advice],
                           "prestige_at_risk": panel.leftInfoVal[0].text},
                "multiplayer": self.multiplayer.state(), "undo_available": self.undo_available, "ended": self.ended, "nuclear": bool(w.NWFlag or w.ANWFlag),
                "tutorial": self.tutorial.view(),
                "opponent": self._opponent_status()}

    def _opponent_status(self):
        opponent = self.presenter.llm_opponent
        if opponent is None:
            return "heuristic" if self.world.level < 5 else "heuristic_not_configured"
        if opponent.disabled:
            return "heuristic_model_unavailable"
        if opponent.offline:
            return "offline"
        if not opponent.config.usable:
            return "heuristic_not_configured"
        if self._opponent_source == "fallback":
            return "heuristic_fallback"
        return "model"

    def _prepare_advice(self, command, args):
        self._require_world()
        if args.get("language", "en") not in ("en", "ru"):
            raise CommandError("invalid_argument", "language must be en or ru")
        data = {"world": clone_world(self.world), "revision": self.revision,
                "selection": self.selected_country, "panel": self._presenter_state(),
                "settings_epoch": self._settings_epoch,
                "offline_training": self.tutorial.active}
        human_crisis = self.multiplayer.local_crisis_context()
        if human_crisis is not None:
            data["human_crisis"] = human_crisis
            data["world"] = human_crisis["world"]
            data["panel"]["locked"] = True
            data["panel"]["risk"] = [str(human_crisis["prestige_at_risk"])]
            data["panel"]["dialogue"] = {"speaker": 1 - data["world"].human,
                "outcome": human_crisis["prompt"].get("phase", "challenge"),
                "headline_text": human_crisis["headline"].text}
        if command == "advisor":
            _integer(args.get("index", 0), "index", 0, 3)
            question = args.get("question", "")
            if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
                raise CommandError("invalid_argument", "question must contain 1 to 2000 characters")
            data["conversation"] = self.conversations.prepare(args.get("index", 0), args.get("language", "en"))
        elif human_crisis is None and (not self.presenter.newsWindow.locked or self.world.crisis.whichHead is None):
            raise CommandError("no_crisis", "there is no crisis to discuss")
        return data

    def _run_advice(self, command, args, prepared):
        w = prepared["world"]
        client, availability = self._advice_client(prepared)
        language = args.get("language", "en")
        if command == "advisor":
            from GameLogic.AdvisorChat import AdvisorSession, ai_advisors_enabled, find_countries
            from GameLogic.LLMClient import LLMConfig
            # Explicit offline factory is the default: no hidden configured calls.
            config = client.config if client is not None else LLMConfig(offline=True)
            conversation = prepared["conversation"]
            # This ID belongs only to the request's cloned world. A late reply
            # can neither assign an ID to the campaign nor write legacy memory.
            w.advisorGameId = conversation["generation"]
            session = AdvisorSession(w.human, args.get("index", 0), config=config,
                                     client=client, memory=conversation["memory"])
            session.history = copy.deepcopy(conversation["history"])
            previous_history_size = len(session.history)
            question = args["question"]
            if prepared["selection"] is not None and not find_countries(w, question):
                question += ("\nВыбранная страна: %s." % country_name(prepared["selection"]) if language == "ru"
                             else "\nSelected country: %s." % Local.countryName(prepared["selection"]))
            active_headline = w.crisis.whichHead if prepared["panel"]["locked"] else None
            if prepared.get("human_crisis") is not None:
                context = prepared["human_crisis"]["prompt"]
                question += "\nAuthoritative human crisis context: " + json.dumps({
                    key: context.get(key) for key in ("phase", "decider", "actor", "challenged", "victim", "level", "summitBy", "choices")}, ensure_ascii=False)
            answer = session.ask(w, question, headline=active_headline, language=language)
            used_model = not session.offline and not bool(session.last_error)
            if not used_model and availability == "ready":
                availability = ("disabled" if not ai_advisors_enabled(session.chat_config) else
                                "offline" if session.chat_config.offline else
                                "unconfigured" if not session.chat_config.usable else "failed")
            if not used_model and language == "ru" and active_headline is not None:
                if prepared.get("human_crisis") is not None:
                    answer += "\n\n" + prepared["human_crisis"]["advice_ru"][args.get("index", 0)]
                else:
                    verdicts = [CrisisHandler.getAdvisorOpinion(w, active_headline, index + 1,
                        reversed=active_headline.actor.id == w.human) for index in range(4)]
                    answer += "\n\n" + crisis_advice_ru(w, prepared["panel"], verdicts)[args.get("index", 0)]
            history = session.history
            if len(history) < previous_history_size + 2:
                history = history + [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
            elif history[-1].get("role") == "assistant":
                history[-1]["content"] = answer
            conversation["history"] = history
            mentioned = find_countries(w, args["question"])
            result = {"text": answer, "used_model": used_model, "status_code": availability,
                      "status": model_status(availability, language), "year": w.year, "side": w.human,
                      "country_id": mentioned[0] if len(mentioned) == 1 else None}
            return {"type": "advisor_reply", "index": args.get("index", 0), "result": result,
                    "_conversation": conversation}
        from GameLogic.CrisisDialogue import snapshot, generate
        if client is None:
            return {"type": "crisis_dialogue", "result": self._fallback_dialogue(prepared, language, status_code=availability)}
        try:
            event = prepared["panel"].get("dialogue") or {"speaker": 1 - w.human, "outcome": "current_step"}
            request = snapshot(w, w.crisis.whichHead, event["speaker"], event["outcome"],
                               headline_text=event.get("headline_text"), language=args.get("language", "en"))
            if prepared.get("human_crisis") is not None:
                from dataclasses import replace
                context = prepared["human_crisis"]
                facts = json.loads(request.facts)
                facts["human_crisis"] = {key: context["prompt"].get(key) for key in
                    ("phase", "decider", "actor", "challenged", "victim", "level", "summitBy", "choices")}
                facts["player_prestige_at_risk"] = context["prestige_at_risk"]
                request = replace(request, facts=json.dumps(facts, ensure_ascii=False))
            reply = generate(request, client)
            return {"type": "crisis_dialogue", "result": {"reaction": reply.reaction,
                    "advice": list(reply.advice), "used_model": reply.used_model, "status": reply.status,
                    "status_code": "ready"}}
        except Exception:
            return {"type": "crisis_dialogue", "result": self._fallback_dialogue(prepared, language, status_code="failed")}

    def _advice_client(self, prepared):
        if prepared["offline_training"]:
            return None, "training"
        if self.model_client_factory is None:
            return None, "unconfigured"
        try:
            resolve = getattr(self.model_client_factory, "resolve_advisor", None)
            if resolve is not None:
                return resolve()
            client = self.model_client_factory()
            if client is None:
                return None, "unconfigured"
            if client.config.offline:
                return None, "offline"
            if not client.config.usable:
                return None, "unconfigured"
            return client, "ready"
        except Exception:
            return None, "failed"

    def _fallback_dialogue(self, prepared, language, failed=False, status_code=None):
        w, panel = prepared["world"], prepared["panel"]
        status_code = status_code or ("failed" if failed else "unconfigured")
        if prepared.get("human_crisis") is not None:
            context = prepared["human_crisis"]
            phase = context["prompt"].get("phase", "challenge")
            english = {"challenge": "The challenged player decides whether to contest this policy.",
                       "escalate": "The deciding player can stand firm, back down or propose a summit if available.",
                       "summit": "The deciding player responds to the summit proposal."}
            russian = {"challenge": "Игрок, которому брошен вызов, решает, оспаривать ли эту политику.",
                       "escalate": "Решающая сторона может стоять на своём, уступить или предложить саммит, если он доступен.",
                       "summit": "Решающая сторона отвечает на предложение саммита."}
            return {"reaction": (russian if language == "ru" else english).get(phase, ""),
                    "advice": list(context["advice_ru"] if language == "ru" else context["advice"]),
                    "used_model": False, "status": model_status(status_code, language), "status_code": status_code}
        headline = w.crisis.whichHead
        advice = [CrisisHandler.getAdvisorOpinion(w, headline, index + 1,
                   reversed=headline.actor.id == w.human) for index in range(4)] if headline is not None else []
        if language == "en":
            return {"reaction": panel["fields"]["reactionLine"]["text"], "advice": advice,
                    "used_model": False, "status": model_status(status_code, language), "status_code": status_code}
        reaction = reaction_ru(w, panel.get("dialogue"))
        return {"reaction": reaction, "advice": crisis_advice_ru(w, panel, advice), "used_model": False,
                "status": model_status(status_code, language), "status_code": status_code}
