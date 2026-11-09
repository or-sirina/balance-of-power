#!/usr/bin/env python3
"""Focused Godot request-race regressions with captured callbacks/local HTTP.

No game launcher, model settings or model provider is used. Tests skip when a
Godot executable is unavailable; every subprocess has isolated user data.
"""

import _isolate  # noqa: F401

import glob
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ROOT = Path(__file__).resolve().parents[1]

HARNESS = '''extends SceneTree
const Main = preload("res://scripts/main.gd")
const Locale = preload("res://scripts/locale.gd")
class BaseHarness extends Main:
 func _ready() -> void: pass
 func _render_state() -> void: pass
 func _build_ui() -> void: pass
 func _update_guide() -> void: pass
 func _advance_guide(_command: String, _response: Dictionary) -> void: pass
 func _save_preferences() -> void: pass
class CapturedHarness extends BaseHarness:
 var captured: Array = []
 func _command(command: String, args: Dictionary = {}, after: Callable = Callable(), advisory: bool = false) -> void:
  captured.append({"command": command, "args": args, "after": after, "advisory": advisory})
func create_harness(captured: bool):
 var host = CapturedHarness.new() if captured else BaseHarness.new()
 root.add_child(host)
 host.status_label = Label.new()
 host.add_child(host.status_label)
 host.end_button = Button.new()
 host.add_child(host.end_button)
 host.crisis_box = VBoxContainer.new()
 host.add_child(host.crisis_box)
 host.crisis_actions = HBoxContainer.new()
 host.add_child(host.crisis_actions)
 host.revision = 7
 host.state = {"year": 1982, "side": 0, "level": 3, "scores": [0, 0], "opponent": "offline", "ended": false,
  "crisis": {"active": true, "level": 8, "speaker": 1, "outcome": "stood_firm", "headline": "A policy is contested.",
   "headline_ru": "Оспаривается политика.", "reaction": "Built-in response.", "reaction_ru": "Стандартная реплика.",
   "choices": ["tough", "loose"], "prestige_at_risk": "12"}}
 return host
func response(text: String, revision: int = 7) -> Dictionary:
 return {"ok": true, "revision": revision, "dialogue": {"reaction": text, "advice": [], "used_model": true, "status": "model"}}
func _initialize() -> void:
 root.gui_embed_subwindows = true
 Locale.language = "en"
 run.call_deferred()
'''


class LocalTransport:
    def __init__(self):
        self.calls = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.calls.append(request["command"])
                failed = request["command"] == "transport_error"
                body = json.dumps({"ok": not failed, "revision": 7,
                                   "state": {"side": 0, "year": 1982, "level": 3, "opponent": "model",
                                             "crisis": {"active": True}, "ended": False}}).encode()
                self.send_response(503 if failed else 200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:%d" % self.server.server_port

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)


class GodotRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        candidates = [os.environ.get("BOP_GODOT"), shutil.which("godot"), shutil.which("godot4")]
        candidates += sorted(glob.glob(os.path.expanduser("~/.local/share/bop-tools/godot-*/Godot*linux.x86_64")), reverse=True)
        cls.binary = next((path for path in candidates
                           if path and os.path.isfile(path) and os.access(path, os.X_OK)), None)
        if cls.binary is None:
            raise unittest.SkipTest("Godot is not installed")

    def run_godot(self, body):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "runtime_probe.gd"
            script.write_text(HARNESS + body, encoding="utf-8")
            env = dict(os.environ, XDG_DATA_HOME=directory)
            try:
                run = subprocess.run([self.binary, "--headless", "--path", str(ROOT / "godot"),
                                      "--script", str(script), "--quit-after", "360"],
                                     env=env, capture_output=True, text=True, timeout=15)
            except subprocess.TimeoutExpired as exc:
                output = (exc.stdout or b"") + (exc.stderr or b"")
                self.fail("Godot timed out:\n" + output.decode("utf-8", "replace"))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertNotIn("SCRIPT ERROR", run.stderr)
        self.assertIn("RUNTIME_REGRESSION_OK", run.stdout)

    def test_dialogue_generation_settings_language_and_new_crisis_callbacks(self):
        self.run_godot('''
func run() -> void:
 var host = create_harness(true)
 host._crisis_briefing()
 assert(host.dialogue_pending)
 assert(host._ready_status() == Locale.text("thinking"))
 var loading_seen := false
 var disabled_briefing_seen := false
 for child in host.crisis_box.get_children():
  if child is Label and child.text == Locale.text("thinking"): loading_seen = true
  if child is Button and child.text == Locale.text("briefing") and child.disabled: disabled_briefing_seen = true
 assert(loading_seen and disabled_briefing_seen)
 var old_reply: Callable = host.captured[0].after
 host._settings_request("settings_apply", {}, func(_result): pass)
 host.captured[1].after.call({"ok": true, "revision": 7})
 host._crisis_briefing()
 var current_reply: Callable = host.captured[2].after
 var generation: int = host.dialogue_generation
 var identity: String = host.dialogue_identity
 old_reply.call(response("OLD SETTINGS"))
 old_reply.call({"ok": false})
 assert(host.dialogue_generation == generation and host.dialogue_identity == identity)
 assert(host.dialogue_pending and host.dialogue_result.is_empty())
 current_reply.call(response("CURRENT SETTINGS"))
 assert(not host.dialogue_pending and host.dialogue_result.reaction == "CURRENT SETTINGS")
 old_reply.call(response("OLD SETTINGS AGAIN"))
 assert(host.dialogue_result.reaction == "CURRENT SETTINGS")
 # Language switches must invalidate callbacks even with the same game revision.
 host._change_language()
 host._crisis_briefing()
 var russian_reply: Callable = host.captured[-1].after
 current_reply.call(response("OLD ENGLISH"))
 assert(host.dialogue_pending and host.dialogue_result.is_empty())
 russian_reply.call(response("Текущий ответ"))
 assert(host.dialogue_result.reaction == "Текущий ответ")
 # Another rung must retain its pending state if the previous callback fails late.
 host.revision = 8
 host.state.crisis.level = 7
 host._crisis_briefing()
 var rung_reply: Callable = host.captured[-1].after
 russian_reply.call({"ok": false})
 assert(host.dialogue_pending and host.model_revision == 8)
 rung_reply.call(response("Новая ступень", 8))
 assert(not host.dialogue_pending and host.dialogue_result.reaction == "Новая ступень")
 host.queue_free()
 await process_frame
 print("RUNTIME_REGRESSION_OK")
 quit(0)
''')

    def test_real_http_settings_epoch_and_transport_error_affordances(self):
        server = LocalTransport()
        try:
            self.run_godot('''
func run() -> void:
 var host = create_harness(false)
 host.backend_url = %s
 host.token = "fake-runtime-transport-token"
 var old_done := {"finished": false}
 host._command("report", {}, func(result):
  assert(not result.get("ok", true))
  old_done.finished = true
 , true)
 host.settings_generation += 1
 host.state.opponent = "offline"
 host.status_label.text = "NEW SETTINGS STATUS"
 for _i in range(240):
  if old_done.finished: break
  await process_frame
 assert(old_done.finished)
 assert(host.state.opponent == "offline" and host.revision == 7)
 assert(host.status_label.text == "NEW SETTINGS STATUS")
 # Failed transport must not expose End Year during a crisis or after game over.
 for terminal in [false, true]:
  host.state.crisis.active = not terminal
  host.state.ended = terminal
  var failed := {"finished": false}
  host._command("transport_error", {}, func(result):
   assert(not result.get("ok", true))
   failed.finished = true
  , true)
  for _i in range(240):
   if failed.finished: break
   await process_frame
  assert(failed.finished and host.end_button.disabled)
 # A synchronous request() error must still release its dialog callback.
 host.backend_url = "ftp://127.0.0.1"
 var immediate := {"finished": false}
 host._command("settings_get", {}, func(result):
  assert(not result.get("ok", true))
  immediate.finished = true
 , true)
 assert(immediate.finished and host.end_button.disabled)
 host.queue_free()
 await process_frame
 print("RUNTIME_REGRESSION_OK")
 quit(0)
''' % json.dumps(server.url))
        finally:
            server.close()
        self.assertEqual(server.calls, ["report", "transport_error", "transport_error"])

    def test_advisor_panel_restores_campaign_and_rejects_old_voice_or_window_replies(self):
        self.run_godot('''
func prior_details(tag: String) -> Dictionary:
 return {"history": [{"role": "user", "content": tag + " question"}, {"role": "assistant", "content": tag + " answer"}],
  "statistics": {"resolved": 3, "hits": 2, "open": 1, "hit_rate": 2.0 / 3.0, "mean_confidence": 0.75, "brier": 0.2},
  "status": tag + " calibrated record", "status_ru": tag + " история прогнозов",
  "pending": [{"summary_en": tag + " pending forecast", "summary_ru": tag + " ожидающий прогноз"}],
  "recent": [{"summary_en": tag + " reviewed forecast", "summary_ru": tag + " проверенный прогноз"}]}
func select_voice(panel, index: int) -> void:
 panel.choice.select(index)
 panel.choice.item_selected.emit(index)
func run() -> void:
 var host = create_harness(true)
 var panel = preload("res://scripts/advisor_panel.gd").new()
 panel.open(host)
 assert(host.captured.size() == 1 and host.captured[0].command == "advisor_history")
 host.captured[0].after.call({"ok": true, "history": prior_details("CAMPAIGN")})
 assert(panel.tabs.get_tab_count() == 3)
 assert(panel.answer.text == "CAMPAIGN answer")
 assert(panel.transcript.text.contains("CAMPAIGN question"))
 assert(panel.last_details.statistics.resolved == 3 and panel.record.get_child_count() > 0)
 # Two delayed history requests must leave the currently selected voice intact.
 select_voice(panel, 1)
 var late_voice: Callable = host.captured[-1].after
 select_voice(panel, 2)
 host.captured[-1].after.call({"ok": true, "history": prior_details("CURRENT VOICE")})
 late_voice.call({"ok": true, "history": prior_details("OLD VOICE")})
 assert(panel.choice.selected == 2 and panel.answer.text == "CURRENT VOICE answer")
 assert(not panel.transcript.text.contains("OLD VOICE"))
 assert(panel.last_details.status == "CURRENT VOICE calibrated record")
 # An empty question must never dispatch a model request.
 var before: int = host.captured.size()
 panel.question.text = "  \\n\\t"
 panel.question.text_changed.emit()
 panel._ask()
 assert(panel.ask.disabled and host.captured.size() == before)
 # Failure releases controls and refreshes history even if the initial history
 # reply was invalidated by clicking Ask before that reply arrived.
 panel.open(host)
 var initial_history: Callable = host.captured[-1].after
 panel.question.text = "Explain the position."
 panel.question.text_changed.emit()
 panel._ask()
 var failed_ask: Callable = host.captured[-1].after
 assert(panel.ask.disabled and panel.choice.disabled and not panel.question.editable)
 failed_ask.call({"ok": false, "error": {"message": "fake transport failure"}})
 assert(not panel.ask.disabled and not panel.choice.disabled and panel.question.editable)
 assert(panel.answer.text == "fake transport failure")
 assert(host.captured[-1].command == "advisor_history")
 host.captured[-1].after.call({"ok": true, "history": prior_details("RECOVERED")})
 initial_history.call({"ok": true, "history": prior_details("SUPERSEDED INITIAL")})
 assert(panel.answer.text == "fake transport failure")
 assert(panel.transcript.text.contains("RECOVERED question"))
 assert(not panel.transcript.text.contains("SUPERSEDED INITIAL"))
 # Closing/reopening while Ask is pending creates a new view generation.
 panel._ask()
 var closed_ask: Callable = host.captured[-1].after
 host.popup.queue_free()
 panel.open(host)
 host.captured[-1].after.call({"ok": true, "history": prior_details("REOPENED")})
 closed_ask.call({"ok": true, "advice": {"text": "LATE CLOSED ANSWER", "status": "old"}})
 assert(panel.answer.text == "REOPENED answer" and not panel.choice.disabled)
 assert(panel.transcript.text.contains("REOPENED question"))
 # A history transport error is explicit in both secondary tabs, never an
 # endless loading message or a fabricated empty calibration score.
 select_voice(panel, 1)
 host.captured[-1].after.call({"ok": false, "error": {"message": "history transport failed"}})
 assert(panel.transcript.text == "history transport failed")
 var visible_error := false
 for child in panel.record.get_children():
  if child is Label and child.text == "history transport failed": visible_error = true
 assert(visible_error and not panel.choice.disabled and panel.question.editable)
 host.queue_free()
 await process_frame
 print("RUNTIME_REGRESSION_OK")
 quit(0)
''')


if __name__ == "__main__":
    unittest.main()
