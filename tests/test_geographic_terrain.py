"""The shipped relief mask aligns physical land/water with the geographic atlas."""
import hashlib
import json
from pathlib import Path
import unittest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


class GeographicTerrainTests(unittest.TestCase):
    def test_georeferenced_land_water_and_provenance(self):
        manifest = json.loads((ROOT / 'data/geography/terrain_source.json').read_text())
        for name, digest in manifest['outputs'].items():
            path = ROOT / 'godot/assets' / name
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
            with Image.open(path) as image:
                self.assertEqual(image.size, (4800, 2400))
        with Image.open(ROOT / 'godot/assets/geo_terrain_mask.png') as mask:
            # Independent geographical probes, including neutral enclave land.
            for name, longitude, latitude, land in (
                ('Washington', -77, 38.9, True), ('London', -.12, 51.5, True),
                ('Himalaya', 85, 28, True), ('Lesotho', 28.2, -29.5, True),
                ('Pacific', -150, 0, False), ('North Sea', 3, 57, False),
                ('Caspian Sea', 51, 42, False),
            ):
                x = int((longitude + 180) / 360 * mask.width)
                y = int((85 - latitude) / 145 * mask.height)
                self.assertEqual(mask.getpixel((x, y)), 255 if land else 0, name)


if __name__ == '__main__':
    unittest.main()
