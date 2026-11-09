extends RefCounted

const L = preload("res://scripts/locale.gd")
var host: Control
var window: Window
var slots: ItemList
var slot_name: LineEdit
var saves: Array = []
var save_button: Button
var load_button: Button
var delete_button: Button
var hint: Label
var refresh_serial := 0
var list_ready := false

func text(en: String, ru: String) -> String:
 return ru if L.language == "ru" else en

func show(parent: Control) -> void:
 host = parent
 list_ready = false
 var body: VBoxContainer = host._dialog(text("Saved campaigns", "Сохранённые кампании"), Vector2i(680, 530))
 window = host.popup
 slots = ItemList.new()
 slots.name = "SaveSlots"
 slots.custom_minimum_size.y = 235
 slots.size_flags_vertical = Control.SIZE_EXPAND_FILL
 body.add_child(slots)
 slot_name = LineEdit.new()
 slot_name.name = "SaveSlotName"
 slot_name.placeholder_text = text("Campaign name", "Название кампании")
 slot_name.text = "prototype"
 body.add_child(slot_name)
 var row := HBoxContainer.new()
 body.add_child(row)
 save_button = host._button(text("Save", "Сохранить"), _save)
 save_button.name = "SaveCampaign"
 row.add_child(save_button)
 load_button = host._button(text("Load", "Загрузить"), _load)
 row.add_child(load_button)
 delete_button = host._button(text("Delete", "Удалить"), _delete)
 row.add_child(delete_button)
 row.add_child(host._button(text("Refresh", "Обновить"), _refresh))
 var portable := HBoxContainer.new()
 body.add_child(portable)
 var import_button: Button = host._button(text("Import .bopg…", "Импорт .bopg…"), func(): _file(false))
 import_button.disabled = bool(host.state.get("tutorial", {}).get("active", false)) or (bool(host.state.get("multiplayer", {}).get("active", false)) and str(host.state.get("multiplayer", {}).get("mode", "")) != "hotseat")
 portable.add_child(import_button)
 var export_button: Button = host._button(text("Export .bopg…", "Экспорт .bopg…"), func(): _file(true))
 export_button.disabled = host.state.is_empty() or bool(host.state.get("tutorial", {}).get("active", false)) or (bool(host.state.get("multiplayer", {}).get("active", false)) and str(host.state.get("multiplayer", {}).get("mode", "")) != "hotseat")
 portable.add_child(export_button)
 hint = host._label(text("Save the campaign in a named slot, or exchange a portable .bopg file.", "Сохраните кампанию под именем или перенесите её файлом .bopg."), 14, host.MUTED, true)
 body.add_child(hint)
 slots.item_selected.connect(func(index): slot_name.text = str(saves[index].slot); _buttons())
 slots.item_activated.connect(func(_index): _load())
 slot_name.text_changed.connect(func(_value): _buttons())
 _refresh()

func _valid() -> bool:
 return is_instance_valid(window) and not window.is_queued_for_deletion() and is_instance_valid(slots)

func _refresh() -> void:
 refresh_serial += 1
 var serial := refresh_serial
 var owner := window
 list_ready = false
 _buttons()
 host._command("save_list", {}, func(response):
  if not _valid() or window != owner or serial != refresh_serial: return
  if not response.get("ok", false):
   _failure(response)
   return
  list_ready = true
  saves = response.get("saves", [])
  slots.clear()
  for save in saves:
   var year = save.get("year")
   slots.add_item(str(save.slot) + ("  ·  " + str(int(year)) if year != null else ""))
  _buttons()
 , true)

func _failure(response: Dictionary) -> void:
 if not _valid(): return
 var error: Dictionary = response.get("error", {})
 hint.text = str(error.get("message_ru" if L.language == "ru" else "message", text("Could not complete this action. Try again.", "Не удалось выполнить действие. Попробуйте снова.")))

func _run(command: String, args: Dictionary, success: Callable) -> void:
 if not _valid(): return
 if host.busy:
  hint.text = text("Wait for the current action to finish, then try again.", "Дождитесь завершения текущего действия и повторите попытку.")
  return
 var owner := window
 host._command(command, args, func(response):
  if not _valid() or window != owner: return
  if response.get("ok", false): success.call()
  else: _failure(response)
 )

func _buttons() -> void:
 if not _valid(): return
 var exists := false
 for save in saves:
  if str(save.slot) == slot_name.text: exists = true
 var blocked := bool(host.state.get("tutorial", {}).get("active", false)) or (bool(host.state.get("multiplayer", {}).get("active", false)) and str(host.state.get("multiplayer", {}).get("mode", "")) != "hotseat")
 save_button.disabled = not list_ready or host.state.is_empty() or slot_name.text.strip_edges().is_empty() or blocked
 load_button.disabled = not list_ready or not exists or blocked
 delete_button.disabled = not list_ready or not exists or blocked

func _confirm(message: String, action: Callable) -> void:
 var dialog := ConfirmationDialog.new()
 dialog.title = text("Confirm", "Подтверждение")
 dialog.dialog_text = message
 dialog.ok_button_text = text("Confirm", "Подтвердить")
 dialog.cancel_button_text = text("Cancel", "Отмена")
 window.add_child(dialog)
 var owner := window
 dialog.confirmed.connect(func():
  if _valid() and window == owner: action.call()
  dialog.queue_free()
 )
 dialog.canceled.connect(dialog.queue_free)
 dialog.popup_centered()

func _save() -> void:
 if not list_ready or save_button.disabled: return
 var name_value := slot_name.text
 var action := func(): _run("save", {"slot": name_value}, _refresh)
 for save in saves:
  if str(save.slot) == name_value:
   _confirm(text("Overwrite campaign “%s”?", "Заменить кампанию «%s»?") % name_value, action)
   return
 action.call()

func _load() -> void:
 if not list_ready or load_button.disabled: return
 var name_value := slot_name.text
 var action := func(): _run("load", {"slot": name_value}, func():
  host._show_game()
  window.queue_free()
 )
 if host.state.is_empty(): action.call()
 else: _confirm(text("Replace the current campaign with this save?", "Заменить текущую кампанию этим сохранением?"), action)

func _delete() -> void:
 if not list_ready or delete_button.disabled: return
 var name_value := slot_name.text
 _confirm(text("Delete campaign “%s”?", "Удалить кампанию «%s»?") % name_value, func():
  _run("save_delete", {"slot": name_value}, _refresh)
 )

func _file(writing: bool) -> void:
 var dialog := FileDialog.new()
 dialog.name = "PortableGameDialog"
 dialog.title = text("Export campaign", "Экспорт кампании") if writing else text("Import campaign", "Импорт кампании")
 dialog.access = FileDialog.ACCESS_FILESYSTEM
 dialog.file_mode = FileDialog.FILE_MODE_SAVE_FILE if writing else FileDialog.FILE_MODE_OPEN_FILE
 dialog.filters = PackedStringArray(["*.bopg ; Balance of Power game"])
 dialog.use_native_dialog = true
 if writing: dialog.current_file = "campaign.bopg"
 window.add_child(dialog)
 var owner := window
 dialog.file_selected.connect(func(path):
  if not _valid() or window != owner:
   dialog.queue_free()
   return
  var action := func(): _run("export_game" if writing else "import_game", {"path": path}, func():
   if writing: hint.text = text("Campaign exported.", "Кампания экспортирована.")
   else:
    host._show_game()
    window.queue_free()
  )
  # FileDialog itself confirms replacement of an existing export file.
  if not writing and not host.state.is_empty():
   _confirm(text("Replace the current campaign with this file?", "Заменить текущую кампанию из этого файла?"), action)
  else: action.call()
  dialog.queue_free()
 )
 dialog.canceled.connect(dialog.queue_free)
 dialog.popup_centered_ratio(0.75)
