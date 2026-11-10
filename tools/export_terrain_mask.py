#!/usr/bin/env python3
"""Rebuild the geographic land mask, including holes, without downloading data."""
import hashlib
import json
from pathlib import Path
from export_geographic_terrain import land_mask

ROOT = Path(__file__).resolve().parents[1]

def main():
    source = ROOT / 'godot/assets/map.json'
    target = ROOT / 'godot/assets/geo_terrain_mask.png'
    metadata = json.loads((ROOT / 'godot/assets/map_metadata.json').read_text(encoding='utf-8'))
    image = land_mask(metadata, json.loads(source.read_text(encoding='utf-8')))
    image.save(target)
    manifest_path = ROOT / 'data/geography/terrain_source.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['outputs'][target.name] = hashlib.sha256(target.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(target)

if __name__ == '__main__':
    main()
