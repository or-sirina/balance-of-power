extends Control

signal country_selected(country_id: int)
const L = preload("res://scripts/locale.gd")
var polygons: Array = []
var countries: Array = []
var selected := -1
var hovered := -1
var mode := 0
var report_values: Dictionary = {}
var zoom := 1.0
var pan := Vector2.ZERO
var dragging := false
var reduced_motion := false
var selection_glow := 0.0
var selection_tween: Tween

func _ready() -> void:
 mouse_filter = Control.MOUSE_FILTER_STOP
 focus_mode = Control.FOCUS_ALL
 clip_contents = true
 var data: Array = JSON.parse_string(FileAccess.get_file_as_string("res://assets/map.json"))
 for entry in data:
  var points := PackedVector2Array()
  for point in entry.points:
   points.append(Vector2(point[0], point[1]))
  var vertices := PackedVector2Array()
  var indices := PackedInt32Array()
  for triangle in entry.triangles:
   for point in triangle:
    indices.append(vertices.size())
    vertices.append(Vector2(point[0], point[1]))
  var outline := points.duplicate()
  if not points.is_empty(): outline.append(points[0])
  polygons.append({"id": int(entry.id), "points": points, "vertices": vertices, "indices": indices, "outline": outline})
 resized.connect(queue_redraw)
 mouse_exited.connect(func(): hovered = -1; queue_redraw())

func update_world(data: Array, selection: int) -> void:
 countries = data
 if selected != selection:
  selected = selection
  if selection_tween:
   selection_tween.kill()
  selection_glow = 1.0 if not reduced_motion else 0.0
  if not reduced_motion:
   selection_tween = create_tween()
   selection_tween.tween_property(self, "selection_glow", 0.0, 0.65)
   selection_tween.tween_callback(queue_redraw)
 queue_redraw()

func apply_report(report: Dictionary) -> void:
 report_values.clear()
 for row in report.get("countries", []):
  report_values[int(row.id)] = row
 queue_redraw()

func _process(_delta: float) -> void:
 if selection_glow > 0:
  queue_redraw()

func fit_map() -> void:
 zoom = 1.0
 pan = Vector2.ZERO
 queue_redraw()

func transform_map() -> Transform2D:
 var scale_value := minf(size.x / 960.0, size.y / 490.0) * 0.95 * zoom
 var offset := (size - Vector2(948, 483) * scale_value) / 2.0 + pan
 return Transform2D(0, Vector2.ONE * scale_value, 0, offset)

func tint(id: int) -> Color:
 if report_values.has(id):
  var exact := Color(str(report_values[id].get("color", "#babba4")))
  return exact.lightened(0.13) if id == hovered else exact
 if id == 0:
  return Color("547d9c")
 if id == 1:
  return Color("ad6863")
 var base := Color("babba4")
 if id < countries.size():
  var c: Dictionary = countries[id]
  if mode == 1:
   return Color("617f82").lerp(Color("e7d2a5"), clampf(float(c.get("prestige", 0)) / 130.0, 0, 1))
  var opinion := float(c.get("standing", 0)) / 127.0
  base = base.lerp(Color("91b9ab") if opinion >= 0 else Color("bf7b70"), absf(opinion) * 0.9)
 if id == hovered:
  base = base.lightened(0.13)
 return base

func _draw() -> void:
 draw_rect(Rect2(Vector2.ZERO, size), Color("193b50"))
 var transform := transform_map()
 draw_set_transform_matrix(transform)
 var line_width := 1.0 / transform.get_scale().x
 for x in range(0, 949, 79):
  draw_line(Vector2(x, 0), Vector2(x, 483), Color(0.55, 0.7, 0.77, 0.07), line_width)
 for y in range(0, 484, 69):
  draw_line(Vector2(0, y), Vector2(948, y), Color(0.55, 0.7, 0.77, 0.07), line_width)
 for polygon in polygons:
  var points: PackedVector2Array = polygon.points
  if points.size() < 3:
   continue
  var fill := tint(polygon.id)
  RenderingServer.canvas_item_add_triangle_array(get_canvas_item(), polygon.indices, polygon.vertices, PackedColorArray([fill]))
  draw_polyline(polygon.outline, Color("365061"), line_width * 0.7, true)
 for polygon in polygons:
  if polygon.id == selected and polygon.points.size() >= 3:
   draw_polyline(polygon.outline, Color("f4df9d"), line_width * (2.4 + selection_glow * 2.5), true)
 draw_set_transform_matrix(Transform2D.IDENTITY)
 var font := ThemeDB.fallback_font
 if hovered >= 0:
  var label := L.country(hovered)
  if report_values.has(hovered):
   var value := str(report_values[hovered].get("label_ru" if L.language == "ru" else "label", ""))
   if not value.is_empty(): label += ": " + value
  var extent := font.get_string_size(label, HORIZONTAL_ALIGNMENT_LEFT, -1, 17)
  var at := get_local_mouse_position() + Vector2(16, -34)
  at.x = clampf(at.x, 8, maxf(8, size.x - extent.x - 24))
  at.y = maxf(8, at.y)
  draw_style_box(_tooltip_box(), Rect2(at, extent + Vector2(20, 12)))
  draw_string(font, at + Vector2(10, 22), label, HORIZONTAL_ALIGNMENT_LEFT, -1, 17, Color("f2f1df"))

func _tooltip_box() -> StyleBoxFlat:
 var box := StyleBoxFlat.new()
 box.bg_color = Color("132b3d")
 box.set_corner_radius_all(4)
 return box

func hit(position: Vector2) -> int:
 var map_point := transform_map().affine_inverse() * position
 for i in range(polygons.size() - 1, -1, -1):
  if Geometry2D.is_point_in_polygon(map_point, polygons[i].points):
   return polygons[i].id
 return -1

func _gui_input(event: InputEvent) -> void:
 if event is InputEventMouseMotion:
  if dragging:
   pan += event.relative
  hovered = hit(event.position)
  queue_redraw()
 elif event is InputEventMouseButton:
  if event.button_index == MOUSE_BUTTON_MIDDLE:
   dragging = event.pressed
  elif event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
   grab_focus()
   var country := hit(event.position)
   if country >= 0:
    country_selected.emit(country)
  elif event.pressed and event.button_index in [MOUSE_BUTTON_WHEEL_UP, MOUSE_BUTTON_WHEEL_DOWN]:
   var before: Vector2 = transform_map().affine_inverse() * event.position
   zoom = clampf(zoom * (1.16 if event.button_index == MOUSE_BUTTON_WHEEL_UP else 0.86), 1.0, 5.0)
   pan += event.position - transform_map() * before
   queue_redraw()
  accept_event()
 elif event is InputEventKey and event.pressed:
  if event.keycode in [KEY_LEFT, KEY_RIGHT, KEY_UP, KEY_DOWN]:
   var next := posmod(selected + (-1 if event.keycode in [KEY_LEFT, KEY_UP] else 1), 80)
   country_selected.emit(next)
   accept_event()
