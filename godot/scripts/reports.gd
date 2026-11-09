extends RefCounted

const L = preload("res://scripts/locale.gd")
const Chart = preload("res://scripts/report_chart.gd")

static func wording(row: Dictionary, key: String) -> String:
 return str(row.get(key + "_ru" if L.language == "ru" else key, row.get(key, "")))

static func show_report(host: Control, kind: String, displayed: Callable = Callable()) -> void:
 var title: String = str({"country": L.text("country_report"), "scores": L.text("scores"), "objectives": L.text("objectives")}.get(kind, ""))
 var body: VBoxContainer = host._dialog(title, Vector2i(940, 740))
 var window: Window = host.popup
 var message: Label = host._label(L.text("working"), 17, host.MUTED, true)
 body.add_child(message)
 var args := {"kind": kind}
 if kind == "country":
  args.country_id = int(host.state.get("selected_country", host.state.get("side", 0))) if host.state.get("selected_country") != null else int(host.state.get("side", 0))
 host._command("report", args, func(response):
  if not is_instance_valid(window) or host.popup != window: return
  if not response.get("ok", false):
   message.text = wording(response.get("error", {}), "message")
   return
  if int(response.get("revision", -1)) != host.revision:
   message.text = L.text("report_changed")
   return
  message.queue_free()
  var report: Dictionary = response.get("report", {})
  match kind:
   "scores": _scores(host, body, report)
   "objectives": _objectives(host, body, report)
   "country": _country(host, body, report)
  if displayed.is_valid(): displayed.call(report)
 , true)

static func scroll_column(parent: Control) -> VBoxContainer:
 var scroll := ScrollContainer.new()
 scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
 scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
 scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 parent.add_child(scroll)
 var column := VBoxContainer.new()
 column.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 column.add_theme_constant_override("separation", 12)
 scroll.add_child(column)
 return column

static func _chart(host: Control, parent: Control, years: Array, series: Array) -> Control:
 if series.size() > 1:
  var legend := HFlowContainer.new()
  legend.add_theme_constant_override("h_separation", 24)
  parent.add_child(legend)
  for index in range(series.size()):
   legend.add_child(host._label("●  " + wording(series[index], "label"), 15, Chart.COLORS[index % Chart.COLORS.size()]))
 var chart: Control = Chart.new()
 chart.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 parent.add_child(chart)
 chart.set_data(years, series, not host.reduced_motion)
 return chart

static func _table(host: Control, parent: Control, headings: Array, rows: Array) -> void:
 var table := GridContainer.new()
 table.columns = headings.size()
 table.size_flags_horizontal = Control.SIZE_EXPAND_FILL
 table.add_theme_constant_override("h_separation", 26)
 table.add_theme_constant_override("v_separation", 10)
 for heading in headings:
  table.add_child(host._expand(host._label(str(heading), 14, host.MUTED, true)))
 for row in rows:
  for cell in row:
   table.add_child(host._expand(host._label(str(cell), 16, host.PAPER, true)))
 parent.add_child(table)

static func _scores(host: Control, body: VBoxContainer, report: Dictionary) -> void:
 var content := scroll_column(body)
 if report.get("nuclear", false):
  content.add_child(host._label(L.text("nuclear_end"), 20, Color("e6ac94"), true))
 var rows: Array = []
 var series: Array = []
 for row in report.get("rows", []):
  rows.append([L.country(int(row.side)), int(row.standing), int(row.delta), int(row.get("objective_bonus", 0))])
  series.append({"label": L.country(int(row.side)), "label_ru": L.country(int(row.side)), "values": row.get("history", [])})
 _table(host, content, [L.text("side"), L.text("score"), L.text("year_delta"), L.text("objective_bonus")], rows)
 content.add_child(host._label(L.text("score_history"), 19, host.MUTED))
 _chart(host, content, report.get("years", []), series)
 content.add_child(host._label(L.text("score_explanation"), 15, host.MUTED, true))

static func _objectives(host: Control, body: VBoxContainer, report: Dictionary) -> void:
 var content := scroll_column(body)
 content.add_child(host._label(L.text("objectives_help"), 17, host.MUTED, true))
 if report.get("void", false):
  content.add_child(host._label(L.text("nuclear_end"), 18, Color("e6ac94"), true))
 content.add_child(host._label(L.text("objective_bonus") + ": " + str(int(report.get("bonus", 0))), 22, Color("eddaa8")))
 for row in report.get("rows", []):
  content.add_child(HSeparator.new())
  var held: bool = bool(row.get("met", false))
  var title := ("✓ " if held else "○ ") + wording(row, "title")
  content.add_child(host._label(title, 19, Color("b5d8bd") if held else host.PAPER, true))
  content.add_child(host._label(wording(row, "detail"), 16, host.PAPER, true))
  content.add_child(host._label(wording(row, "progress") + "   ·   " + L.text("reward") + ": " + str(int(row.get("reward", 0))), 15, host.MUTED, true))

static func _country(host: Control, body: VBoxContainer, report: Dictionary) -> void:
 var country: Dictionary = report.get("country", {})
 body.add_child(host._label(L.country(int(country.get("id", 0))), 23, Color("eddaa8")))
 var tabs := TabContainer.new()
 tabs.name = "CountryReportTabs"
 tabs.size_flags_vertical = Control.SIZE_EXPAND_FILL
 body.add_child(tabs)
 var current := VBoxContainer.new()
 current.name = L.text("current_position")
 tabs.add_child(current)
 var data := scroll_column(current)
 var rows: Array = []
 for row in report.get("rows", []):
  var value := wording(row, "value_text")
  if value.is_empty(): value = str(row.get("value", ""))
  rows.append([wording(row, "label"), value])
 _table(host, data, [L.text("indicator"), L.text("value")], rows)
 var history_tab := VBoxContainer.new()
 history_tab.name = L.text("history")
 tabs.add_child(history_tab)
 var history_column := scroll_column(history_tab)
 var history: Dictionary = report.get("history", {})
 var series: Array = history.get("series", []).filter(func(line): return line.get("available", true))
 var years: Array = history.get("years", [])
 var selector := OptionButton.new()
 selector.name = "HistorySeries"
 for line in series:
  selector.add_item(wording(line, "label"))
 history_column.add_child(selector)
 var chart := _chart(host, history_column, years, [series[0]] if not series.is_empty() else [])
 var values := VBoxContainer.new()
 history_column.add_child(values)
 var show_values := func(index):
  host._clear(values)
  if index < 0 or index >= series.size(): return
  chart.set_data(years, [series[index]], not host.reduced_motion)
  var history_rows: Array = []
  var points: Array = series[index].get("values", [])
  for i in range(mini(years.size(), points.size())):
   history_rows.append([str(int(years[i])), String.num(float(points[i]), 1) if points[i] != null else "—"])
  _table(host, values, [L.text("year"), L.text("value")], history_rows)
 selector.item_selected.connect(show_values)
 if not series.is_empty(): show_values.call(0)
 var encyclopedia: Array = report.get("encyclopedia", [])
 if not encyclopedia.is_empty():
  var info_tab := VBoxContainer.new()
  info_tab.name = L.text("country_profile")
  tabs.add_child(info_tab)
  var info := scroll_column(info_tab)
  var information: Array = []
  for row in encyclopedia:
   information.append([wording(row, "label"), wording(row, "value_text")])
  _table(host, info, [L.text("indicator"), L.text("value")], information)
