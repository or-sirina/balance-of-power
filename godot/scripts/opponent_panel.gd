extends RefCounted

const L = preload("res://scripts/locale.gd")
var host: Control
var window: Window
var status: Label
var entries: ItemList
var detail: TextEdit
var rows: Array = []

func text(en: String, ru: String) -> String:
 return ru if L.language == "ru" else en

func show(parent: Control) -> void:
 host = parent
 var body: VBoxContainer = host._dialog(text("Opponent decisions", "Решения соперника"), Vector2i(800, 610))
 window = host.popup
 status = host._label(text("Loading recorded decisions…", "Загрузка записанных решений…"), 14, host.MUTED, true)
 body.add_child(status)
 body.add_child(host._label(text("Recorded explanations appear after the year ends. The current year's plan remains hidden.", "Записанные пояснения доступны после завершения года. План текущего года остаётся скрытым."), 14, host.MUTED, true))
 entries = ItemList.new()
 entries.name = "OpponentDecisionYears"
 entries.custom_minimum_size.y = 140
 body.add_child(entries)
 detail = TextEdit.new()
 detail.name = "OpponentDecisionDetail"
 detail.editable = false
 detail.wrap_mode = TextEdit.LINE_WRAPPING_BOUNDARY
 detail.size_flags_vertical = Control.SIZE_EXPAND_FILL
 detail.custom_minimum_size.y = 240
 body.add_child(detail)
 entries.item_selected.connect(_select)
 var refresh: Button = host._button(text("Refresh", "Обновить"), _refresh)
 refresh.name = "RefreshOpponentDecisions"
 body.add_child(refresh)
 _refresh()

func _refresh() -> void:
 host._command("opponent_log", {}, func(response):
  if not is_instance_valid(window) or not is_instance_valid(entries): return
  if not response.get("ok", false):
   status.text = text("Could not load the record. Try refreshing.", "Не удалось загрузить журнал. Попробуйте обновить.")
   return
  var log: Dictionary = response.get("opponent_log", {})
  var code := str(log.get("status", "unconfigured"))
  var messages := {
   "no_game": text("Start a campaign to see the opponent's decisions.", "Начните кампанию, чтобы увидеть решения соперника."),
   "builtin": text("This campaign uses the built-in opponent.", "В этой кампании играет встроенный соперник."),
   "unconfigured": text("No model opponent is configured. The built-in AI plays instead.", "Соперник на базе модели не настроен. Играет встроенный ИИ."),
   "heuristic_not_configured": text("No model opponent is configured. The built-in AI plays instead.", "Соперник на базе модели не настроен. Играет встроенный ИИ."),
   "offline": text("The built-in AI is enabled in AI settings.", "В настройках ИИ включён встроенный соперник."),
   "heuristic_model_unavailable": text("The model is unavailable. The built-in AI is playing.", "Модель недоступна. Играет встроенный ИИ."),
   "heuristic_fallback": text("The last model move was unavailable; the built-in AI played instead.", "Последний ход модели недоступен; вместо неё сходил встроенный ИИ."),
   "model": text("The model opponent is playing.", "Играет соперник на базе модели.")
  }
  status.text = str(messages.get(code, text("Recorded opponent decisions", "Журнал решений соперника")))
  var stats: Dictionary = log.get("stats", {})
  if not stats.is_empty():
   status.text += text("\nModel moves: %d · Built-in moves: %d · Actions: %d", "\nХоды модели: %d · Ходы встроенного ИИ: %d · Действия: %d") % [int(stats.get("llm", 0)), int(stats.get("fallback", 0)), int(stats.get("actions", 0))]
  if not str(log.get("last_error", "")).is_empty():
   status.text += text("\nThe last model request could not be completed.", "\nПоследний запрос к модели не удалось выполнить.")
  rows = log.get("entries", []).duplicate()
  rows.reverse()
  entries.clear()
  for row in rows:
   entries.add_item(str(row.get("year", "")) + text(" · %d actions", " · действий: %d") % row.get("actions", []).size())
  if rows.is_empty():
   detail.text = text("No completed-year decisions have been recorded yet.", "Решений за завершённые годы пока нет.")
  else:
   entries.select(0)
   _select(0)
 , true)

func _select(index: int) -> void:
 if index < 0 or index >= rows.size(): return
 var row: Dictionary = rows[index]
 var lines: Array[String] = [str(row.get("year", "")), "", str(row.get("reasoning", "")) if not str(row.get("reasoning", "")).is_empty() else text("No explanation was recorded.", "Пояснение не записано."), "", text("Actions", "Действия")]
 var actions: Array = row.get("actions", [])
 if actions.is_empty(): lines.append(text("No policy changes recorded.", "Изменений политики не записано."))
 for action in actions:
  lines.append("• " + L.policy(int(action.action)) + " · " + L.country(int(action.target)) + text(" · step %d", " · ступень %d") % int(action.value))
 detail.text = "\n".join(lines)
