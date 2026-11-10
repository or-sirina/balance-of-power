"""Contract checks for the continuous, triangulated geographic game map."""
import json
import unittest
from pathlib import Path
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]

class GeographicMapTests(unittest.TestCase):
    def test_geographic_map_contract(self):
        data = json.loads((ROOT/'godot/assets/map.json').read_text())
        metadata = json.loads((ROOT/'godot/assets/map_metadata.json').read_text())
        self.assertTrue(metadata['bounds'] == [-180,-60,180,85])
        self.assertTrue({p['id'] for p in data if p['id'] >= 0} == set(range(80)))
        self.assertTrue(len(metadata['anchors']) == 80)

        capitals = metadata['capitals']
        self.assertEqual(set(capitals), {str(i) for i in range(80)})
        self.assertTrue(all(row['name_ru'].strip() for row in capitals.values()))
        expected_capitals = {
            '0': ('Washington, D.C.', 'Вашингтон'),
            '19': ('Bonn', 'Бонн'),
            '22': ('East Berlin', 'Восточный Берлин'),
            '26': ('Pretoria', 'Претория'),
            '33': ('Lagos', 'Лагос'),
            '38': ('Dar es Salaam', 'Дар-эс-Салам'),
            '58': ('Rangoon', 'Рангун'),
            '67': ('Abidjan', 'Абиджан'),
        }
        for cid, names in expected_capitals.items():
            with self.subTest(capital_id=cid):
                self.assertEqual((capitals[cid]['name'], capitals[cid]['name_ru']), names)
        self.assertAlmostEqual(capitals['26']['longitude'], 28.2293)
        self.assertAlmostEqual(capitals['26']['latitude'], -25.7479)

        for poly in data:
            geometry = Polygon(poly['points'],poly['holes'])
            self.assertTrue(geometry.is_valid)
            for x,y in poly['points']:
                self.assertTrue(0 <= x <= 1200 and 0 <= y <= 600)
            self.assertTrue(all(abs(a[0]-b[0]) < 600 for a,b in zip(poly['points'],poly['points'][1:]+poly['points'][:1])))
            # Rounded mesh preserves the polygon area, including excluded holes.
            self.assertTrue(abs(sum(Polygon(t).area for t in poly['triangles'])-geometry.area) < max(.03, geometry.area*1e-5))
        for cid,anchor in metadata['anchors'].items():
            country = unary_union([Polygon(p['points'],p['holes']) for p in data if p['id']==int(cid)])
            self.assertTrue(country.distance(Point(anchor)) < 1e-6)
        # Ocean in the continuous Pacific; no historical inset rectangles.
        self.assertTrue(not any(Polygon(p['points'],p['holes']).covers(Point(100,300)) for p in data))
        # Essential reconstructed unions and deliberately neutral occupied territories.
        def owner(lon,lat):
            point=Point((lon+180)*1200/360,(85-lat)*600/145)
            return {p['id'] for p in data if Polygon(p['points'],p['holes']).covers(point)}
        self.assertTrue(owner(13.32,52.50)=={19}) # West Berlin gameplay association
        self.assertTrue(owner(13.45,52.52)=={22}) # East Berlin
        self.assertTrue(owner(30.52,50.45)=={1}) # Kyiv, Soviet Union
        self.assertTrue(owner(17.11,48.15)=={24}) # Bratislava, Czechoslovakia
        self.assertTrue(owner(15.98,45.81)=={25}) # Zagreb, Yugoslavia
        self.assertTrue(owner(31.58,4.85)=={34}) # Juba, Sudan
        self.assertTrue(owner(38.93,15.32)=={35}) # Asmara, Ethiopia
        self.assertTrue(owner(17.08,-22.56)=={-1}) # Windhoek, occupied Namibia
        self.assertTrue(owner(125.57,-8.56)=={-1}) # Dili, occupied East Timor


    def test_shared_borders_and_land_coverage(self):
        import gzip
        from shapely.geometry import shape, box
        from shapely.affinity import affine_transform
        from shapely.strtree import STRtree
        polygons = json.loads((ROOT/'godot/assets/map.json').read_text())
        geometries = [Polygon(p['points'],p['holes']) for p in polygons]
        index = STRtree(geometries)
        for i,geometry in enumerate(geometries):
            for j in index.query(geometry,predicate='intersects'):
                if j>i:
                    self.assertTrue(geometry.intersection(geometries[j]).area < .0001)
        source = json.loads(gzip.decompress((ROOT/'data/geography/ne_50m_admin_0_map_units.geojson.gz').read_bytes()))
        original = unary_union([shape(f['geometry']) for f in source['features'] if f['properties']['ADM0_A3']!='ATA']).intersection(box(-180,-60,180,85))
        original = affine_transform(original,[1200/360,0,0,-600/145,600,85*600/145])
        exported = unary_union(geometries)
        # Coordinate rounding and subpixel island filtering are the only area loss.
        self.assertTrue(original.symmetric_difference(exported).area < 2.0)


    def test_historical_yemen_split(self):
        data = json.loads((ROOT/'godot/assets/map.json').read_text())
        def point(lon,lat):
            return Point((lon+180)*1200/360,(85-lat)*600/145)
        sanaa,mukalla = point(44.2,15.35),point(49.10,14.56)
        north = [i for i,p in enumerate(data) if Polygon(p['points'],p['holes']).covers(sanaa)]
        south = [i for i,p in enumerate(data) if Polygon(p['points'],p['holes']).covers(mukalla)]
        self.assertTrue(len(north)==1 and len(south)==1 and north!=south)
        self.assertTrue(data[north[0]]['id']==data[south[0]]['id']==-1)


if __name__ == "__main__":
    unittest.main()
