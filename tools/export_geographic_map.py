#!/usr/bin/env python3
"""Build the continuous 1982 Godot map from pinned public-domain Natural Earth inputs."""
import gzip
import hashlib
import json
from pathlib import Path
from shapely import constrained_delaunay_triangles, make_valid, set_precision
from shapely.geometry import shape, Polygon, box, Point
from shapely.ops import unary_union
from shapely.affinity import affine_transform

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/geography'
OUT = ROOT / 'godot/assets'
WIDTH, HEIGHT = 1200, 600
BOUNDS = [-180, -60, 180, 85]
# Position is the immutable simulation ID, not an alphabetical country code.
CODES = 'USA SUN MEX HND NIC PAN CUB ARG COL PER VEN BRA CHL CAN GRC SWE GBR FRA ESP FRG ROU ITA GDR POL CSK YUG ZAF EGY TUN MAR DZA LBY MLI NGA SDN ETH KEN COD TZA MOZ ZMB AGO JPN PRK KOR AUS CHN VNM TUR SYR ISR TWN IRQ SAU IRN AFG PAK IND MMR THA IDN PHL GTM SLV CRI MRT GIN CIV BFA GHA NER TCD CMR CAF COG ZWE BWA JOR LBN BOL'.split()
GROUPS = {'SUN':'RUS UKR BLR MDA EST LVA LTU GEO ARM AZE KAZ UZB TKM KGZ TJK'.split(),
          'CSK':['CZE','SVK'], 'YUG':['SVN','HRV','BIH','SRB','MNE','MKD','KOS'],
          'SDN':['SDN','SDS'], 'ETH':['ETH','ERI']}

def read(name):
    return json.loads(gzip.decompress((SOURCE / (name+'.geojson.gz')).read_bytes()))['features']

def project(x, y, z=None):
    return ((x + 180) * WIDTH / 360, (85 - y) * HEIGHT / 145)

def parts(geom):
    if geom.geom_type == 'Polygon':
        yield geom
    elif hasattr(geom, 'geoms'):
        for child in geom.geoms:
            yield from parts(child)

def ring(coords):
    return [[round(x,6),round(y,6)] for x,y in list(coords)[:-1]]

def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False,separators=(',',':'))+'\n')

def main():
    manifest = json.loads((SOURCE/'sources.json').read_text())
    for row in manifest:
        assert hashlib.sha256((SOURCE/row['file']).read_bytes()).hexdigest() == row['sha256'], row['file']
    units = read('ne_50m_admin_0_map_units')
    admin1 = read('ne_10m_admin_1_states_provinces')
    by_code = {}
    for f in units:
        by_code.setdefault(f['properties']['ADM0_A3'],[]).append(shape(f['geometry']))
    by_code = {k:unary_union(v) for k,v in by_code.items()}
    # Modern Länder retain the inter-German border at world-map scale.
    east = unary_union([shape(f['geometry']) for f in admin1 if f['properties']['iso_3166_2'] in ['DE-SN','DE-BB','DE-MV','DE-TH','DE-ST','DE-BE']])
    east = make_valid(east).intersection(by_code['DEU'])
    overrides = {f['properties']['key']:f for f in json.loads((SOURCE/'historical_overrides.json').read_text())['features']}
    berlin = unary_union([shape(f['geometry']) for f in admin1 if f['properties']['iso_3166_2']=='DE-BE'])
    west_berlin = make_valid(shape(overrides['west_berlin']['geometry'])).intersection(berlin).intersection(by_code['DEU'])
    east = east.difference(west_berlin)
    by_code['GDR'] = east
    by_code['FRG'] = by_code['DEU'].difference(east)
    modeled = {}
    consumed = {'DEU'}
    for cid, code in enumerate(CODES):
        members = GROUPS.get(code,[code])
        modeled[cid] = unary_union([by_code[c] for c in members])
        consumed.update(members)
    geometries = list(modeled.items())
    # Somaliland's 1991 declaration is later than the scenario.
    by_code['SOM'] = unary_union([by_code['SOM'],by_code['SOL']])
    consumed.add('SOL')
    # Separate neutral countries/dependencies preserve actual land and boundaries.
    # Namibia and East Timor are intentionally NOT merged into their occupiers.
    for code, geometry in sorted(by_code.items()):
        if code not in consumed and code not in ['FRG','GDR','ATA']:
            if code == 'YEM':
                north = geometry.intersection(shape(overrides['north_yemen_mask']['geometry']))
                geometries.extend([(-1,north),(-1,geometry.difference(north))])
            else:
                geometries.append((-1,geometry))
    polygons = []
    for cid, geometry in geometries:
        geometry = make_valid(geometry).intersection(box(*BOUNDS))
        # Natural Earth's 1:50m coordinates already share boundaries; keep them
        # unchanged instead of simplifying each country's border independently.
        screen_geometry = set_precision(affine_transform(geometry,[WIDTH/360,0,0,-HEIGHT/145,WIDTH/2,85*HEIGHT/145]),.000001)
        for screen in parts(screen_geometry):
            if screen.area < .002:
                continue
            mesh = list(constrained_delaunay_triangles(screen).geoms)
            assert abs(sum(t.area for t in mesh)-screen.area) < max(1e-6,screen.area*1e-8)
            triangles = [ring(t.exterior.coords) for t in mesh]
            pts=ring(screen.exterior.coords)
            assert all(abs(a[0]-b[0]) < WIDTH/2 for a,b in zip(pts,pts[1:]+pts[:1])), (cid,'antimeridian')
            polygons.append({'id':cid,'points':pts,'holes':[ring(r.coords) for r in screen.interiors], 'triangles':triangles})
    assert {p['id'] for p in polygons if p['id']>=0} == set(range(80))
    places = read('ne_50m_populated_places')
    capitals = {f['properties']['ADM0_A3']:f['properties'] for f in places if f['properties']['ADM0CAP']==1}
    # Seats of government as of 1982; Natural Earth capital layer reflects the present.
    capital_overrides = {'SUN':('Moscow',37.6173,55.7558),'FRG':('Bonn',7.0982,50.7374),
        'GDR':('East Berlin',13.4105,52.5206),'CSK':('Prague',14.4208,50.0880),
        'YUG':('Belgrade',20.4489,44.7866),'MMR':('Rangoon',96.1561,16.8661),
        'CIV':('Abidjan',-4.0083,5.3599),'TZA':('Dar es Salaam',39.2083,-6.7924),
        'ZAF':('Pretoria',28.2293,-25.7479),'NGA':('Lagos',3.3792,6.5244),'BOL':('La Paz',-68.1193,-16.4897)}
    anchors, capital_info = {},{}
    capital_names_ru = json.loads((SOURCE/'capital_names_ru.json').read_text())
    for cid,code in enumerate(CODES):
        if code in capital_overrides: name,lon,lat = capital_overrides[code]
        else:
            p = capitals[code]; name,lon,lat = p['NAME'],p['LONGITUDE'],p['LATITUDE']
        screen_point = Point(project(lon,lat))
        country_shape = unary_union([Polygon(p['points'],p['holes']) for p in polygons if p['id']==cid])
        if not country_shape.covers(screen_point):
            # Generalized shorelines can miss a coastal capital by fractions of a pixel.
            from shapely.ops import nearest_points
            assert country_shape.distance(screen_point) < 1.0, (cid,name)
            screen_point = nearest_points(country_shape,screen_point)[0]
        anchors[str(cid)] = [screen_point.x,screen_point.y]
        capital_info[str(cid)] = {'name':' '.join(name.split()),'name_ru':capital_names_ru[str(cid)],'longitude':lon,'latitude':lat}
    write(OUT/'map.json',polygons)
    write(OUT/'map_metadata.json',{'width':WIDTH,'height':HEIGHT,'projection':'equirectangular',
        'bounds':BOUNDS,'standard_parallel_degrees':36.336057514613934,'date':'1982-01-01','anchors':anchors,'capitals':capital_info,
        'simulation_codes':{str(i):code for i,code in enumerate(CODES)},'historical_unions':GROUPS,
        'source':'Natural Earth v5.1.2 (public domain), Berlin official open data (dl-de-zero-2.0), original factual US DoD ONC trace; see data/geography/README.md',
        'geometry_notes':['Modern coastlines at 1:50m; historical state unions.',
            'Inter-German border from modern Länder; Berlin sectors generalized from Berlin official 1989 boundary (1988 minor exchanges not reversed).',
            'North/South Yemen split generalized from US DoD ONC K-6 (1984); undefined northeastern frontier uses documented drawing convention.',
            'Neutral countries and dependencies are non-interactive, not simulation actors.']})
    print(f'Exported {len(polygons)} polygons, {sum(len(p["points"]) for p in polygons)} exterior points, {sum(len(p["triangles"]) for p in polygons)} triangles')

if __name__=='__main__': main()
