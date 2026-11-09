"""Real Godot multiplayer controls, localized captions and lobby transitions."""
import _isolate  # noqa: F401
import unittest
import test_godot_runtime as runtime


class MultiplayerUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        runtime.GodotRuntimeTests.setUpClass.__func__(cls)

    def test_controls_commands_and_lobby_permissions(self):
        runtime.GodotRuntimeTests.run_godot(self, '''
class SessionProbe extends "res://scripts/multiplayer_panel.gd":
 var entered := false
 func _enter_game() -> void: entered = true
func run() -> void:
 var host = create_harness(true)
 var panel = load("res://scripts/multiplayer_panel.gd").new()
 panel.show(host)
 var window = host.popup
 var side = window.find_child("MultiplayerSide", true, false)
 var level = window.find_child("MultiplayerLevel", true, false)
 assert(side.item_count == 2 and level.item_count == 5)
 side.select(1)
 level.select(3)
 window.find_child("MultiplayerPort", true, false).value = 34567
 window.find_child("HostMultiplayer", true, false).pressed.emit()
 assert(host.captured[-1].command == "multiplayer_host")
 assert(host.captured[-1].args == {"side": 1, "level": 4, "port": 34567})
 host.captured[-1].after.call({"ok": true, "multiplayer": {"active": true, "mode": "host", "status": "waiting", "local_side": 1}})
 assert(window.find_child("StartMultiplayer", true, false).disabled)
 assert(window.find_child("JoinMultiplayer", true, false).disabled)
 panel._network_changed({"active": true, "mode": "host", "status": "lobby", "local_side": 1})
 assert(not window.find_child("StartMultiplayer", true, false).disabled)
 panel._network_changed({"active": false, "games": [{"name": "Partner", "address": "192.0.2.5", "port": 34568}]})
 var games = window.find_child("DiscoveredGames", true, false)
 assert(games.item_count == 1)
 games.item_selected.emit(0)
 assert(window.find_child("MultiplayerAddress", true, false).text == "192.0.2.5")
 assert(window.find_child("MultiplayerPort", true, false).value == 34568)
 window.queue_free()
 await process_frame
 Locale.language = "ru"
 panel = load("res://scripts/multiplayer_panel.gd").new()
 panel.show(host)
 assert(host.popup.find_child("HostMultiplayer", true, false).text == "Создать партию")
 assert(not host.popup.find_child("HostMultiplayer", true, false).text.contains("/"))
 host.popup.queue_free()
 await process_frame
 host.network_state = {"active": true, "mode": "guest", "status": "playing"}
 var probe = SessionProbe.new()
 probe.show(host)
 await process_frame
 assert(not probe.entered)
 probe._network_changed({"active": true, "mode": "guest", "status": "lobby"})
 probe._network_changed({"active": true, "mode": "guest", "status": "playing"})
 assert(not probe.entered)
 await process_frame
 assert(probe.entered)
 host.state.clear()
 host.popup.find_child("LeaveMultiplayer", true, false).pressed.emit()
 assert(host.captured[-1].command == "multiplayer_leave")
 host.captured[-1].after.call({"ok": true, "state": null, "multiplayer": {"active": false, "status": "offline"}})
 await process_frame
 assert(is_instance_valid(host.start_screen) and host.start_screen.visible)
 assert(not host.game_visible)
 print("RUNTIME_REGRESSION_OK")
 quit()
''')


if __name__ == "__main__":
    unittest.main()
