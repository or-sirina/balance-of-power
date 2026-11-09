"""Exercise the interactive news desk using real Godot controls and fake commands."""
import _isolate  # noqa: F401
import unittest
import test_godot_runtime as runtime
from test_desktop_shell import SHELL


NEWS_FIXTURE = '''
func headline(id: int, target: int, action: int, text: String, questionable: bool = false) -> Dictionary:
 return {"id": id, "actor": 1, "target": target, "host": 1, "action": action,
  "old": 0, "new": 2, "text": text, "text_ru": "Русская новость " + text,
  "type": "Military aid", "type_ru": "Военная помощь", "questionable": questionable,
  "old_text": "None", "new_text": "20 million", "old_text_ru": "Нет", "new_text_ru": "20 миллионов",
  "headline": text, "headline_ru": "Русский заголовок " + text, "category": "policy",
  "category_en": "Policy", "category_ru": "Политика", "country_id": target,
  "context": "Background " + text, "context_ru": "Контекст " + text,
  "story_key": "1982:" + str(id), "year": null}
func news_campaign() -> Dictionary:
 var world := campaign()
 world.news = [headline(0, 2, 2, "Angola aid", true), headline(1, 3, 3, "Brazil troops"), headline(2, 4, 2, "Cuba aid", true)]
 return world
'''


class NewsFeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        runtime.GodotRuntimeTests.setUpClass.__func__(cls)

    def probe(self, body):
        runtime.GodotRuntimeTests.run_godot(self, SHELL + NEWS_FIXTURE + body)

    def test_selection_search_filters_and_replaced_world(self):
        self.probe('''
func run() -> void:
 var host = shell()
 host.state = news_campaign()
 host.state.news[1].category = "historical"
 host._show_game()
 host._render_state()
 var desk = host.news_drawer
 host.country_drawer.show()
 host._toggle_drawer(desk)
 assert(desk.visible and not host.country_drawer.visible)
 host._toggle_drawer(host.country_drawer)
 assert(host.country_drawer.visible and not desk.visible)
 host._toggle_drawer(desk)
 await process_frame
 assert(desk.feed.get_child_count() == 3 and desk.selected_id >= 0)
 desk.feed.get_node("Dispatch_2").pressed.emit()
 assert(desk.selected_id == 2 and desk._selected().headline == "Cuba aid")
 desk.query.text = "  BRAZIL  "
 desk.query.text_changed.emit(desk.query.text)
 assert(desk.feed.get_child_count() == 1 and desk.selected_id == 1)
 desk.query.text = "nothing matches this search"
 desk.query.text_changed.emit(desk.query.text)
 assert(desk.selected_id == -1 and desk._selected().is_empty() and desk.challenge_button == null)
 desk.query.text = ""
 desk.category.select(1)
 desk.category.item_selected.emit(1)
 assert(desk.feed.get_child_count() == 2 and desk.feed.has_node("Dispatch_0") and desk.feed.has_node("Dispatch_2"))
 desk.category.select(2)
 desk.category.item_selected.emit(2)
 assert(desk.feed.get_child_count() == 1 and desk.selected_id == 1)
 desk.category.select(3)
 desk.category.item_selected.emit(3)
 assert(desk.feed.get_child_count() == 2 and is_instance_valid(desk.challenge_button))
 host.state.crisis.active = true
 desk.update_news(host.state, host.busy, host.network_state)
 assert(desk.selected_id == -1)
 host.state.crisis.active = false
 desk.update_news(host.state, host.busy, host.network_state)
 assert(desk.feed.get_child_count() == 2)
 # Polling updates preserve the selected semantic story but refresh its values.
 desk.feed.get_node("Dispatch_2").pressed.emit()
 host.state.news[2].new_text = "80 million"
 host._render_state()
 assert(desk.selected_id == 2 and desk._selected().new_text == "80 million")
 # The next year can reuse positional command id 2 for a different story.
 host.state.year = 1983
 host.state.news = [headline(2, 5, 2, "Replacement story", true)]
 host.state.news[0].story_key = "1983:new"
 var old_story: String = desk.selected_story
 host._render_state()
 var count: int = host.captured.size()
 desk._challenge(2, old_story)
 desk._open_country(4, false, old_story)
 assert(host.captured.size() == count)
 assert(desk.selected_story == "1983:new" and desk._selected().headline == "Replacement story")
 host.state = news_campaign()
 host._render_state()
 assert(desk.selected_story.begins_with("1982:") and desk._selected().headline != "Replacement story")
 host.state.news = []
 host._render_state()
 assert(desk.selected_id == -1 and desk._selected().is_empty())
 host.queue_free()
 await process_frame
 print("RUNTIME_REGRESSION_OK")
 quit()
''')

    def test_challenge_gates_and_country_actions_use_current_selection(self):
        self.probe('''
func run() -> void:
 var host = shell()
 host.state = news_campaign()
 host._show_game()
 host._render_state()
 var desk = host.news_drawer
 desk.show()
 desk.feed.get_node("Dispatch_2").pressed.emit()
 var count: int = host.captured.size()
 desk.challenge_button.pressed.emit()
 assert(host.captured.size() == count + 1 and host.captured[-1].command == "question" and host.captured[-1].args.news_id == 2)
 host.captured[-1].after.call({"ok": false})
 assert(desk.visible)
 desk.challenge_button.pressed.emit()
 host.state.crisis.active = true
 host.captured[-1].after.call({"ok": true})
 assert(not desk.visible and host.country_drawer.visible)
 host.state.crisis.active = false
 desk.show()
 # A formerly enabled signal/callback must recheck the live authoritative gate.
 for gate in ["busy", "crisis", "ended", "network", "network_turn"]:
  if gate == "busy": host.busy = true
  if gate == "crisis": host.state.crisis.active = true
  if gate == "ended": host.state.ended = true
  if gate == "network": host.network_state = {"active": true, "can_act": false}
  if gate == "network_turn": host.network_state = {"active": true, "can_act": true}
  count = host.captured.size()
  desk._challenge(2)
  desk._refresh_actions()
  assert(host.captured.size() == count and desk.challenge_button.disabled)
  host.busy = false
  host.state.crisis.active = false
  host.state.ended = false
  host.network_state = {}
 desk._challenge(0)
 assert(host.captured.size() == count)
 # Country navigation is tied to this article, rather than the map's prior selection.
 desk.actions[0].pressed.emit()
 assert(host.captured[-1].command == "select_country" and host.captured[-1].args.country_id == 4)
 host.captured[-1].after.call({"ok": false})
 assert(desk.visible)
 host.state.selected_country = 4
 desk.actions[0].pressed.emit()
 host.captured[-1].after.call({"ok": true})
 assert(not desk.visible and host.map_view.zoom >= 3.2 and not host.country_drawer.visible)
 desk.show()
 desk.actions[1].pressed.emit()
 assert(host.captured[-1].command == "select_country" and host.captured[-1].args.country_id == 4)
 host.captured[-1].after.call({"ok": true})
 assert(host.captured[-1].command == "report" and host.captured[-1].args.country_id == 4)
 host.queue_free()
 await process_frame
 print("RUNTIME_REGRESSION_OK")
 quit()
''')

    def test_russian_search_and_narrow_screen_controls_fit(self):
        self.probe('''
func run() -> void:
 Locale.language = "ru"
 var host = shell()
 root.size = Vector2i(1024, 720)
 host.state = news_campaign()
 host._show_game()
 host._render_state()
 var desk = host.news_drawer
 desk.show()
 desk.query.text = "Контекст Cuba"
 desk.query.text_changed.emit(desk.query.text)
 assert(desk.selected_id == 2 and desk.feed.get_child_count() == 1)
 for _i in range(5): await process_frame
 var bounds: Rect2 = host.get_global_rect()
 assert(bounds.encloses(desk.get_global_rect()))
 assert(desk.get_global_rect().encloses(desk.query.get_global_rect()))
 assert(desk.get_global_rect().encloses(desk.category.get_global_rect()))
 assert(desk.feed.size.x >= 250 and desk.detail.size.x >= 320)
 for action in desk.actions:
  assert(action.size.x <= desk.detail.size.x)
 assert(desk.challenge_button.text == Locale.text("challenge"))
 host.queue_free()
 await process_frame
 print("RUNTIME_REGRESSION_OK")
 quit()
''')


if __name__ == '__main__':
    unittest.main()
