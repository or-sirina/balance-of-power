"""Headless UI regression: provider isolation, role models and GM backend history."""
import glob
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class AIRolesUITests(unittest.TestCase):
    def test_provider_switch_and_game_master_history(self):
        candidates = [os.environ.get('BOP_GODOT'), shutil.which('godot'), shutil.which('godot4')]
        candidates += sorted(glob.glob(os.path.expanduser('~/.local/share/bop-tools/godot-*/Godot*linux.x86_64')), reverse=True)
        binary = next((p for p in candidates if p and os.access(p, os.X_OK)), None)
        if not binary:
            self.skipTest('Godot is not installed')
        script = '''extends SceneTree
const Main = preload("res://scripts/main.gd")
const GM = preload("res://scripts/game_master_panel.gd")
class Host extends Control:
 const MUTED = Color("9bb2bf")
 const PAPER = Color("e7eadf")
 var state := {"year": 1982}
 var network_state: Dictionary = {}
 var busy := false
 func _label(value: String, _size: int, _color: Color, _wrap: bool) -> Label:
  var result := Label.new()
  result.text = value
  return result
 func _button(value: String, action: Callable) -> Button:
  var result := Button.new()
  result.text = value
  result.pressed.connect(action)
  return result
 func _open_ai_settings() -> void:
  pass
 func _command(_command_name: String, _args: Dictionary, done: Callable, _advisory: bool) -> void:
  done.call({"ok": true, "gamemaster": {"enabled": true, "status": "generated", "last_attempt_year": 1982, "history": [{"year": 1982, "headline": "Backend event", "text": "Backend detail"}]}})
 func _dialog(title_text: String, dimensions: Vector2i) -> VBoxContainer:
  var popup := Window.new()
  popup.title = title_text
  popup.size = dimensions
  add_child(popup)
  var column := VBoxContainer.new()
  popup.add_child(column)
  return column
var panel = preload("res://scripts/ai_settings.gd").new()
var pending: Callable
var args_seen: Dictionary
var data := {"generation": 7, "provider": "openai", "provider_catalog": [{"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1", "default_model": "one"}, {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com", "default_model": "two"}], "base_url": "https://api.openai.com/v1", "model": "one", "chat_model": "advisor", "gamemaster_model": "events", "key_configured": true}
func _initialize() -> void:
 run.call_deferred()
func request(command: String, args: Dictionary, done: Callable) -> void:
 if command == "settings_get" and args.has("provider"):
  args_seen = args
  pending = done
 elif command == "settings_get": done.call({"ok": true, "settings": data})
func run() -> void:
 var host := Host.new()
 root.add_child(host)
 panel.open(host, request, "en")
 assert(panel._values().gamemaster_model == "events")
 panel._controls.api_key.text = "first-provider-secret"
 panel._provider_selected(1)
 assert(panel._controls.api_key.text.is_empty())
 assert(args_seen.provider == "deepseek")
 var next := data.duplicate(true)
 next.provider = "deepseek"
 next.base_url = "https://api.deepseek.com"
 next.model = "two"
 next.key_configured = false
 pending.call({"ok": true, "settings": next})
 assert(panel._values().provider == "deepseek")
 assert(panel._values().expected_generation == 7)
 assert(not panel._values().clear_api_key)
 assert(panel._controls.api_key.text.is_empty())
 assert(panel._status.text.contains("Unsaved"))
 panel.close()
 var gm := GM.new()
 gm.open(host)
 assert(gm.history.text.contains("Backend event"))
 assert(gm.history.text.contains("Backend detail"))
 assert(gm.generate.disabled)
 assert(gm.enabled.button_pressed)
 gm._render({"enabled": true, "supported": false, "can_generate": false, "status": "ready"})
 assert(gm.enabled.disabled and gm.generate.disabled)
 gm._render({"enabled": true, "supported": true, "can_generate": false, "status": "ready"})
 assert(not gm.enabled.disabled and gm.generate.disabled)
 gm.L.language = "ru"
 gm._render({"enabled": true, "status": "fallback", "last_error": "English error", "last_error_ru": "Ошибка модели"})
 assert(gm.status.text.contains("Ошибка модели"))
 print("AI_ROLES_UI_OK")
 quit(0)
'''
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / 'probe.gd'
            probe.write_text(script, encoding='utf-8')
            result = subprocess.run([binary, '--headless', '--path', str(Path(__file__).resolve().parents[1] / 'godot'), '--script', str(probe), '--quit-after', '120'], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('SCRIPT ERROR', result.stderr)
        self.assertIn('AI_ROLES_UI_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
