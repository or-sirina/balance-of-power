extends RefCounted
## Experimental event desk. Only backend-returned history is displayed.
const L = preload("res://scripts/locale.gd")
var host: Control
var window: Window
var column: VBoxContainer
var status: Label
var history: RichTextLabel
var enabled: CheckBox
var generate: Button
var serial := 0
var populating := false

func open(owner_host: Control) -> void:
 host = owner_host
 serial += 1
 column = host._dialog(L.text("gamemaster"), Vector2i(760, 620))
 window = column.get_window()
 column.add_child(host._label(L.text("gamemaster_help"), 16, host.MUTED, true))
 enabled = CheckBox.new()
 enabled.text = L.text("gamemaster_enabled")
 column.add_child(enabled)
 status = host._label(L.text("working"), 15, host.PAPER, true)
 column.add_child(status)
 history = RichTextLabel.new()
 history.size_flags_vertical = Control.SIZE_EXPAND_FILL
 history.bbcode_enabled = false
 column.add_child(history)
 var row := HBoxContainer.new()
 column.add_child(row)
 generate = host._button(L.text("gamemaster_generate"), func(): _request("gamemaster_generate", {}))
 row.add_child(generate)
 row.add_child(host._button(L.text("ai_settings"), host._open_ai_settings))
 enabled.toggled.connect(func(value):
  if not populating: _request("gamemaster_set_enabled", {"enabled": value})
 )
 _request("gamemaster_get", {})

func _request(command: String, args: Dictionary) -> void:
 args = args.duplicate()
 args["language"] = L.language
 var request_serial := serial
 enabled.disabled = true
 generate.disabled = true
 status.text = L.text("working")
 host._command(command, args, func(response: Dictionary):
  if request_serial != serial or not is_instance_valid(window) or window.is_queued_for_deletion(): return
  if not response.get("ok", false):
   var error: Dictionary = response.get("error", {})
   status.text = str(error.get("message_ru" if L.language == "ru" else "message", L.text("connection_error")))
   enabled.disabled = false
   return
  var data: Dictionary = response.get("gamemaster", response.get("state", host.state).get("gamemaster", {}))
  _render(data)
 , true)

func _render(data: Dictionary) -> void:
 populating = true
 enabled.button_pressed = bool(data.get("enabled", false))
 populating = false
 var multiplayer: bool = not host.network_state.is_empty() and bool(host.network_state.get("active", false))
 enabled.disabled = multiplayer or not bool(data.get("supported", true))
 var state_name := str(data.get("status", "disabled"))
 var caption := L.text("gamemaster_status_" + state_name)
 if caption == "gamemaster_status_" + state_name: caption = state_name
 status.text = (L.text("gamemaster_multiplayer") if multiplayer else (L.text("gamemaster_unsupported") if not bool(data.get("supported", true)) else caption)) + "\n" + L.text("gamemaster_cost")
 var last_error := str(data.get("last_error_ru" if L.language == "ru" else "last_error", data.get("last_error", "")))
 if not last_error.is_empty(): status.text += "\n" + last_error
 generate.disabled = not bool(data.get("can_generate", true)) or not bool(data.get("supported", true)) or multiplayer or not enabled.button_pressed or state_name in ["pending", "generating"] or int(data.get("last_attempt_year", -1)) == int(host.state.get("year", -2)) or host.busy
 var lines := PackedStringArray()
 for event in data.get("history", []):
  if event is Dictionary:
   var title := str(event.get("headline_ru" if L.language == "ru" else "headline", event.get("title", "")))
   var body := str(event.get("text_ru" if L.language == "ru" else "text", event.get("description", "")))
   lines.append(str(event.get("year", "")) + "  " + title + "\n" + body)
 history.text = "\n\n".join(lines) if not lines.is_empty() else L.text("gamemaster_empty")
