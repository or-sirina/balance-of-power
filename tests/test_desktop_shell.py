"""Exercise the real desktop menu and drawers without contacting model services."""
import _isolate  # noqa: F401
import unittest
import test_godot_runtime as runtime

SHELL = '''
class ShellHarness extends Main:
 var captured: Array = []
 func _ready() -> void: pass
 func _save_preferences() -> void: pass
 func _play_music() -> void: pass
 func _command(command: String, args: Dictionary = {}, after: Callable = Callable(), advisory: bool = false) -> void:
  captured.append({"command": command, "args": args, "after": after, "advisory": advisory})
func campaign() -> Dictionary:
 return {"year": 1982, "side": 0, "level": 3, "scores": [0, 0], "tension": 20, "opponent": "offline",
  "ended": false, "countries": [], "news": [], "selected_country": null, "crisis": {"active": false},
  "tutorial": {"active": false}, "undo_available": false}
func shell():
 root.size = Vector2i(1280, 800)
 var host = ShellHarness.new()
 host.backend_url = "http://127.0.0.1:1"
 host.reduced_motion = true
 root.add_child(host)
 host.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
 host._build_ui()
 return host
'''


class DesktopShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        runtime.GodotRuntimeTests.setUpClass.__func__(cls)

    def test_start_menu_campaign_entry_and_language_rebuild(self):
        runtime.GodotRuntimeTests.run_godot(self, SHELL + '''
func run() -> void:
 var host = shell()
 await process_frame
 await process_frame
 assert(host.start_screen.visible and not host.ui.visible and not host.game_visible)
 assert(host.captured.size() == 1 and host.captured[0].command == "save_list")
 var continue_button = host.start_screen.find_child("ContinueButton", true, false)
 assert(continue_button.disabled)
 host.captured[0].after.call({"ok": true, "last_slot": null})
 assert(continue_button.disabled)
 host.captured[0].after.call({"ok": true, "last_slot": "Moscow 1984"})
 assert(not continue_button.disabled)
 continue_button.pressed.emit()
 assert(host.captured[-1].command == "load" and host.captured[-1].args.slot == "Moscow 1984")
 host.captured[-1].after.call({"ok": false})
 assert(not host.game_visible)
 host._set_status("Load failed")
 assert(host.start_screen.find_child("MenuStatus", true, false).text == "Load failed")
 host.start_screen.find_child("NewGameButton", true, false).pressed.emit()
 host.popup.find_child("StartCampaignButton", true, false).pressed.emit()
 assert(host.captured[-1].command == "new_game" and not host.game_visible)
 var start_reply: Callable = host.captured[-1].after
 start_reply.call({"ok": false})
 assert(not host.game_visible)
 host.state = campaign()
 host._render_state()
 start_reply.call({"ok": true})
 await process_frame
 await process_frame
 assert(host.ui.visible and host.game_visible and not is_instance_valid(host.start_screen))
 var size: Vector2 = host.get_viewport_rect().size
 assert(host.map_view.size.x * host.map_view.size.y >= size.x * size.y * 0.70)
 # Rebuilding for language switches must not leave interactive drawer siblings.
 var count: int = host.get_child_count()
 for _i in range(3):
  host._change_language()
  await process_frame
  await process_frame
  assert(host.get_child_count() == count)
 assert(host.game_visible and host.ui.visible)
 host._show_start_menu()
 await process_frame
 assert(not host.ui.visible and not host.country_drawer.visible and not host.guide_panel.visible)
 host.start_screen.find_child("ContinueButton", true, false).pressed.emit()
 assert(host.game_visible)
 host.queue_free()
 await process_frame
 print("RUNTIME_REGRESSION_OK")
 quit()
''')

    def test_network_crisis_controls_and_menu_overlay_isolation(self):
        runtime.GodotRuntimeTests.run_godot(self, SHELL + '''
func run() -> void:
 var host = shell()
 host.state = campaign()
 host._show_game()
 host.network_state = {"active": true, "mode": "guest", "status": "playing", "local_side": 1, "can_act": false,
  "duel": {"decider": 0, "actor": 0, "victim": 4, "action": 2, "old": 0, "new": 1, "level": 9,
   "phase": "question", "headline": "A policy is contested", "choices": ["accept", "contest"], "advice": [], "advice_ru": []}}
 host._render_state()
 await process_frame
 assert(host.country_drawer.visible and host.end_button.disabled)
 assert(host.crisis_actions.find_child("CrisisChoice_contest", true, false).disabled)
 host.network_state.local_side = 0
 host._render_state()
 var contest = host.crisis_actions.find_child("CrisisChoice_contest", true, false)
 assert(not contest.disabled)
 contest.pressed.emit()
 assert(host.captured[-1].command == "crisis_choice" and host.captured[-1].args.choice == "contest")
 # Polls can redraw a live crisis while the player has the start menu open.
 host._show_start_menu()
 host._render_state()
 host._update_guide()
 assert(not host.country_drawer.visible and not host.guide_panel.visible)
 assert(host.start_screen.find_child("NewGameButton", true, false).disabled)
 host._show_game()
 assert(host.country_drawer.visible)
 host.network_state.erase("duel")
 host.network_state.can_act = false
 host._update_end_button()
 assert(host.end_button.disabled)
 host.network_state.can_act = true
 host._update_end_button()
 assert(not host.end_button.disabled)
 host.queue_free()
 await process_frame
 print("RUNTIME_REGRESSION_OK")
 quit()
''')


if __name__ == '__main__':
    unittest.main()
