# Godot asset provenance

- `relief_source` is copied from the existing `img/background.png`. The original game artwork is credited in the [project README](../../README.md); no additional license is asserted here.
- The color-safe map palette is derived from the mapping in `MapView.py`.
- Synthesized sound effects are original generated cues based on the recipes in `Sound.py`.
- Music has separate [attribution](music/ATTRIBUTION.md).

- `cities/` contains original procedural 3D miniatures created for this project, baked by `scripts/city_model_baker.gd`; see [model provenance](cities/README.md).
- `terrain_mask.png` is generated from the existing map polygons by `tools/export_terrain_mask.py` (build-time Pillow dependency).
