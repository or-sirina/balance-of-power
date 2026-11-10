# Original miniature city models

These six transparent sprites are original procedural Godot 3D models, rendered with an orthographic camera, directional lighting and cast shadows. The reusable geometry and baker live in `scripts/city_model_baker.gd`. Original procedural assets created for this project. No external game assets were used. Local asphalt streets, center markings and small planted tree clusters are part of the miniature geometry; they do not introduce transport mechanics or assert real road locations.

Variants 0–1 have a civic tower, 2–3 factory buildings and chimneys, and 4–5 warehouses with a cargo crane. These are illustrative country-level settlement markers, not surveyed buildings, verified ports, actual city skylines, or new simulation locations. Stable identity selects a silhouette; it does not infer an economy.

Rebuild from the Godot project directory with a graphical renderer (headless has no texture render output):

```
godot --path . --rendering-method gl_compatibility --script res://scripts/city_model_baker.gd
```

The map uses cached textures only; no live 3D viewport or animation is needed. This keeps reduced motion and GL Compatibility support unchanged. Transparent canvas texture bounds are 256×256; registration places the ground center at approximately (128,160).
