"""Real Godot map drawing, picking, navigation and bilingual briefing checks."""
import _isolate  # noqa: F401
import json
import unittest
import test_godot_runtime as runtime
from test_desktop_shell import SHELL
from test_map_scene import seeded_visual_qa_service


class MapSceneUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        runtime.GodotRuntimeTests.setUpClass.__func__(cls)

    def test_real_map_draw_input_layers_and_briefings(self):
        fixture = json.dumps(json.dumps(seeded_visual_qa_service().view(), ensure_ascii=False))
        runtime.GodotRuntimeTests.run_godot(self, SHELL + '''
func text_tree(node: Node) -> String:
 var text := str(node.get("text")) if node is Label or node is Button else ""
 for child in node.get_children(): text += "\n" + text_tree(child)
 return text
func click_map(chart: Control, at: Vector2, twice: bool = false) -> void:
 var event := InputEventMouseButton.new()
 event.position = at
 event.button_index = MOUSE_BUTTON_LEFT
 event.pressed = true
 event.double_click = twice
 chart._gui_input(event)
func run() -> void:
 var host = shell()
 host.state = JSON.parse_string(FIXTURE)
 host._show_game()
 host._render_state()
 await process_frame
 await process_frame
 var chart = host.map_view
 chart.zoom = 3.0
 chart.set_layer("roads", true)
 chart.set_layer("events", true)
 chart.set_layer("cities", true)
 chart.queue_redraw()
 await process_frame
 await process_frame
 assert(chart.city_hit_regions.size() > 0, "City draw/pick regions not built")
 assert(chart.event_hit_regions.size() > 0 and chart.route_hit_regions.size() > 0)
 var picked := {"city": {}, "event": {}, "route": {}}
 chart.city_selected.connect(func(value): picked.city = value)
 chart.event_selected.connect(func(value): picked.event = value)
 chart.route_selected.connect(func(value): picked.route = value)
 # Pick actual generated event badges, with production event precedence.
 var badge: Dictionary = {}
 for region in chart.event_hit_regions:
  if Rect2(Vector2.ZERO, chart.size).has_point(region.rect.get_center()):
   badge = region
   break
 assert(not badge.is_empty())
 click_map(chart, badge.rect.get_center())
 assert(picked.event == badge.event)
 assert(not picked.event.label.is_empty())
 # Remove badges to exercise city picking without their intentional overlap.
 chart.set_layer("events", false)
 chart.set_layer("roads", false)
 await process_frame
 await process_frame
 assert(chart.event_hit_regions.is_empty() and chart.route_hit_regions.is_empty())
 var city: Dictionary = {}
 for region in chart.city_hit_regions:
  if Rect2(Vector2.ZERO, chart.size).has_point(region.rect.get_center()):
   city = region
   break
 assert(not city.is_empty())
 click_map(chart, city.rect.get_center(), true)
 assert(not picked.city.is_empty() and picked.city.has("status"))
 assert(chart.zoom >= 3.2)
 var centered: Vector2 = chart.transform_map() * chart.country_anchor(int(picked.city.country_id))
 assert(centered.distance_to(chart.size / 2.0) < 0.01)
 # Zoom must preserve the map coordinate beneath the cursor.
 var cursor: Vector2 = chart.size * Vector2(0.37, 0.61)
 var before: Vector2 = chart.transform_map().affine_inverse() * cursor
 var wheel := InputEventMouseButton.new()
 wheel.position = cursor
 wheel.button_index = MOUSE_BUTTON_WHEEL_UP
 wheel.pressed = true
 chart._gui_input(wheel)
 assert((chart.transform_map().affine_inverse() * cursor).distance_to(before) < 0.001)
 var key := InputEventKey.new()
 key.keycode = KEY_F
 key.pressed = true
 chart._gui_input(key)
 assert(chart.zoom == 1.0 and chart.pan == Vector2.ZERO)
 chart.set_layer("cities", false)
 chart.set_layer("roads", true)
 await process_frame
 await process_frame
 assert(chart.city_hit_regions.is_empty())
 assert(chart.city_at(city.rect.get_center()).is_empty())
 # Multiple policies to one target must remain accessible through one line.
 var bundled := false
 for region in chart.route_hit_regions:
  if region.route.get("commitments", []).size() > 1:
   host._map_route_briefing(region.route)
   var briefing := text_tree(host.popup)
   for policy in region.route.commitments:
    assert(briefing.contains(str(policy.label)) and briefing.contains(str(policy.value_label)))
   bundled = true
   break
 assert(bundled, "Real fixture must exercise overlapping policy commitments")
 var connection: Dictionary = chart.route_hit_regions[0]
 var middle: Vector2 = connection.points[12]
 assert(not chart.route_at(middle).is_empty())
 click_map(chart, middle)
 assert(not picked.route.is_empty())
 chart.set_layer("roads", false)
 await process_frame
 await process_frame
 assert(chart.route_at(middle).is_empty())
 chart.reduced_motion = true
 chart.update_world(host.state.countries, 40)
 assert(chart.selection_glow == 0.0)
 for language in ["en", "ru"]:
  Locale.language = language
  host._map_route_briefing(connection.route)
  var route_text := text_tree(host.popup)
  assert(route_text.contains(str(connection.route.get("value_label_ru" if language == "ru" else "value_label"))))
  assert(route_text.contains("не дорогу" if language == "ru" else "not a road"))
  host._map_briefing(int(badge.event.country_id), badge.event)
  var event_text := text_tree(host.popup)
  assert(event_text.contains("Безопасность" if language == "ru" else "Security"))
  host._open_map_layers()
  var toggle = host.popup.find_child("MapLayer_cities", true, false)
  assert(toggle != null)
  toggle.button_pressed = false
  assert(not chart.layers.cities)
 print("RUNTIME_REGRESSION_OK")
 quit()
'''.replace('FIXTURE', fixture))


if __name__ == "__main__":
    unittest.main()
