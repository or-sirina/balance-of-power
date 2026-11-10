extends RefCounted
## Presentation only. The backend owns connection and turn authority.
var host
var window: Window
var ru := false
var status: Label
var detail: Label
var tabs: TabContainer
var side: OptionButton
var level: OptionButton
var address: LineEdit
var port: SpinBox
var relay: CheckBox
var games: ItemList
var folder: LineEdit
var game_id: LineEdit
var chat: LineEdit
var transcript: RichTextLabel
var chat_row: HBoxContainer
var start_button: Button
var leave_button: Button
var return_button: Button
var reconnect_button: Button
var publish_button: Button
var setup_controls: Array[Control] = []
var state: Dictionary = {}
var pending := false
var initialized := false

func text(en: String, russian: String) -> String:
 return russian if ru else en

func _label(parent: Node, caption: String, size: int = 15) -> Label:
 var label: Label = host._label(caption, size, host.PAPER, true)
 parent.add_child(label)
 return label

func _field(parent: Node, caption: String, value: String, node_name: String) -> LineEdit:
 _label(parent, caption)
 var field := LineEdit.new()
 field.name = node_name
 field.text = value
 field.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 parent.add_child(field)
 setup_controls.append(field)
 return field

func _action(parent: Node, caption: String, command: String, arguments: Callable, node_name: String = "") -> Button:
 var button: Button = host._button(caption, func(): _send(command, arguments.call()))
 if not node_name.is_empty(): button.name = node_name
 parent.add_child(button)
 setup_controls.append(button)
 return button

func _page(caption: String, help_text: String) -> VBoxContainer:
 var scroll := ScrollContainer.new()
 scroll.name = caption
 scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
 tabs.add_child(scroll)
 var column := VBoxContainer.new()
 column.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 column.add_theme_constant_override("separation", 8)
 scroll.add_child(column)
 var help: Label = _label(column, help_text)
 help.add_theme_color_override("font_color", host.MUTED)
 return column

func show(parent) -> void:
 host = parent
 ru = str(host.L.language) == "ru"
 var body: VBoxContainer = host._dialog(text("Two-player game", "Игра вдвоём"), Vector2i(820, 660))
 window = host.popup
 window.name = "MultiplayerWindow"
 status = _label(body, "", 19)
 status.add_theme_color_override("font_color", Color("eddaa8"))
 detail = _label(body, "")
 var settings := HBoxContainer.new()
 body.add_child(settings)
 var side_label := _label(settings, text("Your side", "Ваша сторона"))
 side_label.autowrap_mode = TextServer.AUTOWRAP_OFF
 side = OptionButton.new()
 side.name = "MultiplayerSide"
 side.add_item(host.L.country(0), 0)
 side.add_item(host.L.country(1), 1)
 settings.add_child(side)
 setup_controls.append(side)
 var level_label := _label(settings, text("Difficulty", "Сложность"))
 level_label.autowrap_mode = TextServer.AUTOWRAP_OFF
 level = OptionButton.new()
 level.name = "MultiplayerLevel"
 for key in ["beginner", "intermediate", "expert", "multipolar", "adaptive"]: level.add_item(host.L.text(key))
 level.select(2)
 level.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 settings.add_child(level)
 setup_controls.append(level)
 tabs = TabContainer.new()
 tabs.size_flags_vertical = Control.SIZE_EXPAND_FILL
 tabs.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 body.add_child(tabs)
 _build_lan()
 _build_hotseat()
 _build_mail()
 transcript = RichTextLabel.new()
 transcript.name = "MultiplayerChatHistory"
 transcript.custom_minimum_size.y = 68
 transcript.scroll_following = true
 transcript.selection_enabled = true
 body.add_child(transcript)
 chat_row = HBoxContainer.new()
 body.add_child(chat_row)
 chat = LineEdit.new()
 chat.name = "MultiplayerChat"
 chat.placeholder_text = text("Message your opponent", "Сообщение сопернику")
 chat.max_length = 1000
 chat.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 chat_row.add_child(chat)
 var send: Button = host._button(text("Send", "Отправить"), _send_chat)
 chat_row.add_child(send)
 chat.text_submitted.connect(func(_value): _send_chat())
 var actions := HBoxContainer.new()
 body.add_child(actions)
 leave_button = host._button(text("Leave session", "Покинуть сеанс"), func(): _send("multiplayer_leave", {}))
 leave_button.name = "LeaveMultiplayer"
 actions.add_child(leave_button)
 return_button = host._button(text("Return to game", "Вернуться в игру"), _enter_game)
 return_button.name = "ReturnToMultiplayerGame"
 actions.add_child(return_button)
 var close: Button = host._button(host.L.text("close"), func(): window.hide(); window.exclusive = false; window.queue_free())
 actions.add_child(close)
 if host.has_signal("network_changed"):
  host.connect("network_changed", _network_changed)
  window.tree_exiting.connect(func():
   if is_instance_valid(host) and host.is_connected("network_changed", _network_changed): host.disconnect("network_changed", _network_changed)
  )
 var initial = host.get("network_state")
 if initial is Dictionary: _network_changed(initial)
 else: _network_changed(host.state.get("multiplayer", {}))
 var current_mode := str(state.get("mode", ""))
 tabs.current_tab = 1 if current_mode == "hotseat" else 2 if current_mode == "mail" else 0

func _build_lan() -> void:
 var page := _page(text("LAN", "Локальная сеть"), text("Host a Godot game or join another Godot player. The guest takes the other side; the host starts once connected.", "Создайте партию Godot или подключитесь к игроку Godot. Гость получает другую сторону; после подключения начинает хозяин."))
 var endpoint := HBoxContainer.new()
 page.add_child(endpoint)
 var address_box := VBoxContainer.new()
 address_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 endpoint.add_child(address_box)
 address = _field(address_box, text("Host or relay address", "Адрес хозяина или ретранслятора"), "127.0.0.1", "MultiplayerAddress")
 var port_box := VBoxContainer.new()
 endpoint.add_child(port_box)
 _label(port_box, text("Port", "Порт"))
 port = SpinBox.new()
 port.name = "MultiplayerPort"
 port.min_value = 1
 port.max_value = 65535
 port.value = 27835
 port.custom_minimum_size.x = 125
 port_box.add_child(port)
 setup_controls.append(port)
 relay = CheckBox.new()
 relay.text = text("Host through a relay at this address and port", "Создать через ретранслятор по этому адресу и порту")
 page.add_child(relay)
 setup_controls.append(relay)
 var buttons := HBoxContainer.new()
 page.add_child(buttons)
 var host_button: Button = host._button(text("Host game", "Создать партию"), func(): pass)
 host_button.name = "HostMultiplayer"
 buttons.add_child(host_button)
 setup_controls.append(host_button)
 host_button.pressed.connect(func():
  var args := _setup()
  args["port"] = int(port.value)
  if relay.button_pressed: args["address"] = address.text.strip_edges()
  _send("multiplayer_host_relay" if relay.button_pressed else "multiplayer_host", args)
 )
 _action(buttons, text("Join game", "Подключиться"), "multiplayer_join", func(): return {"address": address.text.strip_edges(), "port": int(port.value)}, "JoinMultiplayer")
 _action(buttons, text("Find LAN games", "Найти в сети"), "multiplayer_discover", func(): return {}, "DiscoverMultiplayer")
 start_button = host._button(text("Start with connected player", "Начать с подключённым игроком"), func(): _send("multiplayer_start", {}))
 start_button.name = "StartMultiplayer"
 page.add_child(start_button)
 games = ItemList.new()
 games.name = "DiscoveredGames"
 games.custom_minimum_size.y = 90
 page.add_child(games)
 games.item_selected.connect(func(index):
  var game: Dictionary = games.get_item_metadata(index)
  address.text = str(game.get("address", ""))
  port.value = int(game.get("port", 27835))
 )
 reconnect_button = host._button(text("Reconnect", "Подключиться снова"), func(): _send("multiplayer_reconnect", {}))
 page.add_child(reconnect_button)

func _build_hotseat() -> void:
 var page := _page(text("This computer", "Этот компьютер"), text("Share one computer. Each side makes its decisions before the year advances. The game tells you when to hand over.", "Играйте за одним компьютером. Обе стороны принимают решения до смены года. Игра подсказывает, когда передать управление."))
 _action(page, text("Start hotseat game", "Начать игру за одним компьютером"), "multiplayer_hotseat", _setup, "StartHotseat")

func _build_mail() -> void:
 var page := _page(text("Mail", "По почте"), text("Exchange turns in a shared folder. Both players use the same game code and choose different sides.", "Обменивайтесь ходами в общей папке. Укажите одинаковый код партии и разные стороны."))
 var row := HBoxContainer.new()
 page.add_child(row)
 folder = LineEdit.new()
 folder.name = "MailGameFolder"
 folder.placeholder_text = text("Shared move folder", "Общая папка ходов")
 folder.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 row.add_child(folder)
 setup_controls.append(folder)
 var browse: Button = host._button(text("Choose folder…", "Выбрать папку…"), _choose_folder)
 row.add_child(browse)
 setup_controls.append(browse)
 game_id = _field(page, text("Game code", "Код партии"), "bop-game", "MailGameCode")
 var actions := HBoxContainer.new()
 page.add_child(actions)
 _action(actions, text("Create game", "Создать партию"), "multiplayer_mail_create", _mail_setup, "CreateMailGame")
 _action(actions, text("Join game", "Открыть партию"), "multiplayer_mail_join", _mail_setup, "JoinMailGame")
 publish_button = host._button(text("Publish completed turn", "Опубликовать завершённый ход"), func(): _send("multiplayer_mail_submit", {}))
 page.add_child(publish_button)
 page.add_child(host._button(text("Check for partner's turn", "Проверить ход партнёра"), func(): _send("multiplayer_poll", {})))

func _setup() -> Dictionary:
 return {"side": side.selected, "level": level.selected + 1}

func _mail_setup() -> Dictionary:
 var result := _setup()
 result.merge({"directory": folder.text.strip_edges(), "game_id": game_id.text.strip_edges()})
 return result

func _choose_folder() -> void:
 var picker := FileDialog.new()
 picker.file_mode = FileDialog.FILE_MODE_OPEN_DIR
 picker.access = FileDialog.ACCESS_FILESYSTEM
 picker.title = text("Shared move folder", "Общая папка ходов")
 picker.size = Vector2i(650, 430)
 window.add_child(picker)
 picker.dir_selected.connect(func(path): folder.text = path; picker.queue_free())
 picker.canceled.connect(picker.queue_free)
 picker.popup_centered()

func _send_chat() -> void:
 if chat.text.strip_edges().is_empty(): return
 var message := chat.text.strip_edges()
 _send("multiplayer_chat", {"text": message})
 chat.clear()

func _send(command: String, arguments: Dictionary) -> void:
 if pending or not is_instance_valid(window): return
 if host.busy:
  detail.text = text("Wait for the current action to finish.", "Дождитесь завершения текущего действия.")
  return
 pending = true
 _update_controls()
 host._command(command, arguments, func(response):
  if not is_instance_valid(window): return
  pending = false
  var response_state = response.get("state")
  var network = response.get("multiplayer", response_state.get("multiplayer", state) if response_state is Dictionary else state)
  if network is Dictionary: _network_changed(network)
  if not response.get("ok", false):
   detail.text = str(response.get("error", {}).get("message_ru" if ru else "message", text("Could not complete the request.", "Не удалось выполнить действие.")))
  elif command == "multiplayer_leave":
   window.hide()
   window.exclusive = false
   window.queue_free()
   host._show_start_menu()
  elif command in ["multiplayer_start", "multiplayer_hotseat", "multiplayer_mail_create", "multiplayer_mail_join"] and state.get("status", "") == "playing":
   _enter_game()
  _update_controls()
 )

func _enter_game() -> void:
 if is_instance_valid(window):
  window.hide()
  window.exclusive = false
  window.queue_free()
 host._show_game()

func _network_changed(network: Dictionary = {}) -> void:
 if not is_instance_valid(window): return
 var previous_phase := str(state.get("status", "offline"))
 var was_initialized := initialized
 state = network.duplicate(true)
 initialized = true
 var mode := str(state.get("mode", ""))
 var phase := str(state.get("status", "offline"))
 var captions := {
  "offline": text("Choose how to play", "Выберите способ игры"),
  "waiting": text("Waiting for your opponent", "Ожидание соперника"),
  "connecting": text("Connecting…", "Подключение…"),
  "lobby": text("Opponent connected — host can start", "Соперник подключён — хозяин может начать"),
  "playing": text("Game in progress", "Партия идёт"),
  "disconnected": text("Connection lost — retrying", "Связь потеряна — повторное подключение")}
 status.text = str(captions.get(phase, text("Session paused", "Сеанс приостановлен")))
 if state.get("active", false):
  var ready: Array = state.get("ready", [])
  var local_side := int(state.get("local_side", 0))
  detail.text = text("You play ", "Ваша сторона: ") + host.L.country(local_side)
  if mode in ["host", "guest"]: detail.text += text(". Port ", ". Порт ") + str(state.get("port", 0))
  if phase == "playing":
   detail.text += text(". Your decisions are ready; waiting for your opponent.", ". Ваши решения приняты; ожидание соперника.") if local_side in ready else text(". Your move.", ". Ваш ход.") if state.get("can_act", false) else text(". Waiting for your opponent.", ". Ожидание соперника.")
 else:
  detail.text = text("Godot players connect to Godot games. The original Qt application uses a different session protocol.", "Игроки Godot подключаются к партиям Godot. У исходного приложения Qt другой протокол сеанса.")
 games.clear()
 for game in state.get("games", []):
  var index := games.item_count
  games.add_item(str(game.get("name", text("Game", "Партия"))) + "  " + str(game.get("address", "")) + ":" + str(game.get("port", "")))
  games.set_item_metadata(index, game)
 transcript.text = ""
 for message in state.get("chat", []):
  transcript.add_text(host.L.country(int(message.get("side", 0))) + ": " + str(message.get("text", "")) + "\n")
 _update_controls()
 if was_initialized and mode == "guest" and phase == "playing" and previous_phase in ["lobby", "waiting", "connecting"]:
  _enter_game.call_deferred()

func _update_controls() -> void:
 if not is_instance_valid(window): return
 var active := bool(state.get("active", false))
 var mode := str(state.get("mode", ""))
 var phase := str(state.get("status", "offline"))
 for control in setup_controls:
  if control is BaseButton: control.disabled = active or pending
  elif control is LineEdit: control.editable = not active and not pending
  elif control is SpinBox: control.editable = not active and not pending
 start_button.visible = mode == "host"
 start_button.disabled = pending or phase != "lobby"
 reconnect_button.visible = mode == "guest" and phase == "disconnected"
 reconnect_button.disabled = pending
 publish_button.disabled = pending or mode != "mail"
 leave_button.visible = active
 leave_button.disabled = pending
 return_button.visible = active and phase == "playing"
 chat_row.visible = mode in ["host", "guest"] and phase in ["lobby", "playing"]
 transcript.visible = chat_row.visible
