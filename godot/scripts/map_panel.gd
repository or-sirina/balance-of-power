extends RefCounted
## Read-only map briefings and presentation controls.
const L = preload("res://scripts/locale.gd")

static func word(en: String, ru: String) -> String:
 return ru if L.language == "ru" else en

static func show_layers(host: Control) -> void:
 var column: VBoxContainer = host._dialog(word("Map layers", "Слои карты"), Vector2i(620, 590))
 var captions := {"cities": ["City miniatures and streets", "Городские модели и улицы"], "roads": ["Aid and trade connections", "Связи помощи и торговли"], "events": ["Conflicts and unrest", "Конфликты и волнения"], "labels": ["Place labels", "Подписи на карте"]}
 for key in ["cities", "roads", "events", "labels"]:
  var toggle := CheckButton.new()
  toggle.name = "MapLayer_" + key
  toggle.text = str(captions[key][1 if L.language == "ru" else 0])
  toggle.button_pressed = host.map_layers[key]
  toggle.toggled.connect(func(enabled):
   host.map_layers[key] = enabled
   host.map_view.set_layer(key, enabled)
   host._save_preferences()
  )
  column.add_child(toggle)
 var terrain := CheckButton.new()
 terrain.name = "MapLayer_relief"
 terrain.text = word("Terrain relief", "Рельеф местности")
 terrain.button_pressed = host.relief_enabled
 terrain.toggled.connect(func(enabled): host.relief_enabled = enabled; host.map_view.relief_enabled = enabled; host._save_preferences())
 column.add_child(terrain)
 column.add_child(host._label(word("Wheel: zoom · Middle drag: move · Double-click: focus · F: whole map", "Колесо: масштаб · Средняя кнопка: перемещение · Двойной щелчок: приблизить · F: вся карта"), 14, host.MUTED, true))
 column.add_child(host._label(word("The world view highlights major developments. Zoom in to see minor unrest and all events.", "На общей карте выделены главные события. Приблизьте карту, чтобы увидеть небольшие волнения и остальные события."), 14, host.MUTED, true))
 column.add_child(host._label(word("Cities and streets illustrate each country. Connections show your aid, intervention and trade policies. Select a country to isolate its links.", "Города и улицы обозначают страны. Связи показывают вашу помощь, вмешательство и торговую политику. Выберите страну, чтобы оставить только её связи."), 14, host.MUTED, true))

static func country_status(host: Control, country_id: int) -> Dictionary:
 for row in host.state.get("map_scene", {}).get("countries", []):
  if int(row.id) == country_id: return row
 return {}

static func render_details(host: Control, container: VBoxContainer) -> void:
 host._clear(container)
 var selected = host.state.get("selected_country")
 if selected == null: return
 var row := country_status(host, int(selected))
 if row.is_empty(): return
 var suffix := "_ru" if L.language == "ru" else ""
 container.add_child(host._label(word("On the map", "На карте"), 17, host.MUTED))
 container.add_child(host._label(str(row.get("insurgency_label" + suffix, "")) + "\n" + str(row.get("stability_label" + suffix, "")), 14, host.PAPER, true))
 for event in host.state.get("map_scene", {}).get("events", []):
  if int(event.country_id) == int(selected):
   var button: Button = host._button(str(event.get("label" + suffix, "")), show_event.bind(host, int(selected), event))
   button.name = "MapEvent_" + str(event.kind)
   button.add_theme_font_size_override("font_size", 13)
   container.add_child(button)
 container.add_child(host._label(word("Country-level situation. City models do not locate individual battles or protests.", "Обстановка в стране. Модели городов не указывают точное место боёв или протестов."), 12, host.MUTED, true))
 container.add_child(HSeparator.new())

static func show_event(host: Control, country_id: int, event: Dictionary) -> void:
 var suffix := "_ru" if L.language == "ru" else ""
 var column: VBoxContainer = host._dialog(str(event.get("label" + suffix, word("Situation briefing", "Обзор обстановки"))), Vector2i(660, 570))
 column.add_child(host._label(L.country(country_id) + " · " + str(int(host.state.get("year", 1982))), 23, Color("eddaa8")))
 var row := country_status(host, country_id)
 column.add_child(host._label(word("Security: ", "Безопасность: ") + str(row.get("insurgency_label" + suffix, "")) + "\n" + word("Government: ", "Правительство: ") + str(row.get("stability_label" + suffix, "")), 16, host.PAPER, true))
 var recorded := str(event.get("source", "")) == "turn_event"
 column.add_child(host._label(word("Recorded during the current turn.", "Зафиксировано в текущем ходе.") if recorded else word("Current security assessment from the simulation.", "Текущая оценка безопасности в симуляции."), 14, host.MUTED, true))
 var scroll := ScrollContainer.new()
 scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
 scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
 var news := VBoxContainer.new()
 news.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 scroll.add_child(news)
 column.add_child(scroll)
 var count := 0
 var rows: Array = host.state.get("news", [])
 for index in range(rows.size()-1, -1, -1):
  var item: Dictionary = rows[index]
  if country_id not in [int(item.get("actor", -1)), int(item.get("target", -1)), int(item.get("host", -1))]: continue
  news.add_child(host._label(host._news_text(item), 14, host.PAPER, true))
  news.add_child(HSeparator.new())
  count += 1
  if count == 4: break
 if count == 0: news.add_child(host._label(word("No related dispatches this turn.", "Связанных донесений в этом ходе нет."), 14, host.MUTED, true))
 column.add_child(host._label(word("The marker describes the country as a whole; its city placement is illustrative.", "Значок относится ко всей стране; положение городской модели условное."), 13, host.MUTED, true))
 var window: Window = host.popup
 column.add_child(host._button(word("Open country", "Открыть страну"), func(): window.hide(); window.queue_free(); host._select_country(country_id)))

static func show_route(host: Control, route: Dictionary) -> void:
 var suffix := "_ru" if L.language == "ru" else ""
 var column: VBoxContainer = host._dialog(word("Policy connection", "Связь между странами"), Vector2i(600, 590))
 column.add_child(host._label(L.country(int(route.actor)) + " → " + L.country(int(route.target)), 23, Color("eddaa8"), true))
 column.add_child(host._label(str(route.get("label" + suffix, "")) + ": " + str(route.get("value_label" + suffix, "")), 19, host.PAPER, true))
 if route.get("commitments", []).size() > 1:
  var scroll := ScrollContainer.new()
  scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
  scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
  var commitments := VBoxContainer.new()
  commitments.size_flags_horizontal = Control.SIZE_EXPAND_FILL
  scroll.add_child(commitments)
  column.add_child(scroll)
  for item in route.commitments:
   commitments.add_child(host._label(str(item.get("label" + suffix, "")) + ": " + str(item.get("value_label" + suffix, "")), 16, host.PAPER, true))
 column.add_child(host._label(word("This is your current policy commitment. The line shows who supports whom; it is not a road or a simulated supply route.", "Это ваше текущее политическое обязательство. Линия показывает связь между странами, а не дорогу или маршрут снабжения."), 16, host.MUTED, true))
 var window: Window = host.popup
 column.add_child(host._button(word("Review policy in target country", "Проверить политику в стране"), func(): window.hide(); window.queue_free(); host._select_country(int(route.target))))
