#!/usr/bin/env python3
"""Export map geometry, English names, portraits, and synthesized music for Godot."""
import json
import shutil
import sys

from shapely import constrained_delaunay_triangles
from shapely.geometry import LineString
from shapely.ops import polygonize, unary_union
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "godot" / "assets"
sys.path.insert(0, str(ROOT))


def decode(poly):
    x, y = poly["x"], poly["y"] - 32
    points = [[x, y]]
    compass = poly["compass"]
    i = 0
    while i < len(compass):
        delta = int(compass[i]) if compass[i].isdigit() else 1
        if compass[i].isdigit():
            i += 1
        if i >= len(compass):
            break
        direction = compass[i]
        if direction == "n": y -= delta
        elif direction == "s": y += delta
        elif direction == "e": x += delta
        elif direction == "w": x -= delta
        points.append([x, y])
        i += 1
    return {"id": poly["country_id"] - 1, "points": points}


def odd_even(point, path):
    x, y = point.x, point.y
    inside = False
    for a, b in zip(path, path[1:] + path[:1]):
        if (a[1] > y) != (b[1] > y):
            crossing = a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if x < crossing:
                inside = not inside
    return inside


def triangulate(poly):
    path = poly["points"]
    if len(path) < 3:
        poly["triangles"] = []
        return poly
    lines = LineString(path + [path[0]])
    faces = [face for face in polygonize(unary_union(lines))
             if odd_even(face.representative_point(), path)]
    triangles = []
    area = 0.0
    for face in faces:
        for triangle in constrained_delaunay_triangles(face).geoms:
            coords = list(triangle.exterior.coords)[:-1]
            assert len(coords) == 3
            triangles.append([[x, y] for x, y in coords])
            area += triangle.area
    expected = sum(face.area for face in faces)
    assert abs(area - expected) <= max(1e-7, expected * 1e-9), (poly["id"], area, expected)
    assert triangles or expected == 0.0
    poly["triangles"] = triangles
    return poly


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    polygons = json.loads((ROOT / "data/map_data.json").read_text(encoding="utf-8"))
    write_json(OUT / "map.json", [triangulate(decode(poly)) for poly in polygons])
    local = json.loads((ROOT / "data/local/english.json").read_text(encoding="utf-8"))["data"]
    world = json.loads((ROOT / "data/world_data.json").read_text(encoding="utf-8"))
    write_json(OUT / "countries.json", [{"id": row["id"] - 1, "name": local[37 + row["id"] - 1][0]} for row in world])
    portraits = OUT / "advisors"
    portraits.mkdir(exist_ok=True)
    source = ROOT / "img/advisors"
    for path in sorted(source.glob("*.png")) + [source / "ATTRIBUTION.md", source / "manifest.json"]:
        shutil.copy2(path, portraits / path.name)
    # Synthesis is pure Python and does not initialize Qt or access user settings.
    import Music
    music = OUT / "music"
    music.mkdir(exist_ok=True)
    for key in Music.THEMES:
        Music._write_wav(str(music / (key + ".wav")), Music._fade(Music.render_theme(key)))


if __name__ == "__main__":
    main()
