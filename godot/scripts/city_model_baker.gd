extends SceneTree
## Original reusable 3D miniature kit. Run with --script to rebuild map sprites.
## Variants are illustrative settlement architecture, never geolocated buildings.
func material(color: Color) -> StandardMaterial3D:
 var m := StandardMaterial3D.new()
 m.albedo_color = color
 m.roughness = 0.92
 return m

func box(parent: Node3D, at: Vector3, size: Vector3, color: Color) -> void:
 var mesh := MeshInstance3D.new()
 var shape := BoxMesh.new()
 shape.size = size
 mesh.mesh = shape
 mesh.material_override = material(color)
 mesh.position = at
 parent.add_child(mesh)

func make_city(kind: int) -> Node3D:
 var city := Node3D.new()
 var stone := Color("b6b7a2")
 var roofs := Color("b3a38b")
 # Original procedural assets created for this project.
 # Local roads are illustrative architecture, not simulation transport links.
 box(city, Vector3(0,-0.1,0),Vector3(8.7,0.15,7.2),Color("626d60"))
 # Two crossing streets follow the spaces between building blocks.
 for lane in [-1.275,1.275]:
  box(city,Vector3(lane,0.005,0),Vector3(0.58,0.04,7.0),Color("434d4b"))
 for lane in [-1.025,1.025]:
  box(city,Vector3(0,0.006,lane),Vector3(8.5,0.04,0.48),Color("434d4b"))
 for stripe in range(9):
  var d := -3.6 + float(stripe)*0.9
  for lane in [-1.025,1.025]:
   box(city,Vector3(d,0.034,lane),Vector3(0.35,0.015,0.045),Color("c5c3a2"))
 for stripe in range(7):
  var d := -2.7 + float(stripe)*0.9
  for lane in [-1.275,1.275]:
   box(city,Vector3(lane,0.035,d),Vector3(0.045,0.015,0.32),Color("c5c3a2"))
 # Low-poly planted groves around the ground edge add scale and soft shadows.
 for tree_position in [Vector3(-3.8,0,-2.8),Vector3(-3.5,0,-2.5),Vector3(-3.8,0,2.7),Vector3(3.7,0,-2.8)]:
  box(city,tree_position+Vector3(0,0.3,0),Vector3(0.1,0.6,0.1),Color("736149"))
  var foliage := MeshInstance3D.new()
  var crown := SphereMesh.new()
  crown.radius = 0.42
  crown.height = 0.95
  crown.radial_segments = 5
  crown.rings = 2
  foliage.mesh = crown
  foliage.position = tree_position+Vector3(0,0.83,0)
  foliage.material_override = material(Color("5c7352"))
  city.add_child(foliage)
 for x in range(3):
  for z in range(3):
   var h := 0.8 + float(posmod(x*3+z*5+kind*7,5))*0.38
   if kind < 2 and x == 1 and z == 1: h = 4.6
   if kind >= 4: h *= 0.65
   var p := Vector3(float(x-1)*2.55,h/2.0,float(z-1)*2.05)
   box(city,p,Vector3(1.65,h,1.25),stone.lightened(float(posmod(x+z,3))*0.05))
   box(city,p+Vector3(0,h/2.0+0.08,0),Vector3(1.8,0.16,1.4),roofs)
   # Narrow inset window bands read as architectural detail at close zoom.
   for floor_index in range(1,int(h/0.65)+1):
    box(city,Vector3(p.x,float(floor_index)*0.58,p.z+0.632),Vector3(1.12,0.16,0.025),Color("414d50"))
    box(city,Vector3(p.x+0.832,float(floor_index)*0.58,p.z),Vector3(0.025,0.16,0.8),Color("657479"))
 if kind < 2:
  box(city,Vector3(0,5.0,0),Vector3(0.8,0.45,0.8),Color("d8cfad"))
  var roof := MeshInstance3D.new()
  var peak := PrismMesh.new()
  peak.size = Vector3(1.6,0.9,1.6)
  roof.mesh = peak
  roof.position = Vector3(0,5.65,0)
  roof.material_override = material(Color("7b776a"))
  city.add_child(roof)
 elif kind < 4:
  # Factory hall, two chimneys, no animated smoke or fictitious activity.
  box(city,Vector3(0,0.65,3.1),Vector3(5.7,1.3,1.5),Color("958a77"))
  for x in [-2.1,1.8]:
   box(city,Vector3(x,2.0,3.1),Vector3(0.48,4.0,0.48),Color("8d7462"))
 else:
  # Warehouse wharf and a structural cargo crane silhouette.
  box(city,Vector3(0,0.05,4.0),Vector3(8.0,0.3,1.5),Color("8e8b72"))
  box(city,Vector3(2.6,1.8,3.8),Vector3(0.22,3.6,0.22),Color("c0ab73"))
  box(city,Vector3(1.6,3.5,3.8),Vector3(3.5,0.2,0.22),Color("c0ab73"))
 city.rotation.y = float(kind%2)*0.16-0.08
 return city

func _initialize() -> void:
 call_deferred("bake")

func bake() -> void:
 for kind in range(6):
  var viewport := SubViewport.new()
  viewport.size = Vector2i(256,256)
  viewport.transparent_bg = true
  viewport.own_world_3d = true
  viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
  root.add_child(viewport)
  var environment := WorldEnvironment.new()
  var settings := Environment.new()
  settings.background_mode = Environment.BG_COLOR
  settings.background_color = Color(0,0,0,0)
  settings.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
  settings.ambient_light_color = Color("c5d4dd")
  settings.ambient_light_energy = 0.65
  environment.environment = settings
  viewport.add_child(environment)
  var sun := DirectionalLight3D.new()
  sun.rotation_degrees = Vector3(-48,-42,0)
  sun.light_color = Color("ffe6b3")
  sun.light_energy = 1.2
  sun.shadow_enabled = true
  viewport.add_child(sun)
  viewport.add_child(make_city(kind))
  var camera := Camera3D.new()
  camera.projection = Camera3D.PROJECTION_ORTHOGONAL
  camera.size = 15.5
  camera.position = Vector3(12,13,16)
  viewport.add_child(camera)
  camera.look_at(Vector3(0,1.3,0))
  camera.current = true
  await process_frame
  await process_frame
  await RenderingServer.frame_post_draw
  var img := viewport.get_texture().get_image()
  var error := img.save_png("res://assets/cities/city_%d.png" % kind)
  print("city variant ",kind," saved: ",error)
  viewport.queue_free()
  await process_frame
 quit()
