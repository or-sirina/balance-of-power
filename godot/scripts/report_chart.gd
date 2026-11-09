extends Control

const L = preload("res://scripts/locale.gd")
const COLORS = [Color("83bad5"), Color("e4a69b"), Color("bdd5a5"), Color("ecd396")]
var years: Array = []
var series: Array = []
var reveal := 1.0
var hover_index := -1
var lo := 0.0
var hi := 1.0
var animation: Tween

func set_data(categories: Array, lines: Array, animate: bool = true) -> void:
 years = categories.duplicate()
 series = lines.duplicate(true)
 lo = 0.0
 hi = 0.0
 for line in series:
  for value in line.get("values", []):
   if value == null: continue
   lo = minf(lo, float(value))
   hi = maxf(hi, float(value))
 if is_equal_approx(lo, hi):
  lo -= 1.0
  hi += 1.0
 var padding := (hi - lo) * 0.08
 lo -= padding
 hi += padding
 if animation: animation.kill()
 reveal = 0.0 if animate else 1.0
 if animate and is_inside_tree():
  animation = create_tween()
  animation.tween_property(self, "reveal", 1.0, 0.45).set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_OUT)
  animation.finished.connect(queue_redraw)
 queue_redraw()

func _ready() -> void:
 custom_minimum_size = Vector2(400, 260)
 mouse_filter = Control.MOUSE_FILTER_STOP
 resized.connect(queue_redraw)
 mouse_exited.connect(func(): hover_index = -1; queue_redraw())

func _process(_delta: float) -> void:
 if reveal < 1.0: queue_redraw()

func _plot() -> Rect2:
 return Rect2(68, 20, maxf(1, size.x - 90), maxf(1, size.y - 58))

func _point(index: int, value: float) -> Vector2:
 var rect := _plot()
 var fraction := float(index) / maxf(1.0, years.size() - 1.0)
 return Vector2(rect.position.x + fraction * rect.size.x, rect.end.y - (value - lo) / (hi - lo) * rect.size.y)

func _draw() -> void:
 var font := ThemeDB.fallback_font
 var rect := _plot()
 draw_rect(Rect2(Vector2.ZERO, size), Color("193543"))
 if years.is_empty() or series.is_empty():
  draw_string(font, Vector2(24, 40), "Истории пока нет" if L.language == "ru" else "No history yet", HORIZONTAL_ALIGNMENT_LEFT, -1, 16, Color("b2c3c9"))
  return
 for tick in range(5):
  var fraction := float(tick) / 4.0
  var y := rect.end.y - fraction * rect.size.y
  draw_line(Vector2(rect.position.x, y), Vector2(rect.end.x, y), Color(0.65, 0.76, 0.8, 0.15))
  var number := String.num(lo + (hi - lo) * fraction, 0)
  draw_string(font, Vector2(5, y + 5), number, HORIZONTAL_ALIGNMENT_RIGHT, 53, 13, Color("b2c3c9"))
 for index in range(years.size()):
  var x := _point(index, 0).x
  var label := str(int(years[index]))
  draw_string(font, Vector2(x - 22, rect.end.y + 25), label, HORIZONTAL_ALIGNMENT_CENTER, 44, 13, Color("b2c3c9"))
 var shown := maxf(0.0, (years.size() - 1) * reveal)
 for s in range(series.size()):
  var values: Array = series[s].get("values", [])
  var color: Color = COLORS[s % COLORS.size()]
  var points := PackedVector2Array()
  for index in range(mini(years.size(), values.size())):
   if values[index] == null or index > ceilf(shown): continue
   var point := _point(index, float(values[index]))
   if index > shown and index > 0 and values[index - 1] != null:
    point = _point(index - 1, float(values[index - 1])).lerp(point, shown - floorf(shown))
   points.append(point)
  if points.size() > 1:
   draw_polyline(points, color, 2.5, true)
  elif points.size() == 1:
   draw_circle(points[0], 3.5, color)
 if hover_index >= 0 and reveal >= 1.0:
  var x := _point(hover_index, 0).x
  draw_line(Vector2(x, rect.position.y), Vector2(x, rect.end.y), Color("e5d5a8"), 1.0)
  var lines: Array[String] = [str(int(years[hover_index]))]
  var width := 0.0
  for s in range(series.size()):
   var values: Array = series[s].get("values", [])
   if hover_index >= values.size() or values[hover_index] == null: continue
   var value: float = float(values[hover_index])
   draw_circle(_point(hover_index, value), 4.0, COLORS[s % COLORS.size()])
   var label := str(series[s].get("label_ru" if L.language == "ru" else "label", ""))
   lines.append(label + ": " + String.num(value, 1))
  for line in lines:
   width = maxf(width, font.get_string_size(line, HORIZONTAL_ALIGNMENT_LEFT, -1, 14).x)
  var tooltip_size := Vector2(width + 24, lines.size() * 21 + 12)
  var at := Vector2(clampf(x + 14, 4, maxf(4, size.x - tooltip_size.x - 4)), 24)
  var box := StyleBoxFlat.new()
  box.bg_color = Color("102733")
  box.border_color = Color("567280")
  box.set_border_width_all(1)
  box.set_corner_radius_all(4)
  draw_style_box(box, Rect2(at, tooltip_size))
  for index in range(lines.size()):
   draw_string(font, at + Vector2(12, 22 + index * 21), lines[index], HORIZONTAL_ALIGNMENT_LEFT, -1, 14, Color("e7eadf"))

func _gui_input(event: InputEvent) -> void:
 if event is InputEventMouseMotion and not years.is_empty():
  var rect := _plot()
  hover_index = clampi(roundi((event.position.x - rect.position.x) / rect.size.x * (years.size() - 1)), 0, years.size() - 1) if rect.has_point(event.position) else -1
  queue_redraw()
