"""Provider isolation and wire-format checks; no live provider calls."""
import _isolate
import json
import os
import sys
import unittest
import threading
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from GameLogic.LLMClient import LLMConfig, LLMClient, LLMError, SharedBudget
from GameLogic.LLMProviders import provider_catalog, infer_provider


class ProviderTests(unittest.TestCase):
    def config(self, **kwargs):
        with patch.dict(os.environ, {}, clear=True), patch.object(LLMConfig, '_load_stored', return_value={}):
            return LLMConfig(**kwargs)

    def request(self, provider, model='example'):
        client = LLMClient(self.config(provider=provider, model=model, api_key='fake-test-key'))
        client._send_reasoning = True
        req = client._build_request([{'role':'system','content':'Brief'}, {'role':'user','content':'Hi'}], {'type':'json_object'})
        return req, json.loads(req.data)

    def test_catalog_and_inference(self):
        self.assertEqual(len(provider_catalog()), 9)
        self.assertEqual(infer_provider('https://api.anthropic.com/v1'), 'anthropic')
        self.assertEqual(infer_provider('http://127.0.0.1:8000/v1'), 'local')

    def test_vendor_fields_stay_scoped(self):
        for provider in ('openai','gemini','custom','local'):
            req, body = self.request(provider)
            for field in ('reasoning','thinking','enable_thinking'):
                self.assertNotIn(field, body)
            self.assertNotIn('Http-referer', req.headers)
        self.assertEqual(self.request('deepseek')[1]['thinking'], {'type':'disabled'})
        self.assertFalse(self.request('qwen')[1]['enable_thinking'])
        self.assertFalse(self.request('openrouter')[1]['reasoning']['enabled'])

    def test_openai_reasoning_parameters(self):
        body = self.request('openai', 'gpt-5-mini')[1]
        self.assertIn('max_completion_tokens', body)
        self.assertNotIn('max_tokens', body)
        self.assertNotIn('temperature', body)
        self.assertIn('temperature', self.request('openai', 'gpt-4.1')[1])

    def test_anthropic_native(self):
        req, body = self.request('anthropic')
        self.assertTrue(req.full_url.endswith('/v1/messages'))
        self.assertIn({'type':'text','text':'Brief'}, body['system'])
        self.assertEqual(body['messages'], [{'role':'user','content':'Hi'}])
        self.assertNotIn('response_format', body)
        self.assertEqual(req.headers['Anthropic-version'], '2026-10-21')
        client = LLMClient(self.config(provider='anthropic'))
        self.assertEqual(client._extract_provider({'content':[{'type':'thinking','thinking':'hidden'}, {'type':'text','text':'answer'}]}), 'answer')
        with self.assertRaises(LLMError):
            client._extract_provider({'stop_reason':'max_tokens','content':[{'type':'text','text':'partial'}]})
        client._account({'usage': {'input_tokens':8,'output_tokens':3}})
        self.assertEqual(client.usage['total_tokens'], 11)

    def test_credentials_do_not_cross_providers(self):
        stored = {'base_url':'https://openrouter.ai/api/v1','api_key':'saved-or'}
        with patch.dict(os.environ, {'OPENROUTER_API_KEY':'fake-or', 'OPENAI_API_KEY':'fake-ai'}, clear=True), patch.object(LLMConfig, '_load_stored', return_value=stored):
            self.assertEqual(LLMConfig(provider='openai').api_key, 'fake-ai')
            self.assertEqual(LLMConfig(provider='anthropic').api_key, '')
            self.assertEqual(LLMConfig(base_url='https://custom.invalid/v1').api_key, '')

    def test_named_environment_keys_require_known_https_endpoint(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY':'fake-ai', 'DASHSCOPE_API_KEY':'fake-qwen'}, clear=True), patch.object(LLMConfig, '_load_stored', return_value={}):
            self.assertEqual(LLMConfig(provider='openai').api_key, 'fake-ai')
            self.assertEqual(LLMConfig(provider='openai', base_url='https://gateway.invalid/v1').api_key, '')
            self.assertEqual(LLMConfig(provider='openai', base_url='http://api.openai.com/v1').api_key, '')
            self.assertEqual(LLMConfig(provider='openai', base_url='https://api.deepseek.com').api_key, '')
            self.assertEqual(LLMConfig(provider='qwen', base_url='https://workspace.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1').api_key, 'fake-qwen')
            self.assertEqual(LLMConfig(provider='openai', base_url='https://gateway.invalid/v1', api_key='explicit-fake').api_key, 'explicit-fake')
            with patch.dict(os.environ, {'BOP_LLM_API_KEY':'explicit-env'}):
                self.assertEqual(LLMConfig(provider='openai', base_url='https://gateway.invalid/v1').api_key, 'explicit-env')

    def test_saved_profiles_keep_provider_keys_and_exclude_environment_key(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = os.path.join(directory, 'llm.json')
            with patch('GameLogic.LLMClient.Paths.user_file', return_value=path):
                first = LLMConfig(provider='openrouter', api_key='saved-or')
                first.save()
                second = LLMConfig(provider='anthropic', api_key='saved-cl')
                second.save()
                self.assertEqual(LLMConfig(provider='openrouter').api_key, 'saved-or')
                with patch.dict(os.environ, {'ANTHROPIC_API_KEY':'temporary-cl'}):
                    LLMConfig(provider='anthropic').save()
                with open(path) as handle:
                    saved = json.load(handle)
                self.assertNotIn('temporary-cl', json.dumps(saved))
                self.assertEqual(saved['provider_profiles']['anthropic']['api_key'], 'saved-cl')
                self.assertEqual(LLMConfig(provider='openrouter').api_key, 'saved-or')

    def test_native_transport_with_local_stub(self):
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                calls.append((self.path, json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'type':'message','stop_reason':'end_turn',
                    'content':[{'type':'text','text':'{"ok":true}'}],
                    'usage':{'input_tokens':4,'output_tokens':2}}).encode())
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            config = self.config(provider='anthropic', api_key='fake-test-key',
                                 base_url='http://127.0.0.1:%d/v1' % server.server_port)
            config.game_budget = SharedBudget()
            client = LLMClient(config)
            self.assertEqual(client.chat_json([{'role':'user','content':'Return JSON'}]), {'ok':True})
            self.assertEqual(calls[0][0], '/v1/messages')
            self.assertEqual(config.game_budget.used, 1)
            self.assertEqual(client.usage['total_tokens'], 6)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_profiles_and_shared_budget(self):
        stored = {'provider':'openrouter', 'provider_profiles':{'anthropic':{'base_url':'https://api.anthropic.com/v1','api_key':'fake-cl','model':'claude-example','chat_model':'claude-chat'}}}
        with patch.dict(os.environ, {}, clear=True), patch.object(LLMConfig, '_load_stored', return_value=stored):
            config = LLMConfig(provider='anthropic')
            self.assertEqual(config.api_key, 'fake-cl')
            self.assertEqual(config.gamemaster_model, 'claude-chat')
            self.assertEqual(LLMConfig(provider='anthropic', base_url='https://other.invalid/v1').api_key, '')
        config.game_budget = SharedBudget()
        clone = config.adversarial_config()
        self.assertIs(clone.game_budget, config.game_budget)
        self.assertEqual(clone.provider, 'anthropic')

if __name__ == '__main__':
    unittest.main()
