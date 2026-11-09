"""Lazy adapters for the existing model settings; never log configuration."""

import json
import threading

import Paths


class ConfiguredModels:
    """Shared chat client and game budget, created only on explicit game use."""

    def __init__(self):
        self._lock = threading.RLock()
        self._config = None
        self._chat = None

    def _settings(self):
        from GameLogic.AdvisorChat import set_ai_advisors
        try:
            with open(Paths.user_file("options.dat"), encoding="utf-8") as handle:
                options = json.load(handle)
            enabled = bool(options[11]) if isinstance(options, list) and len(options) > 11 else True
        except (OSError, ValueError, TypeError):
            enabled = True
        set_ai_advisors(enabled)

    def _configuration(self):
        from GameLogic.LLMClient import LLMConfig
        if self._config is None:
            self._config = LLMConfig()
        return self._config

    def __call__(self):
        """Resolve advisors' text model, respecting the saved AI toggle."""
        return self.resolve_advisor()[0]

    def resolve_advisor(self):
        """Return a client and a secret-free explanation of its availability."""
        from GameLogic.AdvisorChat import ai_advisors_enabled, chat_config
        from GameLogic.LLMClient import LLMClient
        with self._lock:
            self._settings()
            config = self._configuration()
            if not ai_advisors_enabled(config):
                return None, "disabled"
            resolved = chat_config(config)
            if resolved.offline:
                return None, "offline"
            if not resolved.usable:
                return None, "unconfigured"
            if self._chat is None:
                self._chat = LLMClient(resolved)
            else:
                self._chat.config = resolved
            return self._chat, "ready"

    def opponent(self):
        """Instantiate the original decision/chat opponent without making calls."""
        from GameLogic.LLMOpponent import LLMOpponent
        with self._lock:
            return LLMOpponent(config=self._configuration())

    def reset_game(self):
        with self._lock:
            self._config = None
            self._chat = None

    def capture_runtime(self):
        """Opaque references used only for transactional command rollback."""
        with self._lock:
            return self._config, self._chat

    def restore_runtime(self, captured):
        with self._lock:
            self._config, self._chat = captured


def configured_client_factory():
    """Return a callable shared lazy factory with .opponent and .reset_game."""
    return ConfiguredModels()
