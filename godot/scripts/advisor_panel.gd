extends RefCounted

const L = preload("res://scripts/locale.gd")
const Reports = preload("res://scripts/reports.gd")
signal details_loaded(details: Dictionary)
var host: Control
var window: Window
var generation := 0
var request_generation := 0
var language := "en"
var choice: OptionButton
var question: TextEdit
var answer: TextEdit
var transcript: TextEdit
var record: VBoxContainer
var origin: Label
var ask: Button
var tabs: TabContainer
var portrait: TextureRect
var last_details: Dictionary = {}

func text(en: String, ru: String) -> String:
 return ru if language == "ru" else en

static func names_for_side(side: int, in_language: String) -> Array:
 if in_language == "ru":
  return ["Джордж Шульц", "Джин Киркпатрик", "Уильям Кейси", "Каспар Уайнбергер"] if side == 0 else ["Андрей Громыко", "Константин Черненко", "Юрий Андропов", "Дмитрий Устинов"]
 return ["George Shultz", "Jeane Kirkpatrick", "William Casey", "Caspar Weinberger"] if side == 0 else ["Andrei Gromyko", "Konstantin Chernenko", "Yuri Andropov", "Dmitri Ustinov"]

func open(parent: Control) -> void:
 generation += 1
 request_generation += 1
 host = parent
 language = L.language
 var body: VBoxContainer = host._dialog(L.text("advisor"), Vector2i(840, 750))
 window = host.popup
 var row := HBoxContainer.new()
 portrait = TextureRect.new()
 portrait.custom_minimum_size = Vector2(75, 90)
 portrait.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
 portrait.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
 row.add_child(portrait)
 choice = OptionButton.new()
 choice.name = "AdvisorChoice"
 var side := int(host.state.side)
 var names: Array = names_for_side(side, language)
 for name in names: choice.add_item(str(name))
 choice.item_selected.connect(_select_advisor)
 row.add_child(host._expand(choice))
 body.add_child(row)
 question = TextEdit.new()
 question.name = "AdvisorQuestion"
 question.custom_minimum_size.y = 86
 question.wrap_mode = TextEdit.LINE_WRAPPING_BOUNDARY
 question.placeholder_text = L.text("advisor_prompt")
 question.text = L.text("advisor_prompt")
 if host.state.get("selected_country") != null:
  question.text += " " + L.country(int(host.state.selected_country))
 body.add_child(question)
 tabs = TabContainer.new()
 tabs.name = "AdvisorTabs"
 tabs.size_flags_vertical = Control.SIZE_EXPAND_FILL
 body.add_child(tabs)
 var latest := VBoxContainer.new()
 latest.name = text("Latest answer", "Последний ответ")
 tabs.add_child(latest)
 answer = _reading_area("AdvisorAnswer")
 latest.add_child(answer)
 var conversation := VBoxContainer.new()
 conversation.name = text("Conversation", "Разговор")
 tabs.add_child(conversation)
 transcript = _reading_area("AdvisorTranscript")
 conversation.add_child(transcript)
 var calibration := ScrollContainer.new()
 calibration.name = text("Track record", "Точность прогнозов")
 calibration.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
 tabs.add_child(calibration)
 record = VBoxContainer.new()
 record.name = "AdvisorTrackRecord"
 record.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 record.add_theme_constant_override("separation", 12)
 calibration.add_child(record)
 origin = host._label("", 13, host.MUTED, true)
 body.add_child(origin)
 ask = host._button(L.text("ask"), _ask)
 ask.name = "AskAdvisorButton"
 body.add_child(ask)
 question.text_changed.connect(func(): ask.disabled = question.text.strip_edges().is_empty())
 _select_advisor(0)

func _reading_area(node_name: String) -> TextEdit:
 var area := TextEdit.new()
 area.name = node_name
 area.editable = false
 area.wrap_mode = TextEdit.LINE_WRAPPING_BOUNDARY
 area.size_flags_vertical = Control.SIZE_EXPAND_FILL
 area.custom_minimum_size.y = 200
 return area

func _valid(serial: int, owner: Window, index: int) -> bool:
 return serial == generation and is_instance_valid(owner) and host.popup == owner and is_instance_valid(choice) and choice.selected == index and L.language == language

func _select_advisor(index: int) -> void:
 request_generation += 1
 last_details = {}
 portrait.texture = load("res://assets/advisors/%s_%s.png" % ["usa" if int(host.state.side) == 0 else "ussr", index])
 answer.text = ""
 transcript.text = L.text("working")
 origin.text = ""
 host._clear(record)
 _load_details(true)

func _load_details(restore_answer: bool) -> void:
 var serial := generation
 var owner := window
 var index := choice.selected
 var request_serial := request_generation
 host._command("advisor_history", {"index": index, "language": language}, func(response):
  if not _valid(serial, owner, index) or request_serial != request_generation: return
  if not response.get("ok", false):
   transcript.text = str(response.get("error", {}).get("message_ru" if language == "ru" else "message", L.text("connection_error")))
   host._clear(record)
   record.add_child(host._label(transcript.text, 16, host.MUTED, true))
   return
  last_details = response.get("history", {})
  _render_details()
  if restore_answer:
   var history: Array = last_details.get("history", [])
   for i in range(history.size() - 1, -1, -1):
    if history[i].get("role") == "assistant":
     answer.text = str(history[i].get("content", ""))
     origin.text = text("Previous answer from this campaign.", "Предыдущий ответ в этой партии.")
     break
  details_loaded.emit(last_details)
 , true)

func _ask() -> void:
 if question.text.strip_edges().is_empty(): return
 request_generation += 1
 var serial := generation
 var owner := window
 var index := choice.selected
 var request_serial := request_generation
 ask.disabled = true
 choice.disabled = true
 question.editable = false
 tabs.current_tab = 0
 answer.text = L.text("thinking")
 origin.text = ""
 host._command("advisor", {"index": index, "question": question.text, "language": language}, func(response):
  if not _valid(serial, owner, index) or request_serial != request_generation: return
  ask.disabled = question.text.strip_edges().is_empty()
  choice.disabled = false
  question.editable = true
  if response.get("ok", false):
   var result: Dictionary = response.get("advice", {})
   answer.text = str(result.get("text", ""))
   origin.text = str(result.get("status", L.text("model") if result.get("used_model", false) else L.text("offline")))
   if result.get("year") != null:
    origin.text += "   ·   " + str(int(result.year))
   if result.get("country_id") != null:
    origin.text += "   ·   " + L.country(int(result.country_id))
  else:
   answer.text = str(response.get("error", {}).get("message_ru" if language == "ru" else "message", L.text("connection_error")))
  _load_details(false)
  host.advisor_answered.emit(response)
 , true)

func _render_details() -> void:
 var parts: Array[String] = []
 for message in last_details.get("history", []):
  var speaker: String = text("You", "Вы") if message.get("role") == "user" else choice.get_item_text(choice.selected)
  parts.append(speaker + "\n" + str(message.get("content", "")))
 transcript.text = "\n\n────────────────────────\n\n".join(parts) if not parts.is_empty() else text("No conversation yet. Ask a question about the selected country.", "Разговор ещё не начат. Задайте вопрос о выбранной стране.")
 host._clear(record)
 record.add_child(host._label(str(last_details.get("status_ru" if language == "ru" else "status", "")), 17, host.PAPER, true))
 var stats: Dictionary = last_details.get("statistics", {})
 var rows: Array = [
  [text("Resolved forecasts", "Проверено прогнозов"), str(int(stats.get("resolved", 0)))],
  [text("Correct forecasts", "Верных прогнозов"), str(int(stats.get("hits", 0)))],
  [text("Awaiting next year", "Ожидают следующего года"), str(int(stats.get("open", 0)))],
  [text("Hit rate", "Доля верных прогнозов"), _percent(stats.get("hit_rate"))],
  [text("Average confidence", "Средняя уверенность"), _percent(stats.get("mean_confidence"))],
  [text("Calibration error (0 is best)", "Ошибка оценки уверенности (0 — лучше)"), "—" if stats.get("brier") == null else String.num(float(stats.brier), 3)]
 ]
 Reports._table(host, record, [text("Measure", "Показатель"), L.text("value")], rows)
 record.add_child(host._label(text("Forecasts concern changes in a country's opinion of us. They are checked against the next year's actual position. More evidence is needed before judging an advisor's reliability.", "Прогнозы касаются изменений отношения страны к нам. Они проверяются по реальной обстановке следующего года. Для оценки надёжности советника нужна достаточная история прогнозов."), 14, host.MUTED, true))
 for group in ["pending", "recent"]:
  var items: Array = last_details.get(group, [])
  if items.is_empty(): continue
  record.add_child(HSeparator.new())
  record.add_child(host._label(text("Pending forecasts", "Ожидают проверки") if group == "pending" else text("Recent results", "Последние результаты"), 18, Color("eddaa8")))
  for item in items:
   record.add_child(host._label(str(item.get("summary_ru" if language == "ru" else "summary_en", "")), 15, host.PAPER, true))

func _percent(value) -> String:
 return "—" if value == null else String.num(float(value) * 100.0, 0) + "%"
