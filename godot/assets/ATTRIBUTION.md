# Godot asset provenance

- `map.json`, `map_metadata.json`, `geo_relief.png` and `geo_terrain_mask.png` are the continuous 1982 geographic map. Natural Earth vector v5.1.2 and Shaded Relief Basic v3.2.0 are public domain. Berlin linework is official Berlin open data under Datenlizenz Deutschland Zero 2.0; the Yemen division is an original generalized factual trace from a US government chart. See [source files and license links](../../data/geography/README.md) and the [historical conventions](../../docs/GEOGRAPHY_1982.md). The Godot build no longer uses the old inset map or its relief image.
- The color-safe map palette is derived from the mapping in `MapView.py`.
- Synthesized sound effects are original generated cues based on the recipes in `Sound.py`.
- Music has separate [attribution](music/ATTRIBUTION.md).

- `cities/` contains original procedural 3D miniatures created for this project, baked by `scripts/city_model_baker.gd`; see [model provenance](cities/README.md).
- `geo_terrain_mask.png` is generated from the geographic mesh triangles, including holes and neutral land, by `tools/export_terrain_mask.py`. `tools/export_geographic_terrain.py` verifies and projects the Natural Earth raster. Pillow is a build-time dependency only.
