extends RefCounted
## Reusable settings dialog. request(command, args, done) must be asynchronous.
## Integration: Settings.new().open(main_control, request_callable, "ru" or "en").
## The host supplies its existing _dialog(title, size) helper and theme.

const COPY = {
 "provider": ["Provider", "Провайдер"],
 "provider_note": ["One provider connection; choose a model for each role below. Changing provider fills its defaults and clears the entered key. Saved keys stay with their provider.", "Одно подключение к провайдеру; ниже задайте модель для каждой роли. При смене провайдера подставляются настройки и очищается ввод ключа. Сохранённые ключи остаются у своего провайдера."],
 "gamemaster_model": ["Experimental game master model", "Модель экспериментального ведущего"],
 "gamemaster_role": ["Game master", "Ведущий"],
 "title": ["AI settings", "Настройки ИИ"],
 "intro": ["Adaptive difficulty uses the opponent model. AI advisors use a text model. Built-in AI remains available offline.", "На адаптивном уровне играет модель соперника. ИИ-советникам нужна текстовая модель. Встроенный ИИ доступен без сети."],
 "offline": ["Use built-in AI; disable network calls", "Встроенный ИИ без сетевых запросов"],
 "endpoint": ["Endpoint", "Адрес API"],
 "endpoint_note": ["Use the provider's API base URL, such as an address ending in /v1. Do not put the API key or /chat/completions in this field.", "Укажите базовый адрес API провайдера, например с окончанием /v1. Не добавляйте сюда API-ключ или /chat/completions."],
 "model": ["Opponent model", "Модель соперника"],
 "chat_model": ["Advisor text model", "Текстовая модель советников"],
 "backend": ["Opponent API", "Тип API соперника"],
 "auto": ["Automatic", "Автоматически"],
 "chat": ["Chat completions", "Текстовый API (Chat)"],
 "decisions": ["Typed decisions (Jev)", "API решений (Jev)"],
 "advisors": ["AI advisors enabled", "Включить ИИ-советников"],
 "reasoning": ["Allow advisor reasoning before the answer", "Разрешить модели обдумывать ответ"],
 "key": ["New API key", "Новый API-ключ"],
 "key_keep": ["Leave blank to keep the configured key", "Оставьте пустым, чтобы сохранить текущий ключ"],
 "key_add": ["Enter an API key", "Введите API-ключ"],
 "configured": ["A key is configured. Its value is never sent to this screen.", "Ключ настроен. Его значение никогда не передаётся на этот экран."],
 "unconfigured": ["No API key is configured.", "API-ключ не настроен."],
 "environment": ["Environment overrides are active: ", "Действуют переменные окружения: "],
 "environment_key": ["An environment key remains active even if the saved key is removed.", "Ключ из окружения продолжит действовать после удаления сохранённого ключа."],
 "clear": ["Remove the saved API key on Apply", "Удалить сохранённый API-ключ при применении"],
 "reveal": ["Show newly entered key", "Показать вводимый ключ"],
 "temperature": ["Temperature", "Температура"],
 "tokens": ["Maximum answer tokens", "Лимит токенов ответа"],
 "timeout": ["Timeout, seconds", "Время ожидания, секунды"],
 "budget": ["Model calls per game (0 = unlimited)", "Вызовов модели на партию (0 — без лимита)"],
 "fallbacks": ["Fallback models, comma separated (optional)", "Резервные модели через запятую (необязательно)"],
 "model_note": ["A decisions opponent needs a separate text model for advisors. Model names can be entered freely.", "Если соперник использует API решений, советникам нужна отдельная текстовая модель. Имена моделей можно вводить свободно."],
 "test_note": ["Test uses the current form without saving. It sends small provider requests, outside the game's call allowance. Each probe waits up to about 45 seconds.", "Проверка использует форму без сохранения. Она отправляет небольшие запросы провайдеру вне лимита партии. Каждый запрос ожидается не более 45 секунд."],
 "test": ["Test connection", "Проверить подключение"],
 "reload": ["Reload", "Обновить"],
 "apply": ["Apply", "Применить"],
 "close": ["Close", "Закрыть"],
 "loading": ["Loading settings…", "Загружаем настройки…"],
 "testing": ["Testing the connection…", "Проверяем подключение…"],
 "saving": ["Saving settings…", "Сохраняем настройки…"],
 "saved": ["Saved. The game will use these settings for its next model request.", "Сохранено. Следующий запрос игры использует эти настройки."],
 "edited": ["Unsaved changes. Apply to save them.", "Есть изменения. Нажмите «Применить», чтобы сохранить."],
 "stale": ["The form changed during the test. Test the current values again.", "Во время проверки форма изменилась. Проверьте текущие значения ещё раз."],
 "error": ["Could not complete the settings request.", "Не удалось выполнить запрос настроек."],
 "invalid": ["Check this field: ", "Проверьте поле: "],
 "opponent": ["Opponent", "Соперник"],
 "advisor_role": ["Advisors", "Советники"],
}

var _host: Control
var _request: Callable
var _language := "en"
var _window: Window
var _form: VBoxContainer
var _status: Label
var _key_status: Label
var _data: Dictionary = {}
var _controls: Dictionary = {}
var _test_button: Button
var _apply_button: Button
var _reload_button: Button
var _serial := 0
var _edit_serial := 0
var _populating := false

func _text(key: String) -> String:
 var entry: Array = COPY.get(key, [key, key])
 return str(entry[1 if _language == "ru" else 0])

func _label(value: String) -> Label:
 var result := Label.new()
 result.text = value
 result.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
 result.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 return result

func _button(key: String, action: Callable) -> Button:
 var result := Button.new()
 result.text = _text(key)
 result.pressed.connect(action)
 return result

func open(host: Control, request: Callable, language: String = "en") -> void:
 close()
 _serial += 1
 _host = host
 _request = request
 _language = "ru" if language == "ru" else "en"
 var column: VBoxContainer = host.call("_dialog", _text("title"), Vector2i(820, 720))
 _window = column.get_window()
 _window.close_requested.connect(close)
 column.add_child(_label(_text("intro")))
 var scroll := ScrollContainer.new()
 scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
 scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
 scroll.follow_focus = true
 column.add_child(scroll)
 _form = VBoxContainer.new()
 _form.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 _form.add_theme_constant_override("separation", 8)
 scroll.add_child(_form)
 _controls.clear()
 _check("offline", "offline")
 _form.add_child(_label(_text("provider")))
 var provider := OptionButton.new()
 provider.item_selected.connect(_provider_selected)
 _controls.provider = provider
 _form.add_child(provider)
 _form.add_child(_label(_text("provider_note")))
 _entry("base_url", "endpoint")
 _form.add_child(_label(_text("endpoint_note")))
 _entry("model", "model")
 _form.add_child(_label(_text("backend")))
 var backend := OptionButton.new()
 for key in ["auto", "chat", "decisions"]:
  backend.add_item(_text(key))
 backend.item_selected.connect(func(_index): _edited())
 _controls.backend = backend
 _form.add_child(backend)
 _check("advisors_enabled", "advisors")
 _entry("chat_model", "chat_model")
 _entry("gamemaster_model", "gamemaster_model")
 _form.add_child(_label(_text("model_note")))
 _check("reasoning", "reasoning")
 var key: LineEdit = _entry("api_key", "key")
 key.secret = true
 key.max_length = 4096
 _key_status = _label("")
 _form.add_child(_key_status)
 var reveal := CheckBox.new()
 reveal.text = _text("reveal")
 reveal.toggled.connect(func(shown): key.secret = not shown)
 _form.add_child(reveal)
 var clear := _check("clear_api_key", "clear")
 clear.toggled.connect(func(remove):
  key.editable = not remove
  if remove: key.clear()
 )
 _number("temperature", "temperature", 0, 2, 0.1)
 _number("max_tokens", "tokens", 128, 8192, 1)
 _number("timeout", "timeout", 5, 300, 1)
 _number("max_requests", "budget", 0, 10000, 1)
 _entry("fallback_models", "fallbacks")
 _form.add_child(_label(_text("test_note")))
 _status = _label(_text("loading"))
 _status.custom_minimum_size.y = 54
 column.add_child(_status)
 var buttons := HBoxContainer.new()
 _test_button = _button("test", _test)
 _reload_button = _button("reload", _reload)
 _apply_button = _button("apply", _apply)
 buttons.add_child(_test_button)
 buttons.add_child(_reload_button)
 var spacer := Control.new()
 spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 buttons.add_child(spacer)
 buttons.add_child(_button("close", close))
 buttons.add_child(_apply_button)
 column.add_child(buttons)
 _set_busy(true)
 _reload()

func close() -> void:
 _serial += 1
 if _controls.get("api_key") is LineEdit and is_instance_valid(_controls.api_key):
  _controls.api_key.clear()
 if is_instance_valid(_window):
  _window.queue_free()
 _window = null
 _controls.clear()
 _data.clear()

func _entry(name: String, caption: String) -> LineEdit:
 _form.add_child(_label(_text(caption)))
 var result := LineEdit.new()
 result.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 result.text_changed.connect(func(_value): _edited())
 _controls[name] = result
 _form.add_child(result)
 return result

func _check(name: String, caption: String) -> CheckBox:
 var result := CheckBox.new()
 result.text = _text(caption)
 result.toggled.connect(func(_value): _edited())
 _controls[name] = result
 _form.add_child(result)
 return result

func _number(name: String, caption: String, minimum: float, maximum: float, increment: float) -> void:
 _form.add_child(_label(_text(caption)))
 var result := SpinBox.new()
 result.min_value = minimum
 result.max_value = maximum
 result.step = increment
 result.value_changed.connect(func(_value): _edited())
 _controls[name] = result
 _form.add_child(result)

func _edited() -> void:
 if _populating or not is_instance_valid(_status): return
 _edit_serial += 1
 _status.text = _text("edited")

func _set_busy(value: bool) -> void:
 _test_button.disabled = value
 _apply_button.disabled = value
 _reload_button.disabled = value
 for name in _controls:
  var control: Control = _controls[name]
  if control is LineEdit or control is SpinBox:
   control.editable = not value
  elif control is BaseButton:
   control.disabled = value
 if not value and _controls.get("clear_api_key") is CheckBox:
  _controls.api_key.editable = not _controls.clear_api_key.button_pressed

func _alive(serial: int) -> bool:
 return serial == _serial and is_instance_valid(_window) and not _window.is_queued_for_deletion()

func _error(response: Dictionary) -> String:
 var error: Dictionary = response.get("error", {})
 var result := str(error.get("message_ru" if _language == "ru" else "message", _text("error")))
 var field_value: Variant = error.get("field", "")
 if field_value is String and not field_value.is_empty():
  var field: String = field_value
  result += "\n" + _text("invalid") + _text({"base_url": "endpoint", "api_key": "key", "advisors_enabled": "advisors", "max_tokens": "tokens", "max_requests": "budget", "fallback_models": "fallbacks", "disable_reasoning": "reasoning", "clear_api_key": "clear"}.get(field, field))
 return result

func _reload() -> void:
 _serial += 1
 var serial := _serial
 _set_busy(true)
 _status.text = _text("loading")
 _request.call("settings_get", {}, func(response: Dictionary):
  if not _alive(serial): return
  _set_busy(false)
  if response.get("ok", false) and response.get("settings") is Dictionary:
   _populate(response.settings)
   _status.text = ""
  else:
   _status.text = _error(response)
 )

func _populate(settings: Dictionary) -> void:
 _populating = true
 _data = settings.duplicate(true)
 _controls.provider.clear()
 var catalog: Array = settings.get("provider_catalog", [{"id": "custom", "name": "Custom", "base_url": "", "default_model": ""}])
 for item in catalog:
  _controls.provider.add_item(str(item.get("name", item.id)))
  _controls.provider.set_item_metadata(_controls.provider.item_count - 1, item)
  if str(item.id) == str(settings.get("provider", "custom")):
   _controls.provider.select(_controls.provider.item_count - 1)
 for name in ["base_url", "model", "chat_model", "gamemaster_model"]:
  _controls[name].text = str(settings.get(name, ""))
 _controls.backend.select(maxi(0, ["auto", "chat", "decisions"].find(str(settings.get("backend", "auto")))))
 for name in ["offline", "advisors_enabled"]:
  _controls[name].button_pressed = bool(settings.get(name, false))
 _controls.reasoning.button_pressed = not bool(settings.get("disable_reasoning", true))
 for name in ["temperature", "max_tokens", "timeout", "max_requests"]:
  _controls[name].value = float(settings.get(name, 0))
 _controls.fallback_models.text = ", ".join(PackedStringArray(settings.get("fallback_models", [])))
 _controls.clear_api_key.button_pressed = false
 _controls.api_key.editable = true
 _controls.api_key.clear()
 _controls.api_key.placeholder_text = _text("key_keep" if settings.get("key_configured", false) else "key_add")
 _key_status.text = _text("configured" if settings.get("key_configured", false) else "unconfigured")
 var overrides: Array = settings.get("environment_overrides", [])
 if not overrides.is_empty():
  var captions := PackedStringArray()
  for name in overrides:
   var caption: String = {"base_url": "endpoint", "api_key": "key"}.get(name, name)
   captions.append(_text(caption))
  _key_status.text += "\n" + _text("environment") + ", ".join(captions)
 if settings.get("key_from_environment", false):
  _key_status.text += "\n" + _text("environment_key")
 _populating = false
 _edit_serial += 1

func _values() -> Dictionary:
 var values := {"language": _language, "expected_generation": int(_data.get("generation", -1))}
 values.provider = str(_controls.provider.get_selected_metadata().get("id", "custom"))
 for name in ["base_url", "model", "chat_model", "gamemaster_model", "api_key"]:
  values[name] = str(_controls[name].text)
 values.backend = ["auto", "chat", "decisions"][_controls.backend.selected]
 for name in ["offline", "advisors_enabled", "clear_api_key"]:
  values[name] = bool(_controls[name].button_pressed)
 values.disable_reasoning = not bool(_controls.reasoning.button_pressed)
 values.temperature = float(_controls.temperature.value)
 for name in ["max_tokens", "timeout", "max_requests"]:
  values[name] = int(_controls[name].value)
 values.fallback_models = []
 for name in str(_controls.fallback_models.text).split(",", false):
  if not name.strip_edges().is_empty(): values.fallback_models.append(name.strip_edges())
 return values

func _apply() -> void:
 if _data.is_empty(): return
 _serial += 1
 var serial := _serial
 _set_busy(true)
 _status.text = _text("saving")
 _request.call("settings_apply", _values(), func(response: Dictionary):
  if not _alive(serial): return
  _set_busy(false)
  if response.get("ok", false) and response.get("settings") is Dictionary:
   _populate(response.settings)
   _status.text = _text("saved")
  else:
   _status.text = _error(response)
 )

func _test() -> void:
 if _data.is_empty(): return
 var serial := _serial
 var edit_serial := _edit_serial
 var values := _values()
 _test_button.disabled = true
 _status.text = _text("testing")
 _request.call("settings_test", values, func(response: Dictionary):
  if not _alive(serial): return
  _test_button.disabled = false
  if edit_serial != _edit_serial or _values() != values:
   _status.text = _text("stale")
   return
  if not response.get("ok", false):
   _status.text = _error(response)
   return
  var result: Dictionary = response.get("test", {})
  var lines := PackedStringArray()
  for report in result.get("reports", []):
   var role: String = str(report.get("role", ""))
   var caption := _text({"opponent": "opponent", "advisor": "advisor_role", "gamemaster": "gamemaster_role"}.get(role, "advisor_role")) if not role.is_empty() else ""
   var message := str(report.get("message_ru" if _language == "ru" else "message", _text("error")))
   lines.append((caption + ": " if not caption.is_empty() else "") + message)
  _status.text = "\n".join(lines) if not lines.is_empty() else _text("error")
 )

func _provider_selected(index: int) -> void:
 if _populating: return
 var provider: Dictionary = _controls.provider.get_item_metadata(index)
 _controls.base_url.text = str(provider.get("base_url", ""))
 for field in ["model", "chat_model", "gamemaster_model"]:
  _controls[field].text = str(provider.get("default_model", ""))
 _controls.backend.select(0)
 _controls.api_key.clear()
 _controls.clear_api_key.button_pressed = false
 _controls.api_key.editable = true
 _controls.api_key.placeholder_text = _text("key_add")
 _key_status.text = _text("provider_note")
 _edited()
 _serial += 1
 var serial := _serial
 var selected_id := str(provider.get("id", "custom"))
 _set_busy(true)
 _status.text = _text("loading")
 _request.call("settings_get", {"provider": selected_id}, func(response: Dictionary):
  if not _alive(serial): return
  _set_busy(false)
  if response.get("ok", false) and response.get("settings") is Dictionary:
   # Preview the selected profile without saving it or exposing its saved key.
   _populate(response.settings)
   _status.text = _text("edited")
  else:
   _status.text = _error(response)
 )
