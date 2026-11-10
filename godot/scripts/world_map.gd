extends Control

signal country_selected(country_id: int)
signal city_selected(city: Dictionary)
signal event_selected(event: Dictionary)
signal route_selected(route: Dictionary)
var route_hit_regions: Array = []
var hovered_route: Dictionary = {}
var event_hit_regions: Array = []
signal city_hovered(city: Dictionary)
const CityModels = preload("res://scripts/city_models.gd")
var map_state: Dictionary = {}
var anchor_cache: Dictionary = {}
var geography: Dictionary = {}
var map_dimensions := Vector2(1200, 600)
const MAX_ZOOM := 24.0
var cities: Array = []
var routes: Array = []
var map_events: Array = []
var city_hit_regions: Array = []
var hovered_city: Dictionary = {}
var layers := {"cities": true, "roads": true, "events": true, "labels": true}

func apply_map_state(data: Dictionary) -> void:
 map_state = data
 cities = data.get("cities", [])
 routes = data.get("routes", [])
 map_events = data.get("events", [])
 queue_redraw()

func set_layer(layer: String, enabled: bool) -> void:
 layers[layer] = enabled
 if not enabled:
  if layer == "cities":
   city_hit_regions.clear()
   hovered_city.clear()
  elif layer == "roads":
   route_hit_regions.clear()
   hovered_route.clear()
  elif layer == "events": event_hit_regions.clear()
 queue_redraw()

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
var atmosphere_time := 0.0
var atmosphere_frame := 0.0
var selection_tween: Tween
var colorblind := false:
 set(value):
  colorblind = value
  queue_redraw()
var relief_enabled := true:
 set(value):
  relief_enabled = value
  queue_redraw()
var safe_colors: Dictionary = {}
var relief_layer: TextureRect
var foreground: Control

class Foreground extends Control:
 var chart: Control
 func _draw() -> void:
  chart.draw_foreground(self)

func _ready() -> void:
 mouse_filter = Control.MOUSE_FILTER_STOP
 focus_mode = Control.FOCUS_ALL
 clip_contents = true
 safe_colors = JSON.parse_string(FileAccess.get_file_as_string("res://assets/color_safe.json"))
 relief_layer = TextureRect.new()
 relief_layer.mouse_filter = Control.MOUSE_FILTER_IGNORE
 relief_layer.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS
 if ResourceLoader.exists("res://assets/geo_relief.png"):
  relief_layer.texture = load("res://assets/geo_relief.png")
 relief_layer.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
 var shade := ShaderMaterial.new()
 shade.shader = preload("res://scripts/relief.gdshader")
 if ResourceLoader.exists("res://assets/geo_terrain_mask.png"):
  shade.set_shader_parameter("land_mask", load("res://assets/geo_terrain_mask.png"))
 relief_layer.material = shade
 add_child(relief_layer)
 foreground = Foreground.new()
 foreground.chart = self
 foreground.mouse_filter = Control.MOUSE_FILTER_IGNORE
 foreground.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
 add_child(foreground)
 if FileAccess.file_exists("res://assets/map_metadata.json"):
  geography = JSON.parse_string(FileAccess.get_file_as_string("res://assets/map_metadata.json"))
  map_dimensions = Vector2(float(geography.get("width",1200)),float(geography.get("height",600)))
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
  var holes: Array = []
  for ring in entry.get("holes", []):
   var hole := PackedVector2Array()
   for point in ring: hole.append(Vector2(point[0],point[1]))
   holes.append(hole)
  polygons.append({"id": int(entry.id), "points": points, "holes": holes, "vertices": vertices, "indices": indices, "outline": outline})
 resized.connect(queue_redraw)
 mouse_exited.connect(func(): hovered = -1; hovered_city.clear(); hovered_route.clear(); queue_redraw())

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
 if not reduced_motion and zoom >= 2.3 and layers.get("events",true):
  atmosphere_time += _delta
  atmosphere_frame += _delta
  if atmosphere_frame >= 1.0/12.0:
   atmosphere_frame = 0.0
   if is_instance_valid(foreground): foreground.queue_redraw()
 if selection_glow > 0:
  queue_redraw()

func fit_map() -> void:
 zoom = 1.0
 pan = Vector2.ZERO
 queue_redraw()

func transform_map() -> Transform2D:
 var scale_value := minf(size.x / map_dimensions.x, size.y / map_dimensions.y) * 0.95 * zoom
 var offset := (size - map_dimensions * scale_value) / 2.0 + pan
 return Transform2D(0, Vector2.ONE * scale_value, 0, offset)

func tint(id: int) -> Color:
 if id < 0: return Color("8c998b")
 if report_values.has(id):
  var exact := presentation_color(str(report_values[id].get("color", "#babba4")))
  return exact.lightened(0.13) if id == hovered else exact
 if id == 0:
  return presentation_color("#547d9c")
 if id == 1:
  return presentation_color("#ad6863")
 var base := Color("babba4")
 if id >= 0 and id < countries.size():
  var c: Dictionary = countries[id]
  if mode == 1:
   return Color("617f82").lerp(Color("e7d2a5"), clampf(float(c.get("prestige", 0)) / 130.0, 0, 1))
  var opinion := float(c.get("standing", 0)) / 127.0
  var friendly := Color("82afdc") if colorblind else Color("91b9ab")
  var hostile := Color("f0aa6e") if colorblind else Color("bf7b70")
  base = base.lerp(friendly if opinion >= 0 else hostile, absf(opinion) * 0.9)
 if id == hovered:
  base = base.lightened(0.13)
 return base

func presentation_color(value: String) -> Color:
 return Color(str(safe_colors.get(value.to_lower(), value))) if colorblind else Color(value)

func _draw() -> void:
 draw_rect(Rect2(Vector2.ZERO, size), Color("193747"))
 var transform := transform_map()
 draw_set_transform_matrix(transform)
 var line_width := 1.0 / transform.get_scale().x
 # Graticule follows the geography's actual longitude/latitude bounds.
 var bounds: Array = geography.get("bounds",[-180,-60,180,85])
 for longitude in range(-180,181,30):
  var x := (float(longitude)-float(bounds[0]))/(float(bounds[2])-float(bounds[0]))*map_dimensions.x
  draw_line(Vector2(x,0),Vector2(x,map_dimensions.y),Color(0.55,0.7,0.77,0.10),line_width)
 for latitude in range(-60,91,30):
  if latitude < float(bounds[1]) or latitude > float(bounds[3]): continue
  var y := (float(bounds[3])-float(latitude))/(float(bounds[3])-float(bounds[1]))*map_dimensions.y
  draw_line(Vector2(0,y),Vector2(map_dimensions.x,y),Color(0.55,0.7,0.77,0.10),line_width)
 for polygon in polygons:
  var points: PackedVector2Array = polygon.points
  if points.size() < 3:
   continue
  var fill := tint(polygon.id)
  RenderingServer.canvas_item_add_triangle_array(get_canvas_item(), polygon.indices, polygon.vertices, PackedColorArray([fill]))
  draw_polyline(polygon.outline, Color("365061"), line_width * 0.7, true)
  for ring in polygon.holes:
   var closed: PackedVector2Array = ring.duplicate()
   if not closed.is_empty(): closed.append(closed[0])
   draw_polyline(closed,Color("365061"),line_width*0.7,true)
 if is_instance_valid(relief_layer):
  relief_layer.visible = relief_enabled and relief_layer.texture != null
  relief_layer.position = transform.origin
  relief_layer.size = map_dimensions * transform.get_scale()
 if is_instance_valid(foreground): foreground.queue_redraw()

func draw_foreground(surface: Control) -> void:
 var transform := transform_map()
 surface.draw_set_transform_matrix(transform)
 var line_width := 1.0 / transform.get_scale().x
 for polygon in polygons:
  if selected >= 0 and polygon.id == selected and polygon.points.size() >= 3:
   surface.draw_polyline(polygon.outline, Color("f4df9d"), line_width * (2.4 + selection_glow * 2.5), true)
   for ring in polygon.holes:
    var closed: PackedVector2Array = ring.duplicate()
    if not closed.is_empty(): closed.append(closed[0])
    surface.draw_polyline(closed,Color("f4df9d"),line_width*2.4,true)
 surface.draw_set_transform_matrix(Transform2D.IDENTITY)
 draw_living_map(surface, transform)
 var font := ThemeDB.fallback_font
 if hovered >= 0 or not hovered_route.is_empty():
  var label := L.country(hovered) if hovered >= 0 else ""
  var country_status := scene_country(hovered)
  if not hovered_city.is_empty():
   var city_name := str(hovered_city.get("name_ru",hovered_city.get("name",""))) if L.language == "ru" else str(hovered_city.get("name",""))
   label = city_name + " · " + L.country(hovered)
   label += " · " + ("События относятся к стране" if L.language == "ru" else "Events represent the country")
  if not country_status.is_empty():
   label += " · " + str(country_status.get("insurgency_label_ru" if L.language == "ru" else "insurgency_label", ""))
  if report_values.has(hovered):
   var value := str(report_values[hovered].get("label_ru" if L.language == "ru" else "label", ""))
   if not value.is_empty(): label += ": " + value
  if not hovered_route.is_empty():
   label = L.country(int(hovered_route.actor))+" → "+L.country(int(hovered_route.target))+": "+str(hovered_route.get("label_ru" if L.language == "ru" else "label",""))+" · "+str(hovered_route.get("value_label_ru" if L.language == "ru" else "value_label",""))
  var extent := font.get_string_size(label, HORIZONTAL_ALIGNMENT_LEFT, -1, 17)
  var at := get_local_mouse_position() + Vector2(16, -34)
  at.x = clampf(at.x, 8, maxf(8, size.x - extent.x - 24))
  at.y = maxf(8, at.y)
  surface.draw_style_box(_tooltip_box(), Rect2(at, extent + Vector2(20, 12)))
  surface.draw_string(font, at + Vector2(10, 22), label, HORIZONTAL_ALIGNMENT_LEFT, -1, 17, Color("f2f1df"))

func _tooltip_box() -> StyleBoxFlat:
 var box := StyleBoxFlat.new()
 box.bg_color = Color("132b3d")
 box.set_corner_radius_all(4)
 return box

func hit(position: Vector2) -> int:
 var map_point := transform_map().affine_inverse() * position
 for i in range(polygons.size() - 1, -1, -1):
  if Geometry2D.is_point_in_polygon(map_point, polygons[i].points):
   var in_hole := false
   for ring in polygons[i].holes:
    if Geometry2D.is_point_in_polygon(map_point,ring):
     in_hole = true
     break
   if not in_hole: return maxi(-1,int(polygons[i].id))
 return -1

func _gui_input(event: InputEvent) -> void:
 if event is InputEventMouseMotion:
  if dragging:
   pan += event.relative
  hovered = hit(event.position)
  hovered_route = route_at(event.position)
  var next_city := city_at(event.position)
  if next_city != hovered_city:
   hovered_city = next_city
   city_hovered.emit(hovered_city)
  queue_redraw()
 elif event is InputEventMouseButton:
  if event.button_index == MOUSE_BUTTON_MIDDLE:
   dragging = event.pressed
  elif event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
   grab_focus()
   for region in event_hit_regions:
    if region.rect.has_point(event.position):
     event_selected.emit(region.event)
     country_selected.emit(int(region.event.country_id))
     accept_event()
     return
   var route := route_at(event.position)
   if not route.is_empty() and city_at(event.position).is_empty():
    route_selected.emit(route)
    accept_event()
    return
   var city := city_at(event.position)
   if not city.is_empty():
    city = city.duplicate()
    city["status"] = scene_country(int(city.get("country_id",-1)))
    city["events"] = map_events.filter(func(item): return int(item.get("country_id",-2)) == int(city.get("country_id",-1)))
    city_selected.emit(city)
   var country := int(city.get("country_id", hit(event.position)))
   if country >= 0:
    country_selected.emit(country)
    if event.double_click:
     focus_country(country)
  elif event.pressed and event.button_index in [MOUSE_BUTTON_WHEEL_UP, MOUSE_BUTTON_WHEEL_DOWN]:
   var before: Vector2 = transform_map().affine_inverse() * event.position
   zoom = clampf(zoom * (1.16 if event.button_index == MOUSE_BUTTON_WHEEL_UP else 0.86), 1.0, MAX_ZOOM)
   pan += event.position - transform_map() * before
   queue_redraw()
  accept_event()
 elif event is InputEventKey and event.pressed:
  if event.keycode == KEY_F:
   fit_map()
   accept_event()
  elif event.keycode in [KEY_PLUS, KEY_EQUAL, KEY_MINUS]:
   var center := transform_map().affine_inverse()*(size/2.0)
   zoom = clampf(zoom*(0.86 if event.keycode == KEY_MINUS else 1.16),1.0,MAX_ZOOM)
   pan += size/2.0-transform_map()*center
   queue_redraw()
   accept_event()
  elif event.keycode in [KEY_LEFT, KEY_RIGHT, KEY_UP, KEY_DOWN]:
   var next := posmod(selected + (-1 if event.keycode in [KEY_LEFT, KEY_UP] else 1), 80)
   country_selected.emit(next)
   accept_event()

func focus_country(id: int) -> void:
 var anchor := country_anchor(id)
 var extent := Vector2(100,70)
 # Focus the capital's landmass; overseas territories and date-line fragments
 # must not force a small country back out to a whole-world view.
 for polygon in polygons:
  if int(polygon.id) != id or not Geometry2D.is_point_in_polygon(anchor,polygon.points): continue
  var bounds := Rect2(polygon.points[0],Vector2.ZERO)
  for point in polygon.points: bounds = bounds.expand(point)
  extent = bounds.size
  break
 var fit_scale := minf(size.x/map_dimensions.x,size.y/map_dimensions.y)*0.95
 var target := minf(size.x/maxf(extent.x,12.0),size.y/maxf(extent.y,10.0))*0.65/fit_scale
 zoom = clampf(maxf(3.2,target),1.0,MAX_ZOOM)
 pan = Vector2.ZERO
 pan = size/2.0-transform_map()*anchor
 queue_redraw()

func country_anchor(id: int) -> Vector2:
 if anchor_cache.has(id): return anchor_cache[id]
 var anchors: Dictionary = geography.get("anchors",{})
 if anchors.has(str(id)):
  var point: Array = anchors[str(id)]
  anchor_cache[id] = Vector2(float(point[0]),float(point[1]))
  return anchor_cache[id]
 # Largest interior triangle is robust for concave and island countries.
 var best := Vector2.ZERO
 var area := -1.0
 for polygon in polygons:
  if int(polygon.id) != id: continue
  var vertices: PackedVector2Array = polygon.vertices
  for i in range(0, vertices.size()-2, 3):
   var a := vertices[i]
   var b := vertices[i+1]
   var c := vertices[i+2]
   var candidate := absf((b-a).cross(c-a))
   if candidate > area:
    area = candidate
    best = (a+b+c)/3.0
 anchor_cache[id] = best
 return best

func city_at(at: Vector2) -> Dictionary:
 for i in range(city_hit_regions.size()-1,-1,-1):
  if city_hit_regions[i].rect.has_point(at): return city_hit_regions[i].city
 return {}

func scene_country(id: int) -> Dictionary:
 for row in map_state.get("countries", []):
  if int(row.get("id", -1)) == id: return row
 return {}

func capital_city(id: int, source: Dictionary = {}) -> Dictionary:
 var city := source.duplicate()
 var capital: Dictionary = geography.get("capitals",{}).get(str(id),{})
 var anchor := country_anchor(id)
 city.merge({"id":id,"country_id":id,"x":anchor.x,"y":anchor.y,"name":capital.get("name",L.country(id)),"name_ru":capital.get("name_ru",capital.get("name",L.country(id))),"schematic":false,"location_semantics":"capital_anchor"},true)
 return city

func draw_living_map(surface: Control, transform: Transform2D) -> void:
 var font := ThemeDB.fallback_font
 var local_cities: Array = cities
 if local_cities.is_empty():
  local_cities = []
  for row in countries:
   var id := int(row.get("id", local_cities.size()))
   local_cities.append(capital_city(id))
 route_hit_regions.clear()
 if layers.get("roads",true):
  for route in grouped_routes():
   var actor := int(route.get("actor",-1))
   var target := int(route.get("target",-1))
   if actor < 0 or target < 0: continue
   # Detail view concentrates on the selected country's commitments.
   if selected >= 0 and actor != selected and target != selected: continue
   var a := transform * country_anchor(actor)
   var b := transform * country_anchor(target)
   var points := PackedVector2Array()
   var bend := Vector2(0,-minf(70,(b-a).length()*0.18))
   for step in range(25):
    var t := float(step)/24.0
    points.append(a.lerp(b,t)+bend*4.0*t*(1.0-t))
   route_hit_regions.append({"points":points,"route":route})
   var kind := str(route.get("kind",""))
   var ink := Color("c5c89c") if kind == "mixed" else Color("dfb76d") if "insurgent" in kind else Color("8cc7d0")
   surface.draw_polyline(points,Color(0.04,0.1,0.14,0.7),4.0,true)
   surface.draw_polyline(points,ink,1.4,true)
   var direction := (points[24]-points[23]).normalized()
   surface.draw_colored_polygon(PackedVector2Array([b,b-direction.rotated(0.5)*8,b-direction.rotated(-0.5)*8]),ink)
 city_hit_regions.clear()
 var unit := clampf(0.50+zoom*0.14,0.64,1.75)
 var occupied: Array[Rect2] = []
 # Labels use screen coordinates to remain readable through zoom.
 for source_city in local_cities:
  var id := int(source_city.get("country_id",source_city.get("id",0)))
  var city := capital_city(id,source_city)
  var at := transform * country_anchor(id)
  if not Rect2(Vector2(-50,-50),size+Vector2(100,100)).has_point(at): continue
  var important := id == selected or id == hovered or id < 2
  var status := scene_country(id)
  var active := int(status.get("insurgency",6)) <= 2 or int(status.get("event",0)) > 0
  if layers.get("cities",true) and (zoom >= 1.7 or important):
   CityModels.draw_city(surface,at,unit,id,id < 2,active)
   city_hit_regions.append({"rect":Rect2(at+Vector2(-18,-27)*unit,Vector2(37,39)*unit),"city":city})
  if layers.get("labels",true) and (zoom >= 2.8 or important):
   var text := str(city.get("name_ru",city.get("name",""))) if L.language == "ru" else str(city.get("name",""))
   var font_size := 14 if important else 12
   var extent := font.get_string_size(text,HORIZONTAL_ALIGNMENT_LEFT,-1,font_size)
   var rect := Rect2(at+Vector2(-extent.x/2,10*unit),extent+Vector2(8,5))
   var overlaps := false
   for previous in occupied:
    if previous.intersects(rect): overlaps = true; break
   if not overlaps or important:
    occupied.append(rect)
    var baseline := rect.position+Vector2(0,font_size)
    surface.draw_string_outline(font,baseline,text,HORIZONTAL_ALIGNMENT_LEFT,-1,font_size,4,Color("142d3a"))
    surface.draw_string(font,baseline,text,HORIZONTAL_ALIGNMENT_LEFT,-1,font_size,Color("ece7cf") if important else Color("ced7ce"))
 event_hit_regions.clear()
 if layers.get("events",true):
  var event_slots: Dictionary = {}
  for event in visible_map_events():
   var id := int(event.get("country_id",-1))
   if id < 0: continue
   var at := transform * country_anchor(id)
   if not Rect2(Vector2(-40,-40),size+Vector2(80,80)).has_point(at): continue
   var kind := str(event.get("kind",""))
   var ink := Color("df986b") if kind in ["civil_war","war","armed_attacks"] else Color("e5c67e")
   # Open warning chevrons sit apart from the architecture, rather than covering it.
   var slot := int(event_slots.get(id, 0))
   event_slots[id] = slot + 1
   var crest := at+Vector2(19,-17)*unit + Vector2(0, slot*27)
   event_hit_regions.append({"rect":Rect2(crest-Vector2(9,10),Vector2(20,25)),"event":event})
   if zoom >= 2.3:
    if kind in ["civil_war","insurgency","war"]:
     for plume in range(4):
      var drift := 0.0
      if not reduced_motion and id in [selected,hovered]: drift = sin(atmosphere_time*1.4+float(plume))*1.5
      var smoke_at := at+Vector2(14+plume*2+drift,-8-plume*5-absf(drift))*unit
      surface.draw_circle(smoke_at,(3.0+plume)*unit,Color(0.2,0.23,0.23,0.7-float(plume)*0.12))
     surface.draw_colored_polygon(PackedVector2Array([at+Vector2(10,-3)*unit,at+Vector2(13,-13)*unit,at+Vector2(17,-2)*unit]),Color("df986b"))
    else:
     for person in range(5):
      var person_at := at+Vector2(15+person*3,4+posmod(person,2)*2)*unit
      surface.draw_circle(person_at-Vector2(0,4)*unit,1.1*unit,Color("e5c67e"))
      surface.draw_line(person_at-Vector2(0,2)*unit,person_at+Vector2(0,3)*unit,Color("444b49"),2*unit)
     surface.draw_line(at+Vector2(20,4)*unit,at+Vector2(20,-7)*unit,Color("cfbe8f"),unit)
     surface.draw_rect(Rect2(at+Vector2(17,-10)*unit,Vector2(8,5)*unit),Color("e0d3aa"))
   surface.draw_polyline(PackedVector2Array([crest+Vector2(-5,4),crest+Vector2(0,-5),crest+Vector2(5,4)]),ink,2.2,true)
   surface.draw_line(crest+Vector2(-5,7),crest+Vector2(5,7),ink,2.2,true)
   if zoom > 3 or id == selected:
    var text := str(event.get("label_ru" if L.language == "ru" else "label",kind))
    if text.length() > 44: text = text.left(41)+"…"
    var baseline := crest+Vector2(10,5)
    var text_size := font.get_string_size(text,HORIZONTAL_ALIGNMENT_LEFT,-1,12)
    var event_rect := Rect2(baseline-Vector2(0,12),text_size+Vector2(6,5))
    var clear := true
    for previous in occupied:
     if previous.intersects(event_rect): clear = false; break
    if clear or id == selected:
     occupied.append(event_rect)
     surface.draw_string_outline(font,baseline,text,HORIZONTAL_ALIGNMENT_LEFT,-1,12,4,Color("142d3a"))
     surface.draw_string(font,baseline,text,HORIZONTAL_ALIGNMENT_LEFT,-1,12,ink)

func grouped_routes() -> Array:
 var groups: Dictionary = {}
 for route in routes:
  var key := str(route.get("actor", -1)) + ":" + str(route.get("target", -1))
  if not groups.has(key):
   groups[key] = route.duplicate(true)
   groups[key]["commitments"] = []
  groups[key].commitments.append(route)
 var result: Array = []
 for route in groups.values():
  var count := int(route.commitments.size())
  if count > 1:
   route.kind = "mixed"
   route.label = "Policy connections"
   route.label_ru = "Политические связи"
   route.value_label = str(count) + " commitments"
   route.value_label_ru = "Обязательств: " + str(count)
  result.append(route)
 return result

func visible_map_events() -> Array:
 var ordered := map_events.duplicate()
 var priority := {"civil_war": 0, "war": 0, "revolution": 1, "coup": 2, "insurgency": 3, "unrest": 4}
 ordered.sort_custom(func(a, b): return int(priority.get(a.get("kind", ""), 5)) < int(priority.get(b.get("kind", ""), 5)))
 var result: Array = []
 var seen: Dictionary = {}
 for event in ordered:
  var id := int(event.get("country_id", -1))
  var kind := str(event.get("kind", ""))
  if zoom < 2.3 and id not in [selected, hovered]:
   # The world view emphasizes major developments. Minor assessments and
   # multiple events become visible when focusing a country or zooming in.
   if kind == "unrest" or (kind == "insurgency" and int(scene_country(id).get("insurgency", 6)) > 1): continue
   if seen.has(id): continue
  seen[id] = true
  result.append(event)
 return result

func route_at(at: Vector2) -> Dictionary:
 for region in route_hit_regions:
  var points: PackedVector2Array = region.points
  for i in range(points.size()-1):
   if Geometry2D.get_closest_point_to_segment(at,points[i],points[i+1]).distance_to(at) < 6.0:
    return region.route
 return {}
