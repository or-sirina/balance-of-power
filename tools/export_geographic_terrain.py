#!/usr/bin/env python3
"""Project pinned Natural Earth shaded relief into the game's geographic atlas.

Requires Pillow only at build time. Normal gameplay/packaging uses the committed
PNGs and never downloads data. Supply the archive or opt into --download.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'godot/assets'
SOURCE_URL = 'https://naturalearth.s3.amazonaws.com/50m_raster/SR_50M.zip'
SOURCE_SHA = 'ff810f5f2747463fd8ffa612b23e5f5e5d593a345218976872b6749610976ab7'


def land_mask(metadata, polygons, scale=4):
    """Fill triangulated land, keeping lake holes and neutral islands correct."""
    width, height = int(metadata['width'] * scale), int(metadata['height'] * scale)
    result = Image.new('L', (width, height), 0)
    draw = ImageDraw.Draw(result)
    for polygon in polygons:
        for triangle in polygon['triangles']:
            draw.polygon([(round(x * scale), round(y * scale)) for x, y in triangle], fill=255)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-archive', type=Path, default=ROOT / '.cache/geography/SR_50M.zip')
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args()
    source = args.source_archive
    if not source.exists():
        if not args.download:
            parser.error('Provide --source-archive or --download to retrieve the pinned public-domain raster.')
        with urllib.request.urlopen(SOURCE_URL, timeout=60) as response:
            raw = response.read(30_000_001)
        if len(raw) > 30_000_000 or hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
            raise ValueError('Natural Earth archive failed size/checksum validation')
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(raw)
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
        raise ValueError('Natural Earth archive checksum differs from the verified source')
    metadata = json.loads((ASSETS / 'map_metadata.json').read_text())
    polygons = json.loads((ASSETS / 'map.json').read_text())
    west, south, east, north = metadata['bounds']
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        with Image.open(io.BytesIO(archive.read('SR_50M.tif'))) as raster:
            raster.load()
            source_size = list(raster.size)
            crop = ((west + 180) / 360 * raster.width,
                    (90 - north) / 180 * raster.height,
                    (east + 180) / 360 * raster.width,
                    (90 - south) / 180 * raster.height)
            output_size = (metadata['width'] * 4, metadata['height'] * 4)
            raster.convert('L').resize(output_size, Image.Resampling.LANCZOS, box=crop).save(ASSETS / 'geo_relief.png')
    land_mask(metadata, polygons).save(ASSETS / 'geo_terrain_mask.png')
    manifest = {
        'name': 'Natural Earth 1:50m Shaded Relief Basic', 'version': '3.2.0',
        'url': SOURCE_URL, 'sha256': SOURCE_SHA, 'source_size': source_size,
        'license': 'Public domain', 'license_url': 'https://www.naturalearthdata.com/about/terms-of-use/',
        'description_url': 'https://www.naturalearthdata.com/downloads/50m-raster-data/50m-shaded-relief/',
        'bounds': metadata['bounds'], 'output_size': list(output_size),
        'method': 'Crop WGS84 global plate carree raster to map bounds; resample to atlas projection; mask with exported land triangles.',
        'outputs': {name: hashlib.sha256((ASSETS / name).read_bytes()).hexdigest()
                    for name in ('geo_relief.png', 'geo_terrain_mask.png')},
    }
    (ROOT / 'data/geography/terrain_source.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Exported geographic shaded relief and land mask:', output_size)


if __name__ == '__main__':
    main()
