extends RefCounted
## Original 3D miniature buildings, baked under orthographic lighting.
## Shared illustrative architecture; variant selection does not assert city data.
## Rebuild PNGs with city_model_baker.gd using a graphical GL Compatibility run.
const MODELS = [
 preload("res://assets/cities/city_0.png"),
 preload("res://assets/cities/city_1.png"),
 preload("res://assets/cities/city_2.png"),
 preload("res://assets/cities/city_3.png"),
 preload("res://assets/cities/city_4.png"),
 preload("res://assets/cities/city_5.png"),
]

static func draw_city(surface: Control, at: Vector2, unit: float, identity: int, capital: bool, active: bool = false) -> void:
 var variant := posmod(identity, 2) if capital else 2 + posmod(identity, 4)
 var size := Vector2(64,64) * unit
 # Registration is the center of the miniature ground plane, not its roof.
 var target := Rect2(at - Vector2(32,40)*unit, size)
 var tint := Color(1.0,0.96,0.87,1.0) if active else Color.WHITE
 surface.draw_texture_rect(MODELS[variant], target, false, tint)
