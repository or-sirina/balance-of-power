extends Control

signal advisor_answered(response: Dictionary)
signal crisis_briefing_ready(result: Dictionary)
signal map_report_ready(mode: int)
signal network_changed(network: Dictionary)

const L = preload("res://scripts/locale.gd")
const WorldMap = preload("res://scripts/world_map.gd")
const Reports = preload("res://scripts/reports.gd")
const GameMasterPanel = preload("res://scripts/game_master_panel.gd")
const AISettings = preload("res://scripts/ai_settings.gd")
const AdvisorPanel = preload("res://scripts/advisor_panel.gd")
const SoundSignals = preload("res://scripts/sound_signals.gd")
const NewsPanel = preload("res://scripts/news_panel.gd")
const MapPanel = preload("res://scripts/map_panel.gd")
const INK = Color("152f40")
const PAPER = Color("e7eadf")
const MUTED = Color("9bb2bf")
var start_screen: PanelContainer
var menu_status_label: Label
var country_drawer: PanelContainer
var news_drawer: PanelContainer
var guide_panel: PanelContainer
var game_visible := false
var colorblind := false
var sfx_enabled := true
var relief_enabled := true
var map_layers := {"cities": true, "roads": false, "events": true, "labels": true}
var sound_signals: Node
var network_state: Dictionary = {}
var network_poll_pending := false
var undo_button: Button
var backend_url := ""
var token := ""
var revision := 0
var request_counter := 0
var state: Dictionary = {}
var busy := false
var ui: VBoxContainer
var map_view: Control
var map_group_picker: OptionButton
var map_picker: OptionButton
var map_source_label: Label
var map_legend: HFlowContainer
var map_mode_id := 17
var map_request_key := ""
var map_report: Dictionary = {}
var year_label: Label
var score_label: Label
var country_label: Label
var facts_label: Label
var map_details_box: VBoxContainer
var status_label: Label
var policies_box: VBoxContainer
var crisis_box: VBoxContainer
var crisis_actions: HBoxContainer
var country_picker: OptionButton
var end_button: Button
var guide_box: VBoxContainer
var guide_label: Label
var guide_scroll: ScrollContainer
var guide_button: Button
var guide_enabled := false
var guide_step := 0
var guide_year := 1982
var reduced_motion := false
var popup: Window
var audio_player: AudioStreamPlayer
var track_index := 0
var music_enabled := false
var volume := -20.0
var smoke_test := false
var screenshot_path := ""
var smoke_phase := 0
var smoke_policy: Dictionary = {}
var smoke_challenged := false
var smoke_campaign: Dictionary = {}
var model_revision := -1
var dialogue_result: Dictionary = {}
var dialogue_pending := false
var dialogue_identity := ""
var dialogue_generation := 0
var settings_generation := 0
var shown_year := 0
var shown_ending := ""
var game_master_panel := GameMasterPanel.new()
var ai_settings := AISettings.new()
var advisor_panel := AdvisorPanel.new()
var track_names := ["detente.wav", "ambient_synthwave4k.ogg", "coldwar.wav", "ambient_mindstream.ogg", "defcon.wav", "tension_wastelands.ogg"]

func _ready() -> void:
 get_viewport().gui_embed_subwindows = true
 for i in range(OS.get_cmdline_user_args().size()):
  var args := OS.get_cmdline_user_args()
  if args[i] == "--backend-url" and i + 1 < args.size():
   backend_url = args[i + 1]
  elif args[i] == "--backend-token" and i + 1 < args.size():
   token = args[i + 1]
  elif args[i] == "--smoke-test":
   smoke_test = true
  elif args[i] == "--screenshot" and i + 1 < args.size():
   screenshot_path = args[i + 1]
 _load_preferences()
 var user_args := OS.get_cmdline_user_args()
 var language_arg := user_args.find("--language")
 if language_arg >= 0 and language_arg + 1 < user_args.size() and user_args[language_arg + 1] in ["en", "ru"]:
  L.language = user_args[language_arg + 1]
 audio_player = AudioStreamPlayer.new()
 audio_player.volume_db = volume
 audio_player.finished.connect(_next_track)
 add_child(audio_player)
 sound_signals = SoundSignals.new()
 add_child(sound_signals)
 _build_ui()
 if backend_url.is_empty():
  _set_status(L.text("connection_error"))
  if smoke_test:
   get_tree().quit(1)
  return
 var network_timer := Timer.new()
 network_timer.wait_time = 1.0
 network_timer.timeout.connect(_poll_multiplayer)
 add_child(network_timer)
 network_timer.start()
 if smoke_test:
  await get_tree().process_frame
  await _snapshot_screen("start")
  start_screen.find_child("NewGameButton", true, false).pressed.emit()
  popup.find_child("StartCampaignButton", true, false).pressed.emit()
 if smoke_test:
  get_tree().create_timer(60).timeout.connect(func(): push_error("Godot smoke timed out"); get_tree().quit(1))

func _load_preferences() -> void:
 if smoke_test:
  return
 var config := ConfigFile.new()
 if config.load("user://presentation.cfg") == OK:
  L.language = config.get_value("ui", "language", "en")
  reduced_motion = config.get_value("ui", "reduced_motion", false)
  music_enabled = config.get_value("audio", "enabled", false)
  volume = config.get_value("audio", "volume", -20.0)
  track_index = config.get_value("audio", "track", 0)
  colorblind = config.get_value("ui", "colorblind", false)
  sfx_enabled = config.get_value("audio", "sfx", true)
  relief_enabled = config.get_value("ui", "relief", true)
  for layer in map_layers: map_layers[layer] = bool(config.get_value("map", layer, map_layers[layer]))

func _save_preferences() -> void:
 if smoke_test:
  return
 var config := ConfigFile.new()
 config.set_value("ui", "language", L.language)
 config.set_value("ui", "reduced_motion", reduced_motion)
 config.set_value("audio", "enabled", music_enabled)
 config.set_value("audio", "volume", volume)
 config.set_value("audio", "track", track_index)
 config.set_value("audio", "sfx", sfx_enabled)
 config.set_value("ui", "colorblind", colorblind)
 config.set_value("ui", "relief", relief_enabled)
 for layer in map_layers: config.set_value("map", layer, map_layers[layer])
 config.save("user://presentation.cfg")

func _style(color: Color, radius: int = 4) -> StyleBoxFlat:
 var box := StyleBoxFlat.new()
 box.bg_color = color
 box.set_corner_radius_all(radius)
 box.content_margin_left = 12
 box.content_margin_right = 12
 box.content_margin_top = 7
 box.content_margin_bottom = 7
 return box

func _theme() -> Theme:
 var result := Theme.new()
 result.default_font_size = 16
 result.set_color("font_color", "Label", PAPER)
 result.set_color("font_readonly_color", "TextEdit", PAPER)
 result.set_color("font_color", "Button", PAPER)
 result.set_color("font_hover_color", "Button", Color.WHITE)
 result.set_color("font_disabled_color", "Button", Color("72848b"))
 result.set_stylebox("normal", "Button", _style(Color("294c5d")))
 result.set_stylebox("hover", "Button", _style(Color("3a6475")))
 result.set_stylebox("pressed", "Button", _style(Color("426d7a")))
 result.set_stylebox("disabled", "Button", _style(Color("263d47")))
 var focus := _style(Color(0, 0, 0, 0))
 focus.border_color = Color("edd394")
 focus.set_border_width_all(2)
 result.set_stylebox("focus", "Button", focus)
 result.set_stylebox("normal", "OptionButton", _style(Color("294c5d")))
 result.set_stylebox("hover", "OptionButton", _style(Color("3a6475")))
 result.set_stylebox("focus", "OptionButton", focus)
 result.set_color("font_color", "OptionButton", PAPER)
 result.set_constant("separation", "VBoxContainer", 8)
 result.set_constant("separation", "HBoxContainer", 8)
 return result

func _label(text: String, font_size: int = 16, color: Color = PAPER, wrap: bool = false) -> Label:
 var label := Label.new()
 label.text = text
 label.add_theme_font_size_override("font_size", font_size)
 label.add_theme_color_override("font_color", color)
 if wrap:
  label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
 return label

func _button(text: String, callback: Callable) -> Button:
 var button := Button.new()
 button.text = text
 button.pressed.connect(callback)
 button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
 return button

func _expand(control: Control) -> Control:
 control.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 return control

func _clear(container: Node) -> void:
 for child in container.get_children():
  container.remove_child(child)
  child.queue_free()

func _build_ui() -> void:
 for overlay in [country_drawer, news_drawer, guide_panel, start_screen]:
  if is_instance_valid(overlay):
   remove_child(overlay)
   overlay.queue_free()
 country_drawer = null
 news_drawer = null
 guide_panel = null
 start_screen = null
 if is_instance_valid(ui):
  remove_child(ui)
  ui.queue_free()
 theme = _theme()
 ui = VBoxContainer.new()
 ui.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
 ui.offset_left = 12
 ui.offset_right = -12
 ui.offset_top = 10
 ui.offset_bottom = -14
 ui.add_theme_constant_override("separation", 6)
 add_child(ui)
 var header := HBoxContainer.new()
 header.add_child(_button(L.text("menu"), _show_start_menu))
 year_label = _label("1982", 24, Color("eddaa8"))
 header.add_child(year_label)
 score_label = _label("", 13, PAPER)
 header.add_child(_expand(score_label))
 header.add_child(_button("Сведения" if L.language == "ru" else "Reports", _open_reports))
 header.add_child(_button(L.text("advisor_short"), _advisor_dialog))
 header.add_child(_button(L.text("gamemaster"), func(): game_master_panel.open(self)))
 end_button = _button(L.text("end"), func(): _command("end_turn"))
 header.add_child(end_button)
 ui.add_child(header)
 var body := HBoxContainer.new()
 body.size_flags_vertical = Control.SIZE_EXPAND_FILL
 body.add_theme_constant_override("separation", 18)
 ui.add_child(body)
 var left := VBoxContainer.new()
 left.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 body.add_child(left)
 guide_box = VBoxContainer.new()
 guide_box.visible = guide_enabled
 var guide_header := HBoxContainer.new()
 guide_header.add_child(_expand(_label(L.text("lesson"), 19, Color("eddaa8"))))
 guide_header.add_child(_button(L.text("restart"), func(): _command("tutorial_start")))
 guide_header.add_child(_button(L.text("return_campaign"), func(): _command("tutorial_end")))
 guide_box.add_child(guide_header)
 var lesson_row := HBoxContainer.new()
 var mentor := TextureRect.new()
 mentor.texture = load("res://assets/advisors/usa_0.png")
 mentor.custom_minimum_size = Vector2(60, 80)
 mentor.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
 mentor.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
 lesson_row.add_child(mentor)
 guide_label = _label("", 16, PAPER, true)
 guide_scroll = ScrollContainer.new()
 guide_scroll.custom_minimum_size.y = 100
 guide_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
 guide_scroll.add_child(_expand(guide_label))
 lesson_row.add_child(_expand(guide_scroll))
 guide_box.add_child(lesson_row)
 guide_button = _button(L.text("ack"), func(): _command("tutorial_ack"))
 guide_box.add_child(guide_button)
 guide_panel = PanelContainer.new()
 guide_panel.add_theme_stylebox_override("panel", _style(INK))
 guide_panel.add_child(guide_box)
 add_child(guide_panel)
 guide_panel.set_anchors_and_offsets_preset(Control.PRESET_TOP_LEFT)
 guide_panel.position = Vector2(24, 110)
 guide_panel.custom_minimum_size = Vector2(420, 0)
 guide_panel.size.x = 420
 var map_toolbar := HBoxContainer.new()
 map_group_picker = OptionButton.new()
 for key in ["map_overview", "map_policies", "map_indicators"]: map_group_picker.add_item(L.text(key))
 map_group_picker.select(1)
 map_group_picker.item_selected.connect(func(_index):
  _populate_map_modes()
  for index in range(map_picker.item_count):
   if not map_picker.is_item_disabled(index):
    map_picker.select(index)
    map_mode_id = map_picker.get_item_id(index)
    map_request_key = ""
    _request_map_report()
    break
 )
 map_toolbar.add_child(map_group_picker)
 map_picker = OptionButton.new()
 map_picker.fit_to_longest_item = false
 map_picker.custom_minimum_size.x = 200
 map_picker.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 map_picker.add_item(L.text("map_rel"), 17)
 map_picker.add_item(L.text("map_value"), 2)
 map_picker.item_selected.connect(func(index): map_mode_id = map_picker.get_item_id(index); map_request_key = ""; _request_map_report())
 map_toolbar.add_child(map_picker)
 map_source_label = _label("", 13, MUTED, true)
 map_source_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 map_toolbar.add_child(map_source_label)
 map_toolbar.add_child(_button(L.text("reset_map"), func(): map_view.fit_map()))
 var layers_button := _button("Слои" if L.language == "ru" else "Layers", _open_map_layers)
 layers_button.name = "MapLayersButton"
 map_toolbar.add_child(layers_button)
 left.add_child(map_toolbar)
 map_toolbar.add_child(_button(L.text("country_short"), func(): _toggle_drawer(country_drawer)))
 map_toolbar.add_child(_button(L.text("news"), func(): _toggle_drawer(news_drawer)))
 map_view = WorldMap.new()
 map_view.relief_enabled = relief_enabled
 map_view.custom_minimum_size = Vector2(200, 200)
 map_view.size_flags_vertical = Control.SIZE_EXPAND_FILL
 map_view.reduced_motion = reduced_motion
 map_view.set("colorblind", colorblind)
 for layer in map_layers: map_view.set_layer(layer, map_layers[layer])
 map_view.country_selected.connect(_select_country)
 map_view.city_selected.connect(func(city): _map_briefing(int(city.country_id)))
 map_view.event_selected.connect(func(event): _map_briefing(int(event.country_id), event))
 map_view.route_selected.connect(_map_route_briefing)
 left.add_child(map_view)
 map_legend = HFlowContainer.new()
 map_legend.add_theme_constant_override("h_separation", 16)
 left.add_child(map_legend)
 news_drawer = NewsPanel.new()
 add_child(news_drawer)
 news_drawer.configure(self)
 news_drawer.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
 news_drawer.offset_left = 36
 news_drawer.offset_right = -36
 news_drawer.offset_top = 100
 news_drawer.offset_bottom = -42
 news_drawer.visible = false
 country_drawer = PanelContainer.new()
 var sidebar := country_drawer
 sidebar.custom_minimum_size.x = 352
 sidebar.add_theme_stylebox_override("panel", _style(Color("203e4d"), 6))
 add_child(sidebar)
 sidebar.set_anchors_and_offsets_preset(Control.PRESET_RIGHT_WIDE)
 sidebar.offset_left = -350
 sidebar.offset_right = -12
 sidebar.offset_top = 104
 sidebar.offset_bottom = -40
 sidebar.visible = false
 var side_column := VBoxContainer.new()
 sidebar.add_child(side_column)
 side_column.add_child(_button(L.text("close"), func(): _toggle_drawer(country_drawer)))
 country_picker = OptionButton.new()
 country_picker.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 for i in range(80):
  country_picker.add_item(L.country(i), i)
 country_picker.item_selected.connect(_select_country)
 side_column.add_child(country_picker)
 var side_scroll := ScrollContainer.new()
 side_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
 side_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
 side_column.add_child(side_scroll)
 var content := VBoxContainer.new()
 content.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 side_scroll.add_child(content)
 country_label = _label(L.text("select"), 24, Color("eddaa8"), true)
 content.add_child(country_label)
 facts_label = _label("", 15, PAPER, true)
 content.add_child(facts_label)
 content.add_child(HSeparator.new())
 map_details_box = VBoxContainer.new()
 content.add_child(map_details_box)
 policies_box = VBoxContainer.new()
 content.add_child(policies_box)
 crisis_box = VBoxContainer.new()
 content.add_child(crisis_box)
 crisis_actions = HBoxContainer.new()
 side_column.add_child(crisis_actions)
 side_column.add_child(_button(L.text("advisor"), _advisor_dialog))
 side_column.add_child(_button(L.text("country_report"), func(): Reports.show_report(self, "country")))
 status_label = _label(L.text("connect"), 14, MUTED, true)
 ui.add_child(status_label)
 _render_state()
 if not state.is_empty():
  _set_status(L.text("ready"))
 _update_guide()
 _play_music()
 if not game_visible:
  _show_start_menu()

func _change_language() -> void:
 L.language = "ru" if L.language == "en" else "en"
 dialogue_generation += 1
 dialogue_pending = false
 dialogue_result.clear()
 model_revision = -1
 map_request_key = ""
 _save_preferences()
 if is_instance_valid(popup):
  popup.queue_free()
 _build_ui()

func _command(command: String, args: Dictionary = {}, after: Callable = Callable(), advisory: bool = false) -> void:
 if backend_url.is_empty() or (busy and not advisory):
  return
 if not advisory:
  busy = true
  end_button.disabled = true
  _set_status(L.text("working"))
 request_counter += 1
 var request := HTTPRequest.new()
 # AI settings allow 300s; the core shares a 1.5x deadline across retries.
 # The local transport must outlast that deadline and return the final state.
 var model_request := command in ["advisor", "crisis_dialogue", "load", "gamemaster_generate"] or (command == "new_game" and (int(args.get("level", 1)) == 5 or bool(args.get("gamemaster_enabled", false)))) or (command in ["end_turn", "crisis_choice"] and (int(state.get("level", 1)) == 5 or bool(state.get("gamemaster", {}).get("enabled", false))))
 request.timeout = 155.0 if command == "settings_test" else (540.0 if model_request else 30.0)
 request.use_threads = true
 add_child(request)
 var id := str(request_counter)
 var language_at_request := L.language
 var settings_at_request := settings_generation
 var revision_at_request := revision
 request.request_completed.connect(func(result, code, _headers, body):
  request.queue_free()
  if command == "multiplayer_poll": network_poll_pending = false
  if not advisory:
   busy = false
  if advisory and settings_at_request != settings_generation:
   if after.is_valid() and language_at_request == L.language:
    after.call({"ok": false, "error": {"message": "AI settings changed; retry the request.", "message_ru": "Настройки ИИ изменились; повторите запрос."}})
   return
  var response = JSON.parse_string(body.get_string_from_utf8()) if result == HTTPRequest.RESULT_SUCCESS else null
  if code != 200 or not response is Dictionary:
   _set_status(L.text("connection_error"))
   _update_end_button()
   if smoke_test: get_tree().quit(1)
   if after.is_valid(): after.call({"ok": false, "error": {"message": L.text("connection_error"), "message_ru": L.text("connection_error")}})
   return
  if advisory and (int(response.get("revision", -1)) < revision or (revision_at_request != revision and not response.get("ok", false))):
   if after.is_valid() and language_at_request == L.language: after.call(response)
   return
  if int(response.get("revision", -1)) >= revision and response.get("multiplayer") is Dictionary:
   _receive_network(response.multiplayer)
  elif int(response.get("revision", -1)) >= revision and response.get("state") is Dictionary and response.state.get("multiplayer") is Dictionary:
   _receive_network(response.state.multiplayer)
  if not advisory and int(response.get("revision", -1)) >= revision:
   revision = int(response.revision)
   if response.has("state"):
    state = response.state if response.state is Dictionary else {}
   if _crisis_identity() != dialogue_identity:
    dialogue_generation += 1
    dialogue_pending = false
    dialogue_result.clear()
   _render_state()
  elif advisory and response.get("ok", false) and int(response.get("revision", -1)) >= revision and response.has("state"):
   var changed := int(response.revision) > revision
   revision = int(response.revision)
   state = response.state if response.state is Dictionary else {}
   if changed:
    dialogue_generation += 1
    dialogue_pending = false
    dialogue_result.clear()
    _render_state()
   else:
    _update_guide()
  if not response.get("ok", false):
   var error: Dictionary = response.get("error", {})
   _set_status(str(error.get("message_ru" if L.language == "ru" else "message", "Command failed")))
   if smoke_test:
    push_error(command + ": " + JSON.stringify(error))
    get_tree().quit(1)
  else:
   _set_status(L.text("saved") if command == "save" else _ready_status())
   # Campaign entry is independent of the language used to send the request.
   # Language-specific panel callbacks below may legitimately be discarded.
   if not advisory and command in ["new_game", "load", "import_game", "tutorial_start"] and int(response.get("revision", -1)) == revision and not state.is_empty():
    _show_game()
   _advance_guide(command, response)
   if command == "tutorial_end" and state.is_empty():
    guide_enabled = false
    if is_instance_valid(guide_panel): guide_panel.hide()
    _show_start_menu()
  if after.is_valid() and language_at_request == L.language:
   after.call(response)
  if smoke_test and not advisory and response.get("ok", false):
   _smoke_next(command)
  elif not screenshot_path.is_empty() and not smoke_test and command == "new_game":
   _capture.call_deferred()
 )
 var payload := {"id": id, "command": command, "args": args, "expected_revision": revision}
 var error := request.request(backend_url + "/command", ["Content-Type: application/json", "Authorization: Bearer " + token], HTTPClient.METHOD_POST, JSON.stringify(payload))
 if error != OK:
  request.queue_free()
  if command == "multiplayer_poll": network_poll_pending = false
  if not advisory: busy = false
  _set_status(L.text("connection_error"))
  _update_end_button()
  if after.is_valid(): after.call({"ok": false, "error": {"message": L.text("connection_error"), "message_ru": L.text("connection_error")}})
  if smoke_test: get_tree().quit(1)

func _update_end_button() -> void:
 end_button.disabled = busy or state.is_empty() or state.get("crisis", {}).get("active", false) or state.get("ended", false) or not _can_act() or network_state.get("duel") is Dictionary
 end_button.text = ("Передать ход" if L.language == "ru" else "Pass turn") if network_state.get("mode", "") == "hotseat" and network_state.get("ready", []).is_empty() else L.text("end")

func _can_act() -> bool:
 return not network_state.get("active", false) or bool(network_state.get("can_act", false))

func _receive_network(data: Dictionary) -> void:
 var changed := JSON.stringify(network_state) != JSON.stringify(data)
 network_state = data
 if changed:
  network_changed.emit(network_state)
  _render_state.call_deferred()

func _poll_multiplayer() -> void:
 if not network_state.get("active", false) or network_poll_pending or busy: return
 network_poll_pending = true
 _command("multiplayer_poll", {}, func(_result): network_poll_pending = false, true)

func _select_country(country_id: int) -> void:
 _show_drawer(country_drawer)
 _command("select_country", {"country_id": country_id})

func _open_ai_settings() -> void:
 ai_settings.open(self, _settings_request, L.language)

func _settings_request(command: String, args: Dictionary, callback: Callable) -> void:
 _command(command, args, func(response):
  if command == "settings_apply" and response.get("ok", false):
   settings_generation += 1
   dialogue_generation += 1
   dialogue_pending = false
   model_revision = -1
   dialogue_identity = ""
   dialogue_result.clear()
   _render_state()
  callback.call(response)
  if smoke_test and smoke_phase == 17 and command == "settings_get" and response.get("ok", false):
   _finish_smoke_settings.call_deferred()
 , true)

func _render_state() -> void:
 if game_visible and not state.is_empty() and (bool(state.get("crisis", {}).get("active", false)) or network_state.get("duel") is Dictionary) and is_instance_valid(country_drawer):
  _show_drawer(country_drawer)
 if state.is_empty():
  end_button.disabled = true
  guide_enabled = false
  map_request_key = ""
  map_report.clear()
  if game_visible: _show_start_menu()
  return
 if is_instance_valid(sound_signals): sound_signals.observe(state, sfx_enabled, volume, smoke_test)
 var current_year := int(state.year)
 year_label.text = str(current_year)
 if shown_year > 0 and shown_year != current_year and not reduced_motion:
  year_label.modulate = Color("a4d7cb")
  create_tween().tween_property(year_label, "modulate", Color.WHITE, 0.8)
 shown_year = current_year
 var scores: Array = state.scores
 score_label.text = "%s  %s  /  %s  %s\n%s: %s ±%s" % [L.country(0), int(scores[0]), L.country(1), int(scores[1]), L.text("tension"), int(state.tension), int(state.get("tension_error", 34))]
 var selected := int(state.get("selected_country", -1)) if state.get("selected_country") != null else -1
 map_view.update_world(state.countries, selected)
 map_view.apply_map_state(state.get("map_scene", {}))
 _request_map_report.call_deferred()
 if selected >= 0:
  country_picker.select(selected)
 var selection = state.get("selection")
 _clear(policies_box)
 if selection is Dictionary:
  country_label.text = L.country(int(selection.id))
  facts_label.text = "%s: %s\n%s: %s\n%s: %s" % [L.text("relations"), int(selection.standing), L.text("outgoing"), int(selection.our_opinion), L.text("prestige"), floori(float(selection.prestige) / 8.0)]
  if int(selection.id) >= 2:
   policies_box.add_child(_label(L.text("policies"), 17, MUTED))
   for policy in selection.get("policies", []):
    var action := int(policy.action)
    var button := _button(L.policy(action) + "\n" + L.step(action, int(policy.old)), _policy_dialog.bind(policy))
    button.alignment = HORIZONTAL_ALIGNMENT_LEFT
    button.add_theme_font_size_override("font_size", 14)
    button.disabled = busy or bool(state.crisis.active) or bool(state.ended) or not _can_act() or network_state.get("duel") is Dictionary
    policies_box.add_child(button)
  else:
   policies_box.add_child(_label(L.text("superpower"), 15, MUTED, true))
 else:
  country_label.text = L.text("select")
  facts_label.text = ""
 news_drawer.update_news(state, busy, network_state)
 _render_crisis()
 MapPanel.render_details(self, map_details_box)
 policies_box.visible = not bool(state.crisis.active) and not network_state.get("duel") is Dictionary
 if state.get("tutorial") is Dictionary:
  guide_enabled = state.tutorial.get("active", false)
  guide_step = int(state.tutorial.get("step", 0))
  _update_guide()
 _update_end_button()
 if state.ended:
  _set_status(L.text("complete"))
  var ending_key := JSON.stringify([state.year, state.scores, state.get("nuclear", false)])
  if ending_key != shown_ending and not smoke_test:
   shown_ending = ending_key
   _endgame_dialog.call_deferred()
 elif state.crisis.active and not smoke_test and _crisis_identity() != dialogue_identity:
  _crisis_briefing.call_deferred()
 else:
  shown_ending = ""

func _set_status(message: String) -> void:
 if is_instance_valid(status_label): status_label.text = message
 if is_instance_valid(menu_status_label): menu_status_label.text = message

func _ready_status() -> String:
 if state.is_empty(): return L.text("ready")
 if dialogue_pending: return L.text("thinking")
 var side_label := "Играем за: " if L.language == "ru" else "Playing as: "
 var result := side_label + L.country(int(state.side))
 if network_state.get("active", false):
  result = side_label + L.country(int(network_state.get("local_side", state.side)))
  if network_state.get("status", "") == "disconnected":
   return result + (" — связь потеряна, подключаемся заново" if L.language == "ru" else " — disconnected, reconnecting")
  if network_state.get("duel") is Dictionary:
   return result + (" — решение принимает " if L.language == "ru" else " — decision: ") + L.country(int(network_state.duel.decider))
  if not network_state.get("can_act", false):
   return result + (" — ожидание второго игрока" if L.language == "ru" else " — waiting for the other player")
  return result
 if state.get("tutorial", {}).get("active", false):
  result = L.text("training_status")
 if int(state.get("level", 1)) == 5:
  var opponent: String = str(state.get("opponent", "heuristic_not_configured"))
  result += "   ·   " + ("Соперник: " if L.language == "ru" else "Opponent: ") + L.text("opponent_" + opponent)
 return result

func _crisis_identity() -> String:
 if network_state.get("duel") is Dictionary:
  var duel: Dictionary = network_state.duel
  return JSON.stringify([state.get("year"), duel.get("phase"), duel.get("level"), duel.get("decider"), duel.get("actor"), duel.get("victim"), duel.get("action"), duel.get("old"), duel.get("new"), duel.get("summitBy"), L.language])
 if state.is_empty() or not state.get("crisis", {}).get("active", false):
  return ""
 var crisis: Dictionary = state.crisis
 return JSON.stringify([state.year, crisis.level, crisis.get("speaker"), crisis.get("outcome"), crisis.headline, crisis.reaction, L.language])

func _request_map_report() -> void:
 if state.is_empty(): return
 var source := int(state.get("selected_country", state.side)) if state.get("selected_country") != null else int(state.side)
 var key := JSON.stringify([revision, map_mode_id, source, L.language])
 if key == map_request_key: return
 map_request_key = key
 _command("report", {"kind": "map", "mode": map_mode_id, "country_id": source}, func(response):
  if key != map_request_key or int(response.get("revision", -1)) != revision: return
  if not response.get("ok", false):
   # A new game can remove access to the old difficulty's map mode.
   if map_mode_id != 17:
    map_mode_id = 17
    map_request_key = ""
    _request_map_report.call_deferred()
   return
  map_report = response.get("report", {})
  map_view.apply_report(map_report)
  _populate_map_modes()
  var perspective = map_report.get("source_country")
  map_source_label.text = L.text("map_perspective") + ": " + L.country(int(perspective)) if perspective != null else ("Общий показатель" if L.language == "ru" else "Global indicator")
  _clear(map_legend)
  for item in map_report.get("scale", {}).get("legend", []):
   var chip := HBoxContainer.new()
   var swatch := ColorRect.new()
   swatch.color = map_view.presentation_color(str(item.get("color", "#babba4"))) if map_view.has_method("presentation_color") else Color(str(item.get("color", "#babba4")))
   swatch.custom_minimum_size = Vector2(12, 12)
   swatch.size_flags_vertical = Control.SIZE_SHRINK_CENTER
   chip.add_child(swatch)
   chip.add_child(_label(Reports.wording(item, "label"), 12, MUTED))
   map_legend.add_child(chip)
  map_report_ready.emit(map_mode_id)
 , true)

func _news_text(item: Dictionary) -> String:
 if L.language == "ru" and item.has("text_ru"):
  return item.text_ru
 if L.language == "ru" and int(item.action) in range(9) and item.actor != item.target:
  return "%s · %s\n%s: %s → %s" % [L.country(int(item.actor)), L.country(int(item.target)), L.policy(int(item.action)), L.step(int(item.action), int(item.old)), L.step(int(item.action), int(item.new))]
 return str(item.text)

func _render_crisis() -> void:
 _clear(crisis_box)
 _clear(crisis_actions)
 crisis_actions.visible = false
 if network_state.get("duel") is Dictionary:
  _render_duel(network_state.duel)
  return
 var crisis: Dictionary = state.get("crisis", {})
 if not crisis.get("active", false):
  return
 crisis_box.add_child(HSeparator.new())
 crisis_box.add_child(_label(L.text("crisis"), 22, Color("e6ac94")))
 crisis_box.add_child(_label("%s: %s" % [L.text("rung"), int(crisis.level)], 18))
 crisis_box.add_child(_label(str(crisis.get("headline_ru" if L.language == "ru" else "headline", "")), 14, PAPER, true))
 var reaction := str(dialogue_result.get("reaction", crisis.get("reaction_ru" if L.language == "ru" else "reaction", "")))
 crisis_box.add_child(_label(reaction, 16, Color("eddaa8"), true))
 var risk := str(crisis.get("prestige_at_risk", ""))
 if not risk.is_empty():
  crisis_box.add_child(_label(L.text("risk") + ": " + risk, 16, Color("e6ac94"), true))
 crisis_box.add_child(_label(L.text("crisis_note"), 13, MUTED, true))
 for choice in crisis.get("choices", []):
  var button := _button(L.text(choice), func(): _command("crisis_choice", {"choice": choice}))
  button.name = "CrisisChoice_" + str(choice)
  button.disabled = busy
  crisis_actions.add_child(_expand(button))
 crisis_actions.visible = crisis_actions.get_child_count() > 0
 if dialogue_pending:
  crisis_box.add_child(_label(L.text("thinking"), 15, Color("eddaa8"), true))
 if not dialogue_result.is_empty():
  var advice: Array = dialogue_result.get("advice", [])
  var names := AdvisorPanel.names_for_side(int(state.side), L.language)
  for index in range(advice.size()):
   crisis_box.add_child(HSeparator.new())
   if index < names.size(): crisis_box.add_child(_label(str(names[index]), 15, Color("83bad5"), true))
   crisis_box.add_child(_label(str(advice[index]), 14, PAPER, true))
  crisis_box.add_child(_label(str(dialogue_result.get("status", "")), 12, MUTED, true))
 var brief_button := _button(L.text("briefing"), _crisis_briefing)
 brief_button.disabled = dialogue_pending
 crisis_box.add_child(brief_button)

func _render_duel(duel: Dictionary) -> void:
 var ru := L.language == "ru"
 var local_side := int(network_state.get("local_side", 0))
 var decider := int(duel.get("decider", 0))
 crisis_box.add_child(_label(L.text("crisis"), 22, Color("e6ac94")))
 crisis_box.add_child(_label("%s: %s" % [L.text("rung"), int(duel.get("level", 9))], 18))
 var headline := str(duel.get("headline", ""))
 if ru:
  headline = "%s: %s — %s\n%s → %s" % [L.country(int(duel.get("actor", 0))), L.country(int(duel.get("victim", 2))), L.policy(int(duel.get("action", 0))), L.step(int(duel.get("action", 0)), int(duel.get("old", 0))), L.step(int(duel.get("action", 0)), int(duel.get("new", 0)))]
 crisis_box.add_child(_label(headline, 16, PAPER, true))
 crisis_box.add_child(_label(("Решение принимает: " if ru else "Decision belongs to: ") + L.country(decider), 16, Color("eddaa8"), true))
 var phase := str(duel.get("phase", ""))
 if phase == "summit":
  crisis_box.add_child(_label("Предложена встреча: согласие завершит кризис, отказ повлияет на доверие." if ru else "A summit is proposed: accepting ends the crisis; refusing affects credibility.", 15, PAPER, true))
 else:
  crisis_box.add_child(_label(L.text("crisis_note"), 14, MUTED, true))
 var risk := int(duel.get("usaRisk" if local_side == 0 else "ussrRisk", 0))
 crisis_box.add_child(_label(("Важность для вашей стороны: " if ru else "Importance to your side: ") + str(risk) + "/7", 14, MUTED, true))
 if duel.has("local_prestige_at_risk"):
  crisis_box.add_child(_label(L.text("risk") + ": " + str(duel.local_prestige_at_risk), 16, Color("e6ac94"), true))
 var captions := {"accept": ["Let it stand", "Не оспаривать"], "contest": ["Contest", "Оспорить"], "back_down": ["Back down", "Уступить"], "tough": ["Stand firm", "Настаивать"], "summit": ["Summit", "Встреча"], "yes": ["Accept", "Согласиться"], "no": ["Decline", "Отказаться"]}
 for choice in duel.get("choices", []):
  var caption: Array = captions.get(str(choice), [str(choice), str(choice)])
  var button := _button(str(caption[1 if ru else 0]), func(): _command("crisis_choice", {"choice": str(choice)}))
  button.name = "CrisisChoice_" + str(choice)
  button.disabled = busy or local_side != decider or network_state.get("status", "") != "playing"
  button.add_theme_font_size_override("font_size", 14)
  crisis_actions.add_child(_expand(button))
 crisis_actions.visible = crisis_actions.get_child_count() > 0
 var names := AdvisorPanel.names_for_side(local_side, L.language)
 var advice: Array = dialogue_result.get("advice", duel.get("advice_ru" if ru else "advice", []))
 for index in range(advice.size()):
  crisis_box.add_child(HSeparator.new())
  if index < names.size(): crisis_box.add_child(_label(str(names[index]), 15, Color("83bad5"), true))
  crisis_box.add_child(_label(str(advice[index]), 14, PAPER, true))
 if dialogue_pending:
  crisis_box.add_child(_label(L.text("thinking"), 15, Color("eddaa8"), true))
 elif not dialogue_result.is_empty():
  crisis_box.add_child(_label(str(dialogue_result.get("status", "")), 12, MUTED, true))
 var briefing := _button(L.text("briefing"), _crisis_briefing)
 briefing.disabled = dialogue_pending
 crisis_box.add_child(briefing)

func _crisis_briefing() -> void:
 if state.is_empty() or (not state.crisis.active and not network_state.get("duel") is Dictionary) or model_revision == revision:
  return
 model_revision = revision
 dialogue_identity = _crisis_identity()
 dialogue_generation += 1
 var generation := dialogue_generation
 var identity := dialogue_identity
 dialogue_pending = true
 _render_crisis()
 _set_status(L.text("thinking"))
 _command("crisis_dialogue", {"language": L.language}, func(response):
  if generation != dialogue_generation or identity != _crisis_identity(): return
  dialogue_pending = false
  if response.get("ok", false) and int(response.revision) == revision:
   dialogue_result = response.get("dialogue", {})
   _render_crisis()
   crisis_briefing_ready.emit(dialogue_result)
  else:
   model_revision = -1
   dialogue_identity = ""
   _render_crisis()
 , true)

func _dialog(title_text: String, dialog_size: Vector2i = Vector2i(660, 560)) -> VBoxContainer:
 if is_instance_valid(popup):
  popup.hide()
  popup.exclusive = false
  popup.queue_free()
 popup = Window.new()
 popup.title = title_text
 popup.size = Vector2i(mini(dialog_size.x, int(get_viewport_rect().size.x) - 32), mini(dialog_size.y, int(get_viewport_rect().size.y) - 32))
 popup.min_size = Vector2i(480, 360)
 popup.transient = true
 popup.exclusive = true
 popup.theme = theme
 var created_window := popup
 popup.close_requested.connect(func(): created_window.hide(); created_window.exclusive = false; created_window.queue_free())
 add_child(popup)
 var background := ColorRect.new()
 background.color = Color("1c3848")
 background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
 popup.add_child(background)
 var margin := MarginContainer.new()
 margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
 for edge in ["left", "right", "top", "bottom"]:
  margin.add_theme_constant_override("margin_" + edge, 24)
 popup.add_child(margin)
 var column := VBoxContainer.new()
 column.add_theme_constant_override("separation", 14)
 margin.add_child(column)
 column.add_child(_label(title_text, 25, Color("eddaa8")))
 if not reduced_motion:
  margin.modulate.a = 0.0
  create_tween().tween_property(margin, "modulate:a", 1.0, 0.18)
 popup.popup_centered()
 return column

func _policy_dialog(policy: Dictionary) -> void:
 if busy or state.get("selection") == null:
  return
 var action := int(policy.action)
 var target := int(state.selection.id)
 var column := _dialog(L.policy(action), Vector2i(660, 650))
 var owning_popup := popup
 column.add_child(_label(L.country(target), 20))
 column.add_child(_label("%s: %s" % [L.text("held"), L.step(action, int(policy.old))], 16, MUTED))
 # JSON numbers arrive as floats. Array.has distinguishes 1 from 1.0 even
 # though scalar equality does not; normalize before checking legal choices.
 var steps: Array = policy.steps.map(func(step): return int(step))
 var choices := ButtonGroup.new()
 var value := {"selected": int(policy.old)}
 for i in range(6):
  var radio := CheckBox.new()
  radio.text = L.step(action, i)
  radio.button_group = choices
  radio.set_meta("policy_step", i)
  radio.button_pressed = i == int(policy.old)
  radio.disabled = not i in steps
  radio.toggled.connect(func(enabled): if enabled: value.selected = i)
  column.add_child(radio)
 if policy.get("available") != null:
  column.add_child(_label("%s: %s" % [L.text("available"), int(policy.available)], 15, MUTED))
 if not str(policy.get("reason", "")).is_empty():
  column.add_child(_label(str(policy.get("reason_ru" if L.language == "ru" else "reason", "")), 14, MUTED, true))
 column.add_child(_expand(Control.new()))
 var apply_button := _button(L.text("apply"), func():
  owning_popup.queue_free()
  _command("policy", {"target": target, "action": action, "value": int(value.selected)})
 )
 apply_button.name = "ApplyPolicyButton"
 column.add_child(apply_button)

func _new_game_dialog() -> void:
 if busy:
  return
 var column := _dialog(L.text("new"), Vector2i(680, 560))
 var owning_popup := popup
 column.add_child(_label(L.text("side")))
 var side := OptionButton.new()
 side.add_item(L.country(0))
 side.add_item(L.country(1))
 column.add_child(side)
 column.add_child(_label(L.text("difficulty")))
 var difficulty := OptionButton.new()
 for key in ["beginner", "intermediate", "expert", "multipolar", "adaptive"]:
  difficulty.add_item(L.text(key))
 difficulty.select(2)
 column.add_child(difficulty)
 column.add_child(_label(L.text("guide_live"), 14, MUTED, true))
 var gamemaster := CheckBox.new()
 gamemaster.text = L.text("gamemaster_enabled")
 gamemaster.button_pressed = false
 column.add_child(gamemaster)
 column.add_child(_label(L.text("gamemaster_cost"), 14, MUTED, true))
 var start_button := _button(L.text("start"), func():
  var args := {"language": L.language, "gamemaster_enabled": gamemaster.button_pressed, "side": side.selected, "level": difficulty.selected + 1, "seed": 1982 if smoke_test else int(Time.get_unix_time_from_system())}
  owning_popup.queue_free()
  guide_step = 0
  _command("new_game", args, func(response):
   if response.get("ok", false): _show_game()
  )
 )
 start_button.name = "StartCampaignButton"
 column.add_child(start_button)

func _intelligence_dialog() -> void:
 if state.is_empty() or busy or state.crisis.active or state.ended:
  return
 var column := _dialog(L.text("intelligence"), Vector2i(620, 440))
 var owning_popup := popup
 column.add_child(_label(L.text("intelligence_help"), 17, PAPER, true))
 column.add_child(_label("%s: %s ±%s" % [L.text("tension"), int(state.tension), int(state.get("tension_error", 34))], 18, Color("eddaa8")))
 var choice := OptionButton.new()
 for i in range(6):
  choice.add_item(("Уровень " if L.language == "ru" else "Level ") + str(i))
 choice.select(int(state.get("intelligence", 0)))
 column.add_child(choice)
 column.add_child(_button(L.text("apply"), func():
  var level := choice.selected
  owning_popup.queue_free()
  _command("intelligence", {"level": level})
 ))

func _endgame_dialog() -> void:
 var column := _dialog(L.text("complete"), Vector2i(700, 470))
 if state.get("nuclear", false):
  column.add_child(_label(L.text("nuclear_end"), 22, Color("e6ac94"), true))
 else:
  var scores: Array = state.scores
  var winner := L.country(0 if float(scores[0]) > float(scores[1]) else 1)
  column.add_child(_label(L.text("draw") if scores[0] == scores[1] else L.text("winner") + winner, 22, Color("eddaa8"), true))
  column.add_child(_label("%s\n%s: %s\n%s: %s" % [L.text("score"), L.country(0), int(scores[0]), L.country(1), int(scores[1])], 20, PAPER, true))
 column.add_child(_label(L.text("end_note"), 17, MUTED, true))

func _advisor_dialog() -> void:
 if state.is_empty():
  return
 advisor_panel.open(self)

func _toggle_guide() -> void:
 _command("tutorial_start", {}, func(response):
  if response.get("ok", false): _show_game()
 )

func _update_guide() -> void:
 if not is_instance_valid(guide_box): return
 guide_box.visible = guide_enabled
 if is_instance_valid(guide_panel): guide_panel.visible = guide_enabled and game_visible
 map_view.custom_minimum_size.y = 200
 if state.get("tutorial", {}).get("active", false):
  guide_step = int(state.tutorial.get("step", 0))
 guide_label.text = L.text("lesson_" + str(guide_step)) if guide_step < 6 else L.text("lesson_done")
 var tutorial: Dictionary = state.get("tutorial", {})
 var lesson: String = str(tutorial.get("lesson_ru" if L.language == "ru" else "lesson_en", ""))
 if not lesson.is_empty(): guide_label.text = lesson
 guide_scroll.custom_minimum_size.y = 130 if guide_step >= 6 else 100
 if guide_step in [0, 2] and tutorial.get("target_country") != null:
  guide_label.text += "\n" + L.country(int(tutorial.target_country))
  if guide_step == 2 and tutorial.get("value") != null:
   guide_label.text += " · " + L.policy(int(tutorial.get("action", 2))) + ": " + L.step(int(tutorial.get("action", 2)), int(tutorial.value))
 guide_button.visible = guide_step in [1, 6]

func _advance_guide(command: String, response: Dictionary) -> void:
 # Progress is acknowledged by the rules service, never by a button animation.
 if command.is_empty() or not response.get("ok", false): return
 _update_guide()

func _credits() -> void:
 var column := _dialog(L.text("credits"), Vector2i(720, 590))
 var scroll := ScrollContainer.new()
 scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
 scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
 var content := VBoxContainer.new()
 content.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 content.add_child(_label(L.text("credits_text"), 17, PAPER, true))
 var tracks = JSON.parse_string(FileAccess.get_file_as_string("res://assets/music/licensed_tracks.json"))
 for track in tracks:
  content.add_child(_label(str(track.title) + " — " + str(track.artist) + " (CC0)", 15, PAPER, true))
  var link := LinkButton.new()
  link.text = str(track.source_url)
  link.pressed.connect(func(): OS.shell_open(track.source_url))
  content.add_child(link)
 scroll.add_child(content)
 column.add_child(scroll)

func _play_music() -> void:
 if not is_instance_valid(audio_player): return
 if not music_enabled:
  audio_player.stop()
  return
 if audio_player.playing: return
 audio_player.stream = load("res://assets/music/" + track_names[track_index])
 audio_player.play()

func _next_track() -> void:
 track_index = (track_index + 1) % track_names.size()
 audio_player.stop()
 _play_music()

func _smoke_next(command: String) -> void:
 if smoke_phase == 0 and command == "new_game":
  # The campaign becomes visible only after the successful response. Let its
  # containers settle before measuring, including in headless smoke runs.
  await get_tree().process_frame
  await get_tree().process_frame
  await _snapshot_screen("game")
  if map_view.size.x * map_view.size.y < get_viewport_rect().size.x * get_viewport_rect().size.y * 0.70:
   push_error("Map does not occupy 70 percent of the viewport")
   get_tree().quit(1)
   return
  smoke_phase = 1
  map_view.country_selected.emit(4)
 elif smoke_phase == 1 and command == "select_country":
  var found := false
  for policy in state.selection.policies:
   for value in policy.steps:
    if value != policy.old:
     smoke_policy = {"target": 4, "action": int(policy.action), "value": int(value)}
     found = true
     break
   if found: break
  if not found:
   push_error("No smoke policy is legal")
   get_tree().quit(1)
   return
  smoke_phase = 2
  _command.call_deferred("policy", smoke_policy)
 elif smoke_phase == 2 and command == "policy":
  smoke_phase = 3
  _command.call_deferred("end_turn")
 elif smoke_phase == 3:
  if state.crisis.active:
   await _snapshot_screen("crisis")
   var choices: Array = state.crisis.choices
   _command.call_deferred("crisis_choice", {"choice": "loose" if "loose" in choices else choices[0]})
  else:
   if not smoke_challenged:
    smoke_challenged = true
    for item in state.news:
     if item.questionable:
      _command.call_deferred("question", {"news_id": int(item.id)})
      return
   smoke_phase = 4
   _command.call_deferred("save")
 elif smoke_phase == 4 and command == "save":
  smoke_phase = 5
  _command.call_deferred("load")
 elif smoke_phase == 5 and command == "load":
  smoke_phase = 6
  smoke_campaign = state.duplicate(true)
  _command.call_deferred("tutorial_start")
 elif smoke_phase == 6 and command == "tutorial_start":
  await _snapshot_screen("tutorial")
  smoke_phase = 7
  _command.call_deferred("select_country", {"country_id": int(state.tutorial.target_country)})
 elif smoke_phase == 7:
  smoke_phase = 8
  _command.call_deferred("tutorial_ack")
 elif smoke_phase == 8:
  for policy in state.selection.policies:
   if int(policy.action) != 2: continue
   _policy_dialog(policy)
   var legal: Array = policy.steps.map(func(step): return int(step))
   for radio in popup.find_children("*", "CheckBox", true, false):
    var step := int(radio.get_meta("policy_step"))
    if radio.disabled == (step in legal):
     push_error("Policy control does not match authoritative legal steps")
     get_tree().quit(1)
     return
    if step == int(state.tutorial.value):
     radio.button_pressed = true
   await _snapshot_screen("policy")
   smoke_phase = 9
   popup.find_child("ApplyPolicyButton", true, false).pressed.emit()
   break
 elif smoke_phase == 9:
  smoke_phase = 10
  _command.call_deferred("end_turn")
 elif smoke_phase == 10:
  if state.crisis.active:
   var choices: Array = state.crisis.choices
   _command.call_deferred("crisis_choice", {"choice": "loose" if "loose" in choices else choices[0]})
  else:
   smoke_phase = 11
   _command.call_deferred("select_country", {"country_id": int(state.tutorial.target_country)})
 elif smoke_phase == 11:
  _advisor_dialog()
  smoke_phase = 12
  advisor_answered.connect(_after_smoke_advice, CONNECT_ONE_SHOT)
  popup.find_child("AskAdvisorButton", true, false).pressed.emit()
 elif smoke_phase == 21 and command == "tutorial_ack":
  if int(state.tutorial.step) != 7:
   push_error("Crisis lesson acknowledgement failed")
   get_tree().quit(1)
   return
  smoke_phase = 22
  _smoke_crisis_choice.call_deferred("tough")
 elif smoke_phase == 22 and command == "crisis_choice":
  if int(state.tutorial.step) != 8 or int(state.crisis.level) != 7:
   push_error("Training escalation did not reach the expected actual rung")
   get_tree().quit(1)
   return
  await _snapshot_screen("tutorial-escalation")
  smoke_phase = 23
  _smoke_crisis_choice.call_deferred("loose")
 elif smoke_phase == 23 and command == "crisis_choice":
  var practice: Dictionary = state.tutorial.crisis_practice
  if int(state.tutorial.step) != 9 or practice.policy_current != practice.policy_before or int(practice.observed_loss) <= 0:
   push_error("Training concession did not enact a policy reversal and prestige loss")
   get_tree().quit(1)
   return
  await _snapshot_screen("tutorial-concession")
  smoke_phase = 24
  _smoke_crisis_choice.call_deferred("continue")
 elif smoke_phase == 24 and command == "crisis_choice":
  if not state.tutorial.get("finished", false) or state.crisis.active:
   push_error("Training crisis did not finish")
   get_tree().quit(1)
   return
  smoke_phase = 12
  _command.call_deferred("tutorial_end")
 elif smoke_phase == 12 and command == "tutorial_end":
  if state.year != smoke_campaign.year or state.scores != smoke_campaign.scores or state.news != smoke_campaign.news:
   push_error("Tutorial did not preserve campaign")
   get_tree().quit(1)
   return
  smoke_phase = 13
  L.language = "ru"
  _build_ui()
  _smoke_report("scores")

func _smoke_report(kind: String) -> void:
 Reports.show_report(self, kind, func(report):
  if report.get("kind", "") != kind:
   push_error("Wrong report displayed")
   get_tree().quit(1)
   return
  if kind in ["scores", "objectives"] and report.get("rows", []).is_empty():
   push_error("Empty report")
   get_tree().quit(1)
   return
  await _snapshot_screen(kind)
  if kind == "country":
   var tabs: TabContainer = popup.find_child("CountryReportTabs", true, false)
   var selector: OptionButton = popup.find_child("HistorySeries", true, false)
   if not is_instance_valid(tabs) or not is_instance_valid(selector) or selector.item_count < 2:
    push_error("Country history controls are missing")
    get_tree().quit(1)
    return
   tabs.current_tab = 1
   selector.select(1)
   selector.item_selected.emit(1)
   await _snapshot_screen("history")
   if tabs.get_tab_count() > 2:
    tabs.current_tab = 2
    await _snapshot_screen("profile")
  popup.queue_free()
  if kind == "scores":
   smoke_phase = 14
   _smoke_report.call_deferred("objectives")
  elif kind == "objectives":
   smoke_phase = 15
   _smoke_report.call_deferred("country")
  else:
   smoke_phase = 17
   _open_ai_settings.call_deferred()
 )

func _finish_smoke_settings() -> void:
 var key_control: LineEdit = ai_settings._controls.get("api_key")
 if not is_instance_valid(key_control) or not key_control.secret or not key_control.text.is_empty():
  push_error("Settings key field did not preserve masking")
  get_tree().quit(1)
  return
 await _snapshot_screen("settings")
 ai_settings.close()
 smoke_phase = 19
 _smoke_map_mode(2)

func _smoke_map_mode(mode: int) -> void:
 map_group_picker.select(0 if mode < 8 else 1 if mode <= 21 or mode >= 58 else 2)
 _populate_map_modes()
 var index := map_picker.get_item_index(mode)
 if index < 0 or map_picker.is_item_disabled(index):
  push_error("Map mode is unavailable")
  get_tree().quit(1)
  return
 map_report_ready.connect(_finish_smoke_map, CONNECT_ONE_SHOT)
 map_picker.select(index)
 map_picker.item_selected.emit(index)

func _finish_smoke_map(mode: int) -> void:
 if map_report.get("countries", []).size() != 80 or map_report.get("registry", []).size() != 60 or int(map_report.get("mode", -1)) != mode:
  push_error("Map report did not reach the visible mode")
  get_tree().quit(1)
  return
 if smoke_phase == 19 and mode == 2:
  await _snapshot_screen("map-prestige")
  smoke_phase = 20
  _smoke_map_mode.call_deferred(17)
 elif smoke_phase == 20 and mode == 17:
  smoke_phase = 18
  _capture.call_deferred()

func _after_smoke_advice(response: Dictionary) -> void:
 if not response.get("ok", false) or int(response.state.tutorial.step) != 6:
  push_error("Tutorial advisor completion failed; step=" + str(response.get("state", {}).get("tutorial", {}).get("step", -1)))
  get_tree().quit(1)
  return
 var displayed: TextEdit = popup.find_child("AdvisorAnswer", true, false)
 if displayed.text != response.advice.text or displayed.text.length() < 20:
  push_error("Advisor reply did not reach the visible conversation")
  get_tree().quit(1)
  return
 await _snapshot_screen("advisor")
 if advisor_panel.last_details.get("history", []).size() < 2:
  await advisor_panel.details_loaded
 if advisor_panel.last_details.get("history", []).size() < 2:
  push_error("Advisor transcript did not preserve the visible exchange")
  get_tree().quit(1)
  return
 advisor_panel.tabs.current_tab = 1
 await _snapshot_screen("advisor-conversation")
 advisor_panel.tabs.current_tab = 2
 await _snapshot_screen("advisor-record")
 popup.queue_free()
 smoke_phase = 21
 _smoke_crisis_start.call_deferred()

func _smoke_crisis_start() -> void:
 if not state.crisis.active or not guide_button.visible or guide_label.text.is_empty():
  push_error("Practice crisis did not reach the guide")
  get_tree().quit(1)
  return
 _crisis_briefing()
 var briefing: Dictionary = await crisis_briefing_ready
 if briefing.get("advice", []).size() != 4 or briefing.get("used_model", true) or briefing.get("status_code", "") != "training":
  push_error("Practice crisis did not show four clearly identified offline advisors")
  get_tree().quit(1)
  return
 await _snapshot_screen("tutorial-crisis")
 guide_button.pressed.emit()

func _smoke_crisis_choice(choice: String) -> void:
 var button: Button = crisis_actions.find_child("CrisisChoice_" + choice, true, false)
 if not is_instance_valid(button) or button.disabled:
  push_error("Required training crisis choice is not available")
  get_tree().quit(1)
  return
 button.pressed.emit()

func _snapshot_screen(suffix: String) -> void:
 if screenshot_path.is_empty() or DisplayServer.get_name() == "headless": return
 get_window().move_to_foreground()
 if not reduced_motion: await get_tree().create_timer(0.55).timeout
 await get_tree().process_frame
 await get_tree().process_frame
 await RenderingServer.frame_post_draw
 var output := get_viewport().get_texture().get_image()
 var result := output.save_png(screenshot_path.get_basename() + "-" + suffix + ".png")
 if result != OK:
  push_error("Could not capture " + suffix)

func _capture() -> void:
 await get_tree().process_frame
 await get_tree().process_frame
 if not screenshot_path.is_empty() and DisplayServer.get_name() != "headless":
  get_window().move_to_foreground()
  await RenderingServer.frame_post_draw
  var output := get_viewport().get_texture().get_image()
  var result := output.save_png(screenshot_path)
  if result != OK:
   push_error("Could not save screenshot")
   get_tree().quit(1)
   return
 if smoke_test:
  _smoke_desktop_workflows()

func _smoke_desktop_workflows() -> void:
 # Run through the same HTTP bridge in source and frozen builds, in the
 # launcher's disposable directory. This also checks Qt-free mail packaging.
 var directory := OS.get_environment("BOP_USER_DIR")
 if directory.is_empty():
  push_error("Desktop smoke requires an isolated directory")
  get_tree().quit(1)
  return
 var portable := directory.path_join("smoke-roundtrip.bopg")
 var steps := [
  ["save", {"slot": "smoke-named"}], ["save_list", {}],
  ["export_game", {"path": portable}], ["import_game", {"path": portable}],
  ["multiplayer_hotseat", {"side": 0, "level": 3, "seed": 1982}],
  ["end_turn", {}], ["save", {"slot": "smoke-hotseat"}], ["load", {"slot": "smoke-hotseat"}],
  ["multiplayer_leave", {}],
  ["multiplayer_host", {"bind": "127.0.0.1", "port": 0}], ["multiplayer_leave", {}],
  ["multiplayer_mail_create", {"directory": directory.path_join("mail"), "game_id": "smoke", "side": 0}],
  ["end_turn", {}], ["multiplayer_mail_submit", {}], ["multiplayer_leave", {}],
  ["save_delete", {"slot": "smoke-hotseat"}], ["save_delete", {"slot": "smoke-named"}]
 ]
 for step in steps:
  var completed := {"done": false, "response": {}}
  _command(str(step[0]), step[1], func(response): completed.response = response; completed.done = true)
  while not completed.done: await get_tree().process_frame
  var response: Dictionary = completed.response
  var valid := bool(response.get("ok", false))
  if step[0] == "save_list": valid = valid and response.get("saves", []).any(func(slot): return slot.slot == "smoke-named")
  elif step[0] == "load": valid = valid and network_state.get("mode", "") == "hotseat" and int(network_state.get("local_side", -1)) == 1
  elif step[0] == "multiplayer_host": valid = valid and int(network_state.get("port", 0)) > 0
  elif step[0] == "multiplayer_mail_create": valid = valid and network_state.get("mode", "") == "mail"
  if not valid:
   push_error("Desktop smoke failed: " + str(step[0]))
   get_tree().quit(1)
   return
 print("GODOT_SMOKE_OK: start menu, map modes, policy controls, crisis, year, named saves, portable files, hotseat resume, LAN host, mail submit, isolated tutorial, advisors, reports, AI settings, Russian UI")
 get_tree().quit(0)

func _show_drawer(drawer: Control) -> void:
 if not is_instance_valid(drawer): return
 if drawer == news_drawer and is_instance_valid(country_drawer): country_drawer.hide()
 drawer.show()
 if not reduced_motion:
  drawer.modulate.a = 0.0
  create_tween().tween_property(drawer, "modulate:a", 1.0, 0.16)

func _toggle_drawer(drawer: Control) -> void:
 if drawer.visible: drawer.hide()
 else:
  if drawer == country_drawer and is_instance_valid(news_drawer): news_drawer.hide()
  _show_drawer(drawer)

func _show_game() -> void:
 game_visible = true
 ui.show()
 if is_instance_valid(start_screen):
  start_screen.hide()
  start_screen.queue_free()
 if is_instance_valid(guide_panel): guide_panel.visible = guide_enabled
 if state.get("crisis", {}).get("active", false) or network_state.get("duel") is Dictionary:
  _show_drawer(country_drawer)

func _show_start_menu() -> void:
 game_visible = false
 if is_instance_valid(ui): ui.hide()
 if is_instance_valid(start_screen): start_screen.queue_free()
 if is_instance_valid(country_drawer): country_drawer.hide()
 if is_instance_valid(news_drawer): news_drawer.hide()
 if is_instance_valid(guide_panel): guide_panel.hide()
 start_screen = PanelContainer.new()
 start_screen.name = "StartMenu"
 start_screen.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
 start_screen.add_theme_stylebox_override("panel", _style(Color("152f40")))
 add_child(start_screen)
 var margin := MarginContainer.new()
 for edge in ["left", "right", "top", "bottom"]: margin.add_theme_constant_override("margin_" + edge, 42)
 start_screen.add_child(margin)
 var row := HBoxContainer.new()
 row.add_theme_constant_override("separation", 48)
 margin.add_child(row)
 var column := VBoxContainer.new()
 column.custom_minimum_size.x = 330
 column.add_theme_constant_override("separation", 9)
 row.add_child(column)
 column.add_child(_label(L.text("title"), 42, Color("eddaa8")))
 column.add_child(_label(L.text("subtitle"), 18, MUTED))
 column.add_child(HSeparator.new())
 var continue_button := Button.new()
 continue_button.text = L.text("continue")
 continue_button.pressed.connect(func():
  var slot := str(continue_button.get_meta("last_slot", ""))
  if slot.is_empty(): _show_game()
  else: _command("load", {"slot": slot}, func(result):
   if result.get("ok", false): _show_game()
  )
 )
 continue_button.name = "ContinueButton"
 continue_button.disabled = state.is_empty()
 column.add_child(continue_button)
 if state.is_empty() and not backend_url.is_empty():
  _command("save_list", {}, func(response):
   if not is_instance_valid(continue_button): return
   var last: String = response.last_slot if response.get("ok", false) and response.get("last_slot") is String else ""
   continue_button.disabled = last.is_empty()
   if not last.is_empty():
    continue_button.set_meta("last_slot", last)
  , true)
 var new_button := _button(L.text("new"), _new_game_dialog)
 new_button.name = "NewGameButton"
 new_button.disabled = network_state.get("active", false)
 column.add_child(new_button)
 column.add_child(_button(L.text("load"), _open_saves))
 var learn_button := _button(L.text("learn"), _toggle_guide)
 learn_button.disabled = network_state.get("active", false)
 column.add_child(learn_button)
 column.add_child(_button(L.text("multiplayer"), _open_multiplayer))
 column.add_child(_button(L.text("settings"), _open_preferences))
 column.add_child(_button(L.text("help"), _open_help))
 column.add_child(_button(L.text("credits"), _credits))
 column.add_child(_expand(Control.new()))
 column.add_child(_button(L.text("quit"), func(): get_tree().quit()))
 var context := VBoxContainer.new()
 context.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 row.add_child(context)
 var backdrop := WorldMap.new()
 backdrop.custom_minimum_size = Vector2(200, 280)
 backdrop.size_flags_vertical = Control.SIZE_EXPAND_FILL
 backdrop.mouse_filter = Control.MOUSE_FILTER_IGNORE
 context.add_child(backdrop)
 context.add_child(_label(L.text("menu_brief"), 22, PAPER, true))
 context.add_child(_label(L.text("menu_hint"), 16, MUTED, true))
 menu_status_label = _label("", 14, Color("eddaa8"), true)
 menu_status_label.name = "MenuStatus"
 context.add_child(menu_status_label)
 new_button.grab_focus()

func _unhandled_key_input(event: InputEvent) -> void:
 if event is InputEventKey and event.pressed and not event.echo:
  if event.keycode == KEY_ESCAPE:
   if is_instance_valid(popup) and popup.visible:
    popup.hide()
    popup.exclusive = false
    popup.queue_free()
   elif game_visible:
    _show_start_menu()
   elif not state.is_empty():
    _show_game()
   get_viewport().set_input_as_handled()
  elif event.keycode == KEY_F1:
   _open_help()
   get_viewport().set_input_as_handled()

func _open_saves() -> void:
 load("res://scripts/saves_panel.gd").new().show(self)

func _open_multiplayer() -> void:
 load("res://scripts/multiplayer_panel.gd").new().show(self)

func _open_help() -> void:
 load("res://scripts/manual.gd").show(self)

func _open_reports() -> void:
 var column := _dialog("Сведения о кампании" if L.language == "ru" else "Campaign reports", Vector2i(560, 510))
 column.add_child(_button(L.text("scores"), func(): Reports.show_report(self, "scores")))
 column.add_child(_button(L.text("objectives"), func(): Reports.show_report(self, "objectives")))
 column.add_child(_button(L.text("intelligence"), _intelligence_dialog))
 column.add_child(_button("Решения соперника" if L.language == "ru" else "Opponent decisions", func(): load("res://scripts/opponent_panel.gd").new().show(self)))
 undo_button = _button("Отменить прошлый ход" if L.language == "ru" else "Undo last turn", func():
  popup.hide()
  popup.queue_free()
  _command("undo")
 )
 undo_button.disabled = not state.get("undo_available", false)
 column.add_child(undo_button)
 column.add_child(_button(L.text("help"), _open_help))

func _open_preferences() -> void:
 var column := _dialog(L.text("settings"), Vector2i(620, 600))
 var music := CheckButton.new()
 music.text = L.text("music")
 music.button_pressed = music_enabled
 music.toggled.connect(func(value): music_enabled = value; _play_music(); _save_preferences())
 column.add_child(music)
 var slider := HSlider.new()
 slider.min_value = -40
 slider.max_value = 0
 slider.value = volume
 slider.value_changed.connect(func(value): volume = value; audio_player.volume_db = value; _save_preferences())
 column.add_child(_label(L.text("volume")))
 column.add_child(slider)
 var tracks := OptionButton.new()
 for track in track_names: tracks.add_item(str(track).get_basename().replace("_", " "))
 tracks.select(track_index)
 tracks.item_selected.connect(func(index): track_index = index; audio_player.stop(); _play_music(); _save_preferences())
 column.add_child(tracks)
 var motion := CheckButton.new()
 motion.text = L.text("motion")
 motion.button_pressed = reduced_motion
 motion.toggled.connect(func(value): reduced_motion = value; map_view.reduced_motion = value; _save_preferences())
 column.add_child(motion)
 var colors := CheckButton.new()
 colors.text = L.text("colorblind")
 colors.button_pressed = colorblind
 colors.toggled.connect(func(value): colorblind = value; map_view.set("colorblind", value); map_view.queue_redraw(); map_request_key = ""; _request_map_report(); _save_preferences())
 column.add_child(colors)
 var relief := CheckButton.new()
 relief.text = "Рельеф карты" if L.language == "ru" else "Terrain relief"
 relief.button_pressed = relief_enabled
 relief.toggled.connect(func(value): relief_enabled = value; map_view.relief_enabled = value; _save_preferences())
 column.add_child(relief)
 var effects := CheckButton.new()
 effects.text = L.text("sfx")
 effects.button_pressed = sfx_enabled
 effects.toggled.connect(func(value): sfx_enabled = value; _save_preferences())
 column.add_child(effects)
 column.add_child(_button("Русский" if L.language == "en" else "English", _change_language))
 column.add_child(_button(L.text("ai_settings"), _open_ai_settings))
 column.add_child(_button(L.text("intelligence"), _intelligence_dialog))

func _open_map_layers() -> void:
 MapPanel.show_layers(self)

func _map_briefing(country_id: int, event: Dictionary = {}) -> void:
 if event.is_empty():
  _show_drawer(country_drawer)
 else:
  MapPanel.show_event(self, country_id, event)

func _map_route_briefing(route: Dictionary) -> void:
 MapPanel.show_route(self, route)

func _populate_map_modes() -> void:
 map_picker.clear()
 var group := map_group_picker.selected
 for item in map_report.get("registry", []):
  var mode := int(item.id)
  var belongs := (mode < 8) if group == 0 else ((mode >= 8 and mode <= 21) or mode >= 58) if group == 1 else (mode >= 22 and mode < 58)
  if not belongs: continue
  var index := map_picker.item_count
  map_picker.add_item(Reports.wording(item, "label"), mode)
  map_picker.set_item_disabled(index, not bool(item.get("available", false)))
  if mode == map_mode_id: map_picker.select(index)
