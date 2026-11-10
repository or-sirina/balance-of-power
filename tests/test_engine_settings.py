#!/usr/bin/env python3
"""Settings are secret-free, explicit, isolated from games, and stale-safe."""

import _isolate  # noqa: F401 -- never read developer settings or use real keys

import json
import glob
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import Paths
from EngineBridge.settings import SettingsError, SettingsService
from GameLogic.AdvisorChat import ai_advisors_enabled, set_ai_advisors
from GameLogic.LLMClient import LLMConfig, LLMError


class LocalAPI:
    def __init__(self):
        self.calls = []
        self.started = threading.Event()
        self.release = None
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.calls.append((self.path, payload))
                outer.started.set()
                if outer.release:
                    outer.release.wait(3)
                body = json.dumps({"choices": [{"message": {"content": "ready"}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:%d/v1" % self.server.server_port

    def close(self):
        if self.release:
            self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"BOP_USER_DIR": self.directory.name})
        self.environment.start()
        self.service = SettingsService()
        self.apis = []

    def tearDown(self):
        for api in self.apis:
            api.close()
        self.environment.stop()
        self.directory.cleanup()
        set_ai_advisors(True)

    def stored(self):
        with open(Paths.user_file("llm.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def seed(self, **kwargs):
        config = LLMConfig(api_key="fake-saved-secret", model="test/chat", **kwargs)
        config.save()
        return config

    def local(self):
        api = LocalAPI()
        self.apis.append(api)
        return api

    def test_read_and_apply_never_contact_models_or_return_a_key(self):
        def forbidden(_config):
            self.fail("settings read/apply instantiated a model client")
        self.service = SettingsService(chat_factory=forbidden, decisions_factory=forbidden)
        first = self.service.get()
        self.assertFalse(first["key_configured"])
        self.assertFalse(os.path.exists(Paths.user_file("llm.json")))
        self.assertFalse(os.path.exists(Paths.user_file("options.dat")))
        result = self.service.apply({"api_key": "fake-new-secret", "offline": True})
        self.assertTrue(result["key_configured"])
        self.assertNotIn("api_key", result)
        self.assertNotIn("fake-new-secret", json.dumps(result))
        self.assertEqual(self.stored()["api_key"], "fake-new-secret")
        if os.name == "posix":
            # Windows stat mode bits do not describe access controlled by ACLs.
            self.assertEqual(stat.S_IMODE(os.stat(Paths.user_file("llm.json")).st_mode), 0o600)

    def test_blank_preserves_key_and_explicit_clear_removes_it(self):
        self.seed()
        current = self.service.get()
        result = self.service.apply({"api_key": "", "temperature": 0.4,
                                     "expected_generation": current["generation"]})
        self.assertEqual(self.stored()["api_key"], "fake-saved-secret")
        self.assertGreater(result["generation"], current["generation"])
        result = self.service.apply({"clear_api_key": True, "expected_generation": result["generation"]})
        self.assertEqual(self.stored()["api_key"], "")
        self.assertFalse(result["key_configured"])

    def test_environment_key_is_not_saved_and_clear_does_not_disable_environment(self):
        self.seed()
        with patch.dict(os.environ, {"BOP_LLM_API_KEY": "fake-environment-secret"}):
            result = self.service.apply({"api_key": ""})
            self.assertEqual(self.stored()["api_key"], "fake-saved-secret")
            result = self.service.apply({"clear_api_key": True})
            self.assertEqual(self.stored()["api_key"], "")
            self.assertTrue(result["key_configured"])
            self.assertTrue(result["key_from_environment"])
            self.assertFalse(result["saved_key_configured"])
            self.assertNotIn("fake-environment-secret", json.dumps(result))

    def test_existing_secrets_are_hidden_even_in_malformed_saved_nonsecret_fields(self):
        self.seed(base_url="https://user:fake-saved-secret@example.test/v1?api_key=fake-saved-secret")
        with patch.dict(os.environ, {"BOP_LLM_API_KEY": "fake-other-environment-secret"}):
            view = self.service.get()
        rendered = json.dumps(view)
        self.assertNotIn("fake-saved-secret", rendered)
        self.assertNotIn("fake-other-environment-secret", rendered)
        self.assertEqual(view["base_url"], "https://example.test/v1")

    def test_public_view_is_valid_json_even_when_saved_floats_are_nonfinite(self):
        self.seed(temperature=float("nan"), timeout=float("inf"))
        json.dumps(self.service.get(), allow_nan=False)

    def test_apply_preserves_other_preferences_and_saves_advisor_toggle(self):
        options = [False, True, False, "english.json", 2, 1, 0, True, False, True, True, True, False, 18]
        with open(Paths.user_file("options.dat"), "w", encoding="utf-8") as handle:
            json.dump(options, handle)
        self.service.apply({"advisors_enabled": False})
        with open(Paths.user_file("options.dat"), encoding="utf-8") as handle:
            saved = json.load(handle)
        self.assertEqual(saved[:11], options[:11])
        self.assertEqual(saved[12:], options[12:])
        self.assertFalse(saved[11])
        self.assertFalse(ai_advisors_enabled())

    def test_invalid_fields_never_write_or_echo_values(self):
        self.seed()
        before = Path(Paths.user_file("llm.json")).read_bytes()
        invalid = ({"base_url": "file:///tmp/key"}, {"base_url": "https://user:secret@example.org/v1"},
                   {"base_url": "https://example.org/v1?token=secret"}, {"max_tokens": True},
                   {"temperature": float("nan")}, {"timeout": 1000}, {"max_requests": -1},
                   {"backend": "bogus"}, {"chat_model": "typesafe/jev-1.13"},
                   {"clear_api_key": True, "api_key": "fake-new-secret"},
                   {"api_key": "a key with spaces"}, {"unknown": "fake-secret"})
        for args in invalid:
            with self.subTest(fields=list(args)):
                with self.assertRaises(SettingsError) as raised:
                    self.service.apply(args)
                self.assertNotIn("fake-new-secret", str(raised.exception))
                self.assertEqual(Path(Paths.user_file("llm.json")).read_bytes(), before)
                self.assertFalse(os.path.exists(Paths.user_file("options.dat")))

    def test_atomic_apply_rolls_back_config_if_preferences_write_fails(self):
        self.seed()
        original = Path(Paths.user_file("llm.json")).read_bytes()
        atomic = self.service._atomic
        def fail_preferences(path, data):
            if path.endswith("options.dat"):
                raise OSError("fake I/O failure")
            return atomic(path, data)
        with patch.object(self.service, "_atomic", side_effect=fail_preferences):
            with self.assertRaises(SettingsError):
                self.service.apply({"api_key": "fake-replacement"})
        self.assertEqual(Path(Paths.user_file("llm.json")).read_bytes(), original)

    def test_explicit_test_uses_unsaved_form_and_never_game_budget(self):
        api = self.local()
        source = self.seed()
        source.game_budget = object()
        source.max_requests = 1
        original_budget = source.game_budget
        self.service = SettingsService(config_factory=lambda: source)
        before = Path(Paths.user_file("llm.json")).read_bytes()
        result = self.service.test({"base_url": api.url, "model": "test/unsaved", "api_key": "fake-probe-only"})
        self.assertTrue(result["ok"])
        self.assertEqual(len(api.calls), 1)
        self.assertEqual(api.calls[0][0], "/v1/chat/completions")
        self.assertEqual(api.calls[0][1]["model"], "test/unsaved")
        self.assertEqual(api.calls[0][1]["max_tokens"], 128)
        self.assertIs(source.game_budget, original_budget)
        self.assertEqual(source.max_requests, 1)
        self.assertEqual(source.model, "test/chat")
        self.assertEqual(Path(Paths.user_file("llm.json")).read_bytes(), before)
        self.assertNotIn("fake-probe-only", json.dumps(result))

    def test_offline_and_missing_key_skip_all_network_calls(self):
        def forbidden(_config):
            self.fail("a skipped test instantiated a network client")
        self.service = SettingsService(chat_factory=forbidden, decisions_factory=forbidden)
        no_key = self.service.test({})
        self.assertFalse(no_key["ok"])
        self.assertEqual(no_key["reports"][0]["code"], "not_configured")
        offline = self.service.test({"offline": True, "api_key": "fake-key"})
        self.assertTrue(offline["ok"])
        self.assertEqual(offline["reports"][0]["code"], "offline")

    def test_decisions_and_advisor_models_probe_the_correct_backends(self):
        called = []
        class Decisions:
            def __init__(self, config):
                self.config = config
            def decide(self, *args, **kwargs):
                called.append(("decisions", self.config.model, self.config.game_budget))
                return {"ready": object()}
        class Chat:
            def __init__(self, config):
                self.config = config
            def chat(self, *args, **kwargs):
                called.append(("chat", self.config.model, self.config.game_budget))
                return "ready"
        self.service = SettingsService(chat_factory=Chat, decisions_factory=Decisions)
        result = self.service.test({"model": "typesafe/jev-1.13", "chat_model": "test/prose", "api_key": "fake-key"})
        self.assertTrue(result["ok"])
        self.assertEqual(called, [("decisions", "typesafe/jev-1.13", None), ("chat", "test/prose", None)])

    def test_provider_error_bodies_and_credentials_are_never_diagnostics(self):
        class LeakyProvider:
            def __init__(self, config):
                self.config = config
            def chat(self, *args, **kwargs):
                raise LLMError("the API key was rejected: " + self.config.api_key + " Bearer another-provider-secret")
        self.service = SettingsService(chat_factory=LeakyProvider)
        result = self.service.test({"api_key": "fake-private-value", "model": "test/chat"})
        rendered = json.dumps(result)
        self.assertFalse(result["ok"])
        self.assertNotIn("fake-private-value", rendered)
        self.assertNotIn("another-provider-secret", rendered)
        self.assertEqual(result["reports"][0]["code"], "key")
        self.assertTrue(result["reports"][0]["message_ru"])

    def test_test_response_is_discarded_when_apply_changes_settings_mid_request(self):
        api = self.local()
        api.release = threading.Event()
        prepared = self.service.prepare_test({"base_url": api.url, "model": "test/chat", "api_key": "fake-key"})
        outcome = []
        def worker():
            try:
                outcome.append(self.service.run_test(prepared))
            except SettingsError as exc:
                outcome.append(exc.code)
        thread = threading.Thread(target=worker)
        thread.start()
        self.assertTrue(api.started.wait(2))
        self.service.apply({"temperature": 0.2})
        api.release.set()
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome, ["settings_changed"])

    def test_already_stale_test_and_apply_forms_are_rejected_before_network(self):
        prepared = self.service.prepare_test({"api_key": "fake-key", "model": "test/chat"})
        old_generation = prepared.generation
        self.service.apply({"offline": True})
        with self.assertRaises(SettingsError):
            self.service.apply({"expected_generation": old_generation})
        with self.assertRaises(SettingsError):
            self.service.run_test(prepared)

    def test_external_settings_change_also_invalidates_prepared_probe(self):
        self.seed()
        prepared = self.service.prepare_test({})
        config = LLMConfig()
        config.temperature = 0.123
        config.save()
        with self.assertRaises(SettingsError) as raised:
            self.service.run_test(prepared)
        self.assertEqual(raised.exception.code, "settings_changed")

    def test_provider_preview_is_read_only_and_keys_are_scoped(self):
        self.service.apply({'provider': 'openrouter', 'model': 'router/model', 'api_key': 'router-private'})
        before = Path(Paths.user_file('llm.json')).read_bytes()
        generation = self.service.generation
        preview = self.service.get({'provider': 'openai'})
        self.assertEqual(preview['provider'], 'openai')
        self.assertEqual(preview['base_url'], 'https://api.openai.com/v1')
        self.assertFalse(preview['key_configured'])
        self.assertFalse(preview['saved_key_configured'])
        self.assertEqual(preview['generation'], generation)
        self.assertEqual(Path(Paths.user_file('llm.json')).read_bytes(), before)
        result = self.service.apply({'provider': 'openai', 'api_key': 'openai-private',
                                     'gamemaster_model': 'gm/test'})
        self.assertEqual(result['gamemaster_model'], 'gm/test')
        result = self.service.apply({'provider': 'openrouter'})
        self.assertEqual(result['model'], 'router/model')
        saved = self.stored()
        self.assertEqual(saved['api_key'], 'router-private')
        self.assertEqual(saved['provider_profiles']['openai']['api_key'], 'openai-private')
        self.assertNotIn('router-private', json.dumps(result))
        self.assertNotIn('openai-private', json.dumps(result))

    def test_endpoint_change_does_not_send_or_persist_previous_key(self):
        self.seed()
        prepared = self.service.prepare_test({'base_url': 'https://another.test/v1'})
        self.assertEqual(prepared.skipped, 'not_configured')
        result = self.service.apply({'base_url': 'https://another.test/v1'})
        self.assertFalse(result['key_configured'])
        self.assertEqual(self.stored()['api_key'], '')

    def test_provider_environment_key_is_selected_and_never_saved(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'openai-environment-private',
                                     'OPENROUTER_API_KEY': 'router-environment-private'}):
            preview = self.service.get({'provider': 'openai'})
            self.assertTrue(preview['key_from_environment'])
            self.assertIn('api_key', preview['environment_overrides'])
            result = self.service.apply({'provider': 'openai'})
            self.assertEqual(self.stored()['api_key'], '')
            self.assertNotIn('openai-environment-private', json.dumps(result))
            self.assertNotIn('router-environment-private', json.dumps(result))

    def test_malformed_profile_fields_cannot_echo_another_profile_key(self):
        self.service.apply({'provider': 'openrouter', 'api_key': 'router-private'})
        self.service.apply({'provider': 'openai', 'api_key': 'openai-private'})
        saved = self.stored()
        saved['provider_profiles']['openai']['model'] = 'router-private'
        saved['provider_profiles']['openai']['gamemaster_model'] = 'openai-private'
        Path(Paths.user_file('llm.json')).write_text(json.dumps(saved), encoding='utf-8')
        rendered = json.dumps(self.service.get({'provider': 'openai'}))
        self.assertNotIn('router-private', rendered)
        self.assertNotIn('openai-private', rendered)

    def test_explicit_gamemaster_probe_uses_own_model(self):
        called = []
        class Chat:
            def __init__(self, config): self.config = config
            def chat(self, *args, **kwargs):
                called.append(self.config.model)
                return 'ready'
        service = SettingsService(chat_factory=Chat)
        result = service.test({'provider': 'openai', 'model': 'opponent/test',
                               'chat_model': 'advisor/test', 'gamemaster_model': 'gm/test',
                               'api_key': 'fake-key'})
        self.assertTrue(result['ok'])
        self.assertEqual(called, ['opponent/test', 'advisor/test', 'gm/test'])
        self.assertEqual(result['reports'][-1]['role'], 'gamemaster')

    def test_godot_dialog_secure_key_and_stale_callbacks(self):
        candidates = [os.environ.get("BOP_GODOT"), shutil.which("godot"), shutil.which("godot4")]
        candidates += sorted(glob.glob(os.path.expanduser("~/.local/share/bop-tools/godot-*/Godot*linux.x86_64")), reverse=True)
        binary = next((path for path in candidates
                       if path and os.path.isfile(path) and os.access(path, os.X_OK)), None)
        if binary is None:
            self.skipTest("Godot is not installed")
        probe = Path(self.directory.name) / "settings_probe.gd"
        probe.write_text('''extends SceneTree
class Host extends Control:
 var popup: Window
 func _dialog(title_text: String, dimensions: Vector2i) -> VBoxContainer:
  popup = Window.new()
  popup.title = title_text
  popup.size = dimensions
  add_child(popup)
  var column := VBoxContainer.new()
  popup.add_child(column)
  popup.popup_centered()
  return column
var panel = preload("res://scripts/ai_settings.gd").new()
var host: Host
var calls: Array = []
var pending: Callable
var data := {"generation": 0, "base_url": "https://example.test/v1", "model": "test/chat", "chat_model": "test/prose", "backend": "auto", "offline": false, "advisors_enabled": true, "disable_reasoning": true, "temperature": 0.7, "max_tokens": 1200, "timeout": 10, "max_requests": 16, "fallback_models": [], "key_configured": true, "environment_overrides": []}
func _initialize() -> void:
 host = Host.new()
 root.add_child(host)
 run.call_deferred()
func request(command: String, _args: Dictionary, done: Callable) -> void:
 calls.append(command)
 if command == "settings_get": done.call({"ok": true, "settings": data})
 elif command == "settings_test": pending = done
 elif command == "settings_apply":
  data.generation += 1
  done.call({"ok": true, "settings": data})
func run() -> void:
 panel.open(host, request, "ru")
 assert(calls == ["settings_get"])
 assert(panel._controls.api_key.secret and panel._controls.api_key.text.is_empty())
 panel._controls.api_key.text = "fake-entered-key"
 panel._test()
 panel._controls.model.text = "test/changed"
 pending.call({"ok": true, "test": {"reports": [{"message_ru": "old response"}]}})
 assert(panel._status.text.contains("форма изменилась"))
 panel._test()
 var old_reply := pending
 panel._apply()
 assert(panel._data.generation == 1 and panel._controls.api_key.text.is_empty())
 var saved_text: String = panel._status.text
 old_reply.call({"ok": true, "test": {"reports": [{"message_ru": "old response"}]}})
 assert(panel._status.text == saved_text)
 var key: LineEdit = panel._controls.api_key
 key.text = "fake-close-key"
 panel.close()
 assert(key.text.is_empty())
 old_reply.call({"ok": true})
 await process_frame
 print("SETTINGS_UI_OK")
 quit(0)
''', encoding="utf-8")
        env = dict(os.environ, XDG_DATA_HOME=self.directory.name)
        run = subprocess.run([binary, "--headless", "--path", str(Path(__file__).resolve().parents[1] / "godot"),
                              "--script", str(probe), "--quit-after", "120"],
                             env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertNotIn("SCRIPT ERROR", run.stderr)
        self.assertIn("SETTINGS_UI_OK", run.stdout)


if __name__ == "__main__":
    unittest.main()
