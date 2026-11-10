#!/usr/bin/env python3
"""Export map geometry, English names, portraits, and synthesized music for Godot."""
import json
import shutil
import sys

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "godot" / "assets"
sys.path.insert(0, str(ROOT))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # Godot uses a continuous geographic map; the original Qt compass map stays intact.
    from tools.export_geographic_map import main as export_geographic_map
    export_geographic_map()
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
