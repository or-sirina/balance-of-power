"""Provider role factory resolution never performs network I/O."""
import _isolate  # noqa: F401
import os
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from EngineBridge.models import ConfiguredModels
from GameLogic.LLMClient import LLMConfig
from GameLogic.AdvisorChat import set_ai_advisors


class FactoryTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(set_ai_advisors, True)
        with patch.dict(os.environ, {}, clear=True), patch.object(LLMConfig, '_load_stored', return_value={}):
            self.config = LLMConfig(provider='openai', api_key='fake-key', model='opponent',
                                    chat_model='advisor', gamemaster_model='director', timeout=90,
                                    fallback_models=['typesafe/jev-1.13', 'chat-fallback'])
        self.factory = ConfiguredModels()
        self.factory._config = self.config

    def test_director_is_independent_copied_and_shares_budget(self):
        set_ai_advisors(False)
        client, status = self.factory.resolve_gamemaster()
        self.assertEqual(status, 'ready')
        self.assertIsNot(client.config, self.config)
        self.assertEqual(client.config.model, 'director')
        self.assertEqual(client.config.backend, 'chat')
        self.assertEqual(client.config.provider, 'openai')
        self.assertEqual(client.config.timeout, 30)
        self.assertEqual(client.config.fallback_models, ['chat-fallback'])
        self.assertIs(client.config.game_budget, self.config.game_budget)
        client._bump('requests')
        advisor_config = self.config.adversarial_config()
        self.assertEqual(advisor_config.active_budget().used, 1)
        self.assertEqual(self.config.model, 'opponent')
        self.assertEqual(self.config.timeout, 90)

    def test_offline_missing_key_and_decisions_fail_soft(self):
        self.config.offline = True
        self.assertEqual(self.factory.resolve_gamemaster(), (None, 'offline'))
        self.config.offline = False
        self.config.api_key = ''
        self.assertEqual(self.factory.resolve_gamemaster(), (None, 'unconfigured'))
        self.config.api_key = 'fake-key'
        self.config.gamemaster_model = 'typesafe/jev-1.13'
        self.assertEqual(self.factory.resolve_gamemaster(), (None, 'unconfigured'))

    def test_runtime_tuple_remains_compatible_and_reset_clears_budget(self):
        first, _ = self.factory.resolve_gamemaster()
        captured = self.factory.capture_runtime()
        self.assertEqual(len(captured), 2)
        self.factory.reset_game()
        self.factory.restore_runtime(captured)
        second, _ = self.factory.resolve_gamemaster()
        self.assertIs(second.config.game_budget, first.config.game_budget)
        self.factory.reset_game()
        with patch('GameLogic.LLMClient.LLMConfig', return_value=LLMConfig(api_key='fake')):
            third = self.factory._configuration()
        self.assertIsNot(third.game_budget, first.config.game_budget)

    def test_legacy_configuration_without_active_budget_method(self):
        self.factory._config = SimpleNamespace()
        config = self.factory._configuration()
        budget = config.game_budget
        self.assertTrue(budget.alive)
        self.assertIs(self.factory._configuration().game_budget, budget)

    def test_test_isolation_scrubs_every_named_key(self):
        names = ('OPENROUTER_API_KEY','OPENAI_API_KEY','DEEPSEEK_API_KEY',
                 'ANTHROPIC_API_KEY','DASHSCOPE_API_KEY','GEMINI_API_KEY','GOOGLE_API_KEY')
        env = _isolate.scrub(dict.fromkeys(names, 'fake'))
        for name in names:
            self.assertNotIn(name, env)

if __name__ == '__main__':
    unittest.main()
