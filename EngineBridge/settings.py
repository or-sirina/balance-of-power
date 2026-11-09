"""Secret-free settings views and explicit, isolated connection probes.

No constructor or read operation contacts a model. Call prepare_test under the
command boundary, then run_test outside the game lock. Config objects in a
PreparedTest are private snapshots and never carry the game's shared budget.
"""

import copy
import json
import math
import os
import tempfile
import threading
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

import Paths
from constants import DEFAULT_OPTS
from GameLogic.AdvisorChat import chat_config, set_ai_advisors
from GameLogic.JevClient import JevClient
from GameLogic.LLMClient import (Deadline, DEFAULT_BASE_URL, DEFAULT_CHAT_MODEL,
                                 DEFAULT_MODEL, LLMClient, LLMConfig, LLMError, MOCK_MODEL,
                                 failure_kind, is_decision_model)


MESSAGES = {
    "invalid_settings": ("Check the AI settings fields.", "Проверьте поля настроек ИИ."),
    "settings_changed": ("Settings changed. Reload the form and test again.", "Настройки изменились. Обновите форму и повторите проверку."),
    "save_error": ("AI settings could not be saved.", "Не удалось сохранить настройки ИИ."),
    "ready": ("The connection works.", "Подключение работает."),
    "offline": ("Built-in AI selected; no network request was made.", "Выбран встроенный ИИ; сетевых запросов не было."),
    "not_configured": ("Add an API key before testing the connection.", "Для проверки подключения укажите API-ключ."),
    "key": ("The provider rejected the API key.", "Провайдер отклонил API-ключ."),
    "certificate": ("TLS certificate verification failed. Check the trusted corporate CA.", "Не удалось проверить TLS-сертификат. Проверьте доверенный сертификат организации."),
    "filter": ("A proxy or web filter blocked the request.", "Запрос заблокирован прокси-сервером или сетевым фильтром."),
    "model": ("The model is unavailable at this endpoint.", "Модель недоступна по указанному адресу."),
    "busy": ("The provider is busy or rate-limited. Try later.", "Провайдер занят или ограничил частоту запросов. Повторите позже."),
    "unusable": ("The provider returned an unusable answer. Check model and backend.", "Провайдер вернул неподходящий ответ. Проверьте модель и тип API."),
    "unreachable": ("Connection failed. Check the endpoint, proxy and network.", "Нет подключения. Проверьте адрес, прокси и сеть."),
    "timeout": ("The connection test timed out.", "Истекло время проверки подключения."),
}


class SettingsError(ValueError):
    def __init__(self, code="invalid_settings", field_name=None):
        self.code = code
        self.field = field_name
        self.message, self.message_ru = MESSAGES[code]
        super().__init__(self.message)


@dataclass(frozen=True, repr=False)
class PreparedTest:
    generation: int
    steps: tuple = field(repr=False)
    skipped: str = ""


class SettingsService:
    """Existing llm.json/options.dat conventions, with no key in public results."""

    FIELDS = {"base_url", "model", "chat_model", "backend", "offline", "advisors_enabled",
              "disable_reasoning", "temperature", "max_tokens", "timeout", "max_requests",
              "fallback_models", "api_key", "clear_api_key", "expected_generation", "language"}
    PERSISTED = ("base_url", "model", "chat_model", "backend", "offline", "disable_reasoning",
                 "temperature", "max_tokens", "timeout", "max_requests", "fallback_models")

    def __init__(self, config_factory=LLMConfig, chat_factory=LLMClient, decisions_factory=JevClient):
        self.lock = threading.RLock()
        self.generation = 0
        self._stamp = None
        self.config_factory = config_factory
        self.chat_factory = chat_factory
        self.decisions_factory = decisions_factory

    def _paths(self):
        return Paths.user_file("llm.json"), Paths.user_file("options.dat")

    def _sync(self):
        stamp = []
        for path in self._paths():
            try:
                info = os.stat(path)
                stamp.append((info.st_mtime_ns, info.st_size))
            except FileNotFoundError:
                stamp.append(None)
        stamp = tuple(stamp)
        if self._stamp is not None and self._stamp != stamp:
            self.generation += 1
        self._stamp = stamp

    @staticmethod
    def _stored(path, default):
        try:
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return copy.deepcopy(default)

    def _options(self):
        options = self._stored(self._paths()[1], list(DEFAULT_OPTS))
        if not isinstance(options, list) or len(options) < len(DEFAULT_OPTS):
            options = list(DEFAULT_OPTS)
        defaults = list(DEFAULT_OPTS) + [False, True, True, False, True]
        options += defaults[len(options):]
        return options

    def _expected(self, args):
        expected = args.get("expected_generation")
        if expected is not None and (type(expected) is not int or expected != self.generation):
            raise SettingsError("settings_changed")

    @staticmethod
    def _public_text(value, config, saved_secret=""):
        # Even a malformed saved field must not echo the existing credential.
        text = str(value)
        for secret in (config.api_key, getattr(config, "_env_key", ""), saved_secret):
            if secret:
                text = text.replace(secret, "***")
        return text

    def _view(self, config, options):
        stored = self._stored(self._paths()[0], {})
        stored = stored if isinstance(stored, dict) else {}
        saved_secret = stored.get("api_key") if isinstance(stored.get("api_key"), str) else ""
        result = {name: copy.deepcopy(getattr(config, name)) for name in self.PERSISTED}
        for name in ("base_url", "model", "chat_model", "backend"):
            result[name] = self._public_text(result[name], config, saved_secret)
        try:
            url = urlsplit(result["base_url"])
            host = url.hostname or ""
            if ":" in host:
                host = "[" + host + "]"
            result["base_url"] = urlunsplit((url.scheme, host + (":" + str(url.port) if url.port else ""), url.path, "", ""))
        except ValueError:
            result["base_url"] = ""
        result["fallback_models"] = [self._public_text(item, config, saved_secret) for item in config.fallback_models]
        result["max_requests"] = int(config.max_requests or 0)
        for name, default in (("temperature", 0.7), ("timeout", 30.0)):
            if not math.isfinite(result[name]):
                result[name] = default
        result.update(generation=self.generation, key_configured=bool(config.api_key),
                      saved_key_configured=bool(stored.get("api_key")),
                      key_from_environment=bool(getattr(config, "_env_key", "")),
                      advisors_enabled=bool(options[11]))
        result["environment_overrides"] = [field_name for env_name, field_name in (
            ("BOP_LLM_BASE_URL", "base_url"), ("BOP_LLM_MODEL", "model"),
            ("BOP_LLM_CHAT_MODEL", "chat_model"), ("BOP_LLM_API_KEY", "api_key"),
            ("OPENROUTER_API_KEY", "api_key")) if os.environ.get(env_name)]
        return result

    def get(self):
        with self.lock:
            self._sync()
            return self._view(self.config_factory(), self._options())

    @staticmethod
    def _text(value, name, default=None, maximum=256):
        if not isinstance(value, str):
            raise SettingsError(field_name=name)
        value = value.strip() or default
        if not value or len(value) > maximum or any(ord(c) < 32 for c in value):
            raise SettingsError(field_name=name)
        return value

    def _collect(self, args):
        if not isinstance(args, dict) or set(args) - self.FIELDS:
            raise SettingsError()
        self._expected(args)
        config = copy.copy(self.config_factory())
        config.game_budget = None
        enabled = bool(self._options()[11])
        for name in ("offline", "disable_reasoning", "advisors_enabled", "clear_api_key"):
            if name in args and type(args[name]) is not bool:
                raise SettingsError(field_name=name)
        if "language" in args and args["language"] not in ("en", "ru"):
            raise SettingsError(field_name="language")
        for name, default in (("base_url", DEFAULT_BASE_URL), ("model", DEFAULT_MODEL), ("chat_model", DEFAULT_CHAT_MODEL)):
            value = args.get(name, getattr(config, name))
            setattr(config, name, self._text(value, name, default, 2048 if name == "base_url" else 256))
        config.base_url = config.base_url.rstrip("/")
        try:
            url = urlsplit(config.base_url)
            valid_url = (url.scheme in ("http", "https") and url.hostname and not url.username
                         and not url.password and not url.query and not url.fragment
                         and not any(c.isspace() for c in config.base_url))
            _ = url.port
        except ValueError:
            valid_url = False
        if not valid_url:
            raise SettingsError(field_name="base_url")
        backend = args.get("backend", config.backend)
        if backend not in ("auto", "chat", "decisions"):
            raise SettingsError(field_name="backend")
        config.backend = backend
        if is_decision_model(config.chat_model):
            raise SettingsError(field_name="chat_model")
        for name, low, high, integer in (("temperature", 0, 2, False), ("max_tokens", 128, 8192, True),
                                          ("timeout", 5, 300, False), ("max_requests", 0, 10000, True)):
            value = args.get(name, getattr(config, name) or 0)
            if (isinstance(value, bool) or not isinstance(value, (int, float)) or
                    not math.isfinite(value) or (integer and type(value) is not int) or not low <= value <= high):
                raise SettingsError(field_name=name)
            setattr(config, name, int(value) if integer else float(value))
        config.max_requests = config.max_requests or None
        fallbacks = args.get("fallback_models", config.fallback_models)
        if not isinstance(fallbacks, list) or len(fallbacks) > 8:
            raise SettingsError(field_name="fallback_models")
        config.fallback_models = list(dict.fromkeys(self._text(x, "fallback_models") for x in fallbacks if x != config.model))
        for name in ("offline", "disable_reasoning"):
            setattr(config, name, args.get(name, getattr(config, name)))
        config.offline = bool(config.offline or config.model == MOCK_MODEL)
        enabled = args.get("advisors_enabled", enabled)
        key = args.get("api_key", "")
        if not isinstance(key, str) or len(key) > 4096:
            raise SettingsError(field_name="api_key")
        key = key.strip()
        if args.get("clear_api_key", False) and key:
            raise SettingsError(field_name="api_key")
        if key:
            if any(ord(c) > 255 or ord(c) < 33 for c in key):
                raise SettingsError(field_name="api_key")
            config.api_key = key
        elif args.get("clear_api_key", False):
            config.api_key = config._env_key
        return config, enabled

    @staticmethod
    def _atomic(path, data):
        fd, temporary = tempfile.mkstemp(prefix=".ai-settings-", dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def apply(self, args):
        with self.lock:
            self._sync()
            config, enabled = self._collect(args)
            llm_path, options_path = self._paths()
            old = self._stored(llm_path, {})
            old = old if isinstance(old, dict) else {}
            key = config.api_key
            if args.get("clear_api_key", False):
                key = ""
            elif config._env_key and key == config._env_key:
                key = old.get("api_key") or ""
            payload = {name: copy.deepcopy(getattr(config, name)) for name in self.PERSISTED}
            payload.update(api_key=key, max_requests=config.max_requests or 0)
            options = self._options()
            options[11] = enabled
            paths = (llm_path, options_path)
            backups = []
            for path in paths:
                try:
                    with open(path, "rb") as handle:
                        backups.append(handle.read())
                except FileNotFoundError:
                    backups.append(None)
            written = []
            try:
                for path, value in zip(paths, (payload, options)):
                    self._atomic(path, json.dumps(value, ensure_ascii=False, indent=1).encode("utf-8"))
                    written.append(path)
            except OSError:
                for path, backup in zip(paths, backups):
                    if path in written:
                        if backup is None:
                            os.unlink(path)
                        else:
                            self._atomic(path, backup)
                raise SettingsError("save_error") from None
            self._stamp = None
            self.generation += 1
            self._sync()
            set_ai_advisors(enabled)
            return self._view(self.config_factory(), options)

    def prepare_test(self, args):
        with self.lock:
            self._sync()
            config, enabled = self._collect(args)
            if config.offline:
                return PreparedTest(self.generation, (), "offline")
            if not config.api_key:
                return PreparedTest(self.generation, (), "not_configured")
            steps = [("opponent", config.resolved_backend(), config)]
            advisors = chat_config(config)
            if enabled and advisors is not config:
                steps.append(("advisors", "chat", advisors))
            frozen = []
            for role, backend, target in steps:
                target = copy.copy(target)
                target.game_budget = None
                target.max_requests = None
                target.max_tokens = 128
                target.temperature = 0.0
                target.disable_reasoning = True
                target.fallback_models = []
                frozen.append((role, backend, target))
            return PreparedTest(self.generation, tuple(frozen))

    @staticmethod
    def _report(code, **fields):
        message, message_ru = MESSAGES[code]
        return dict(fields, code=code, message=message, message_ru=message_ru)

    def run_test(self, prepared):
        reports = []
        self._check_test_current(prepared)
        if prepared.skipped:
            reports.append(self._report(prepared.skipped, ok=prepared.skipped == "offline", skipped=True))
        for role, backend, config in prepared.steps:
            self._check_test_current(prepared)
            # A connection probe has its own short allowance and fresh clients;
            # it cannot consume a live game's call count or retry other models.
            timeout = min(float(config.timeout), 30.0)
            deadline = Deadline(timeout * 1.5)
            try:
                if backend == "decisions":
                    answer = self.decisions_factory(config).decide({"purpose": "connection test"},
                        {"ready": {"type": "noul", "instructions": "Is this a connection test? Answer yes."}},
                        timeout=timeout, deadline=deadline)
                    if not isinstance(answer, dict) or "ready" not in answer:
                        raise LLMError("the decision model did not answer the connection question")
                else:
                    answer = self.chat_factory(config).chat([{"role": "user", "content": "Reply with the single word: ready"}],
                                                   timeout=timeout, deadline=deadline)
                    if not isinstance(answer, str) or not answer.strip():
                        raise LLMError("the model returned an empty answer")
                reports.append(self._report("ready", role=role, backend=backend, ok=True))
            except Exception as exc:
                code = "timeout" if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower() else failure_kind(exc)
                if code not in MESSAGES:
                    code = "unusable"
                # Provider bodies and exception strings never enter the result.
                reports.append(self._report(code, role=role, backend=backend, ok=False))
        self._check_test_current(prepared)
        return {"generation": prepared.generation, "ok": all(item["ok"] for item in reports),
                "reports": reports}

    def _check_test_current(self, prepared):
        with self.lock:
            self._sync()
            if prepared.generation != self.generation:
                raise SettingsError("settings_changed")

    def test(self, args):
        return self.run_test(self.prepare_test(args))
