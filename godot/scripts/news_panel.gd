extends PanelContainer
## A dispatch desk: the feed is navigation; one report owns the reading space.
const L = preload("res://scripts/locale.gd")
const Reports = preload("res://scripts/reports.gd")
const PALE = Color("e7eadf")
const MUTED = Color("9bb2bf")
const AMBER = Color("edc580")
var host: Control
var articles: Array = []
var selected_id := -1
var selected_story := ""
var fingerprint := ""
var query: LineEdit
var category: OptionButton
var feed: VBoxContainer
var detail: VBoxContainer
var count_label: Label
var actions: Array[Button] = []
var challenge_button: Button

class CountryShape extends Control:
 var shapes: Array = []
 func _draw() -> void:
  draw_rect(Rect2(Vector2.ZERO, size), Color("173748"))
  for x in range(24, int(size.x), 32):
   draw_line(Vector2(x, 0), Vector2(x, size.y), Color("244958"))
  for y in range(16, int(size.y), 32):
   draw_line(Vector2(0, y), Vector2(size.x, y), Color("244958"))
  if shapes.is_empty(): return
  var bounds := Rect2(shapes[0][0], Vector2.ZERO)
  for points in shapes:
   for point in points: bounds = bounds.expand(point)
  var scale_factor := minf((size.x - 40) / maxf(bounds.size.x, 1), (size.y - 30) / maxf(bounds.size.y, 1))
  for points in shapes:
   var transformed := PackedVector2Array()
   for point in points: transformed.append((point - bounds.get_center()) * scale_factor + size / 2)
   if transformed.size() > 2:
    draw_colored_polygon(transformed, Color("497a88"))
    transformed.append(transformed[0])
    draw_polyline(transformed, Color("9cc5c9"), 1.5, true)

func word(en: String, ru: String) -> String:
 return ru if L.language == "ru" else en

func configure(owner_host: Control) -> void:
 host = owner_host
 name = "DispatchDesk"
 add_theme_stylebox_override("panel", host._style(Color("132e3f"), 8))
 var column := VBoxContainer.new()
 column.add_theme_constant_override("separation", 14)
 add_child(column)
 var header := HBoxContainer.new()
 column.add_child(header)
 var title: Label = host._label(L.text("news"), 28, PALE)
 title.size_flags_horizontal = SIZE_EXPAND_FILL
 header.add_child(title)
 count_label = host._label("", 14, MUTED)
 header.add_child(count_label)
 header.add_child(host._button(word("Back to map", "Вернуться к карте"), func(): hide()))
 var tools := HBoxContainer.new()
 column.add_child(tools)
 query = LineEdit.new()
 query.name = "DispatchSearch"
 query.placeholder_text = word("Search dispatches or countries", "Поиск донесений и стран")
 query.size_flags_horizontal = SIZE_EXPAND_FILL
 query.text_changed.connect(func(_value): _render())
 tools.add_child(query)
 category = OptionButton.new()
 for label in [word("All dispatches", "Все донесения"), word("Policy moves", "Политические действия"), word("World events", "События в мире"), word("Can challenge", "Можно оспорить")]: category.add_item(label)
 category.item_selected.connect(func(_index): _render())
 tools.add_child(category)
 var split := HBoxContainer.new()
 split.size_flags_vertical = SIZE_EXPAND_FILL
 split.add_theme_constant_override("separation", 20)
 column.add_child(split)
 var feed_scroll := ScrollContainer.new()
 feed_scroll.custom_minimum_size.x = 290
 feed_scroll.size_flags_horizontal = SIZE_EXPAND_FILL
 feed_scroll.size_flags_stretch_ratio = 0.85
 feed_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
 split.add_child(feed_scroll)
 feed = VBoxContainer.new()
 feed.size_flags_horizontal = SIZE_EXPAND_FILL
 feed_scroll.add_child(feed)
 split.add_child(VSeparator.new())
 var article_scroll := ScrollContainer.new()
 article_scroll.size_flags_horizontal = SIZE_EXPAND_FILL
 article_scroll.size_flags_stretch_ratio = 1.6
 article_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
 split.add_child(article_scroll)
 detail = VBoxContainer.new()
 detail.size_flags_horizontal = SIZE_EXPAND_FILL
 detail.add_theme_constant_override("separation", 14)
 article_scroll.add_child(detail)
 visibility_changed.connect(func(): if visible: query.grab_focus())

func update_news(data: Dictionary, _busy: bool, _network: Dictionary) -> void:
 articles = data.get("news", [])
 var next_key := JSON.stringify([articles, L.language, data.get("crisis", {}).get("active", false), data.get("ended", false), _network.get("active", false), host._can_act()])
 if next_key != fingerprint:
  fingerprint = next_key
  _render()
 _refresh_actions()

func _process(_delta: float) -> void:
 if visible: _refresh_actions()

func _unhandled_key_input(event: InputEvent) -> void:
 if visible and event is InputEventKey and event.pressed and event.keycode == KEY_ESCAPE:
  hide()
  get_viewport().set_input_as_handled()

func _country(item: Dictionary) -> int:
 var country = item.get("country_id", item.get("host", item.get("target", -1)))
 return int(country) if country != null else -1

func _policy(item: Dictionary) -> bool:
 return item.get("category", "") == "policy" if item.has("category") else int(item.get("action", -1)) in range(9) and int(item.get("actor", -1)) != int(item.get("target", -1))

func _headline(item: Dictionary) -> String:
 var supplied := str(item.get("headline_ru" if L.language == "ru" else "headline", ""))
 if not supplied.is_empty(): return supplied
 if _policy(item): return L.country(_country(item)) + ": " + L.policy(int(item.action))
 return host._news_text(item)

func _eligible(item: Dictionary) -> bool:
 return bool(item.get("questionable", false)) and not host.state.get("crisis", {}).get("active", false) and not host.state.get("ended", false) and not host.network_state.get("active", false) and host._can_act()

func _render() -> void:
 var focused := get_viewport().gui_get_focus_owner()
 var restore_feed_focus := is_instance_valid(focused) and focused is Button and focused.get_parent() == feed
 host._clear(feed)
 var filtered: Array = []
 for item in articles:
  var mode := category.selected
  if mode == 1 and not _policy(item): continue
  if mode == 2 and _policy(item): continue
  if mode == 3 and not _eligible(item): continue
  var searchable: String = _headline(item) + " " + host._news_text(item) + " " + L.country(_country(item)) + " " + str(item.get("text", "")) + " " + str(item.get("text_ru", "")) + " " + str(item.get("context", "")) + " " + str(item.get("context_ru", ""))
  if not query.text.strip_edges().is_empty() and not searchable.to_lower().contains(query.text.strip_edges().to_lower()): continue
  filtered.append(item)
 count_label.text = word("Briefing %s", "Сводка %s") % str(int(host.state.get("year", 1982)))
 count_label.text += "\n" + (word("%s of %s dispatches", "Донесений: %s из %s") % [filtered.size(), articles.size()])
 var retained := filtered.filter(func(item): return _story(item) == selected_story)
 if not retained.is_empty(): selected_id = int(retained[0].id)
 else:
  selected_id = int(filtered[0].id) if not filtered.is_empty() else -1
  selected_story = _story(filtered[0]) if not filtered.is_empty() else ""
 for item in filtered:
  var feed_metadata := str(item.get("category_ru" if L.language == "ru" else "category_en", ""))
  if _policy(item): feed_metadata = L.country(int(item.get("actor", -1))) + " / " + L.policy(int(item.get("action", -1)))
  var button: Button = host._button(feed_metadata + "\n" + _headline(item), func(): selected_id = int(item.id); selected_story = _story(item); _render())
  button.name = "Dispatch_%s" % item.id
  button.alignment = HORIZONTAL_ALIGNMENT_LEFT
  button.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
  button.add_theme_font_size_override("font_size", 16)
  button.add_theme_stylebox_override("normal", host._style(Color("305565") if int(item.id) == selected_id else Color("1a394a"), 4))
  button.custom_minimum_size.y = 66
  button.tooltip_text = host._news_text(item)
  feed.add_child(button)
 if filtered.is_empty(): feed.add_child(host._label(word("No matching dispatches. Clear the search or choose another filter.", "Нет подходящих донесений. Очистите поиск или измените фильтр."), 16, MUTED, true))
 _render_article()
 if restore_feed_focus:
  for button in feed.get_children():
   if button is Button and button.name == "Dispatch_%s" % selected_id: button.grab_focus.call_deferred()

func _story(item: Dictionary) -> String:
 return str(item.get("story_key", JSON.stringify([host.state.get("year"), item.get("id"), item.get("text") ])))

func _selected() -> Dictionary:
 for item in articles:
  if int(item.id) == selected_id and _story(item) == selected_story: return item
 return {}

func _render_article() -> void:
 host._clear(detail)
 actions.clear()
 challenge_button = null
 var item := _selected()
 if item.is_empty():
  detail.add_child(host._label(L.text("quiet") if articles.is_empty() else word("Select a dispatch to read the report.", "Выберите донесение для чтения."), 22, MUTED, true))
  return
 var country := _country(item)
 var metadata := str(item.get("category_ru" if L.language == "ru" else "category_en", word("Policy move", "Политическое действие") if _policy(item) else word("World event", "Событие в мире")))
 if item.get("year") != null: metadata += "   /   " + str(int(item.year))
 detail.add_child(host._label(metadata, 14, AMBER, true))
 detail.add_child(host._label(_headline(item), 27, PALE, true))
 if country in range(80):
  var geo := HBoxContainer.new()
  detail.add_child(geo)
  var shape := CountryShape.new()
  shape.custom_minimum_size = Vector2(150, 100)
  shape.mouse_filter = Control.MOUSE_FILTER_IGNORE
  for polygon in host.map_view.polygons:
   if int(polygon.id) == country: shape.shapes.append(polygon.points)
  geo.add_child(shape)
  var location := VBoxContainer.new()
  location.size_flags_horizontal = SIZE_EXPAND_FILL
  geo.add_child(location)
  location.add_child(host._label(L.country(country), 21, PALE, true))
  if _policy(item): location.add_child(host._label(word("Acting power: ", "Инициатор: ") + L.country(int(item.actor)), 15, MUTED, true))
 if host._news_text(item) != _headline(item):
  detail.add_child(host._label(host._news_text(item), 18, PALE, true))
 if _policy(item):
  var change := PanelContainer.new()
  change.add_theme_stylebox_override("panel", host._style(Color("233f4d"), 5))
  detail.add_child(change)
  var changes := VBoxContainer.new()
  change.add_child(changes)
  changes.add_child(host._label(L.policy(int(item.action)), 15, MUTED, true))
  changes.add_child(host._label(str(item.get("old_text_ru" if L.language == "ru" else "old_text", L.step(int(item.action), int(item.old)))) + "  →  " + str(item.get("new_text_ru" if L.language == "ru" else "new_text", L.step(int(item.action), int(item.new)))), 20, AMBER, true))
 var context := str(item.get("context_ru" if L.language == "ru" else "context", ""))
 if not context.is_empty(): detail.add_child(host._label(context, 15, MUTED, true))
 var buttons := HFlowContainer.new()
 buttons.add_theme_constant_override("h_separation", 8)
 buttons.add_theme_constant_override("v_separation", 8)
 detail.add_child(buttons)
 if country in range(80):
  var map_button: Button = host._button(word("Show on map", "Показать на карте"), func(): _open_country(country, false, _story(item)))
  buttons.add_child(map_button)
  actions.append(map_button)
  var report_button: Button = host._button(L.text("country_report"), func(): _open_country(country, true, _story(item)))
  buttons.add_child(report_button)
  actions.append(report_button)
 if _eligible(item):
  challenge_button = host._button(L.text("challenge"), _challenge.bind(selected_id, selected_story))
  challenge_button.add_theme_stylebox_override("normal", host._style(Color("755a32")))
  buttons.add_child(challenge_button)
 _refresh_actions()

func _refresh_actions() -> void:
 for button in actions:
  if is_instance_valid(button): button.disabled = host.busy
 if is_instance_valid(challenge_button): challenge_button.disabled = host.busy or not _eligible(_selected())

func _challenge(id: int, expected_story: String = "") -> void:
 var item := _selected()
 if host.busy or item.is_empty() or int(item.id) != id or not _eligible(item): return
 if not expected_story.is_empty() and expected_story != selected_story: return
 host._command("question", {"news_id": id}, func(response):
  if response.get("ok", false):
   hide()
   if host.state.get("crisis", {}).get("active", false): host._show_drawer(host.country_drawer)
 )

func _open_country(country: int, report: bool, expected_story: String = "") -> void:
 if host.busy: return
 if not expected_story.is_empty() and expected_story != selected_story: return
 host._command("select_country", {"country_id": country}, func(response):
  if not response.get("ok", false): return
  if report:
   Reports.show_report(host, "country")
  else:
   hide()
   host.country_drawer.hide()
   host.map_view.zoom = maxf(host.map_view.zoom, 3.2)
   host.map_view.pan = Vector2.ZERO
   host.map_view.pan += host.map_view.size / 2 - host.map_view.transform_map() * host.map_view.country_anchor(country)
   host.map_view.queue_redraw()
 )
