#!/usr/bin/env python3
"""Rebuild relief clipping mask from the existing map geometry.

Build-time Pillow dependency; no runtime dependency. This mask derives solely
from godot/assets/map.json and inherits that source's provenance. It introduces
no external geographic data or independent licensing claim.
"""
import json
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]

def main():
    source = ROOT / 'godot/assets/map.json'
    target = ROOT / 'godot/assets/terrain_mask.png'
    image = Image.new('RGB', (948, 483), 'black')
    draw = ImageDraw.Draw(image)
    for polygon in json.loads(source.read_text(encoding='utf-8')):
        if len(polygon['points']) >= 3:
            draw.polygon([tuple(point) for point in polygon['points']], fill='white')
    image.save(target)
    print(target)

if __name__ == '__main__':
    main()
