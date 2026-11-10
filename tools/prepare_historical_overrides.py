#!/usr/bin/env python3
"""Rebuild world-scale historical overlays from vendored open Berlin lines and factual ONC tracing."""
import gzip,hashlib,json
from pathlib import Path
from shapely.geometry import shape,Polygon,mapping
from shapely.ops import unary_union
ROOT=Path(__file__).resolve().parents[1]/'data/geography'
# Original factual trace of the North/South boundary on US DoD ONC K-6.
# Coordinates read against the graticule, rounded/generalized for world-map use.
# The north-eastern boundary was undefined: last segment is a drawing convention.
YEMEN_LINE=[(43.5,12.6),(43.64,12.82),(43.66,12.96),(43.8,13.08),(43.95,13.09),(44.08,13.04),(44.22,13.0),(44.32,13.03),(44.37,13.14),(44.49,13.19),(44.51,13.28),(44.65,13.25),(44.7,13.32),(44.64,13.39),(44.62,13.48),(44.52,13.5),(44.53,13.56),(44.41,13.53),(44.35,13.45),(44.32,13.49),(44.4,13.6),(44.49,13.6),(44.57,13.75),(44.6,13.85),(44.79,13.88),(44.92,13.94),(45.03,13.9),(45.12,13.94),(45.13,14.0),(45.2,13.99),(45.25,14.1),(45.34,14.08),(45.39,14.18),(45.47,14.22),(45.52,14.12),(45.64,14.0),(45.89,14.03),(45.97,14.12),(45.98,14.32),(46.09,14.46),(46.07,14.53),(45.91,14.6),(45.8,14.67),(45.71,14.66),(45.65,14.58),(45.62,14.43),(45.54,14.43),(45.49,14.48),(45.51,14.63),(45.46,14.7),(45.36,14.71),(45.36,14.9),(45.46,14.92),(45.46,15.02),(45.53,15.15),(46.5,17.4),(47.0,20.0)]
def main():
 manifest=json.loads((ROOT/'historical_sources.json').read_text(encoding='utf-8'))
 for source in manifest['berlin']['files']:
  if hashlib.sha256((ROOT/source['file']).read_bytes()).hexdigest()!=source['sha256']:
   raise ValueError('Historical Berlin source checksum mismatch: '+source['file'])
 lines=[]
 for name in ['a_grenzmauer','c_politischegrenze']:
  d=json.loads(gzip.decompress((ROOT/f'berlin_1989_{name}.geojson.gz').read_bytes()))
  lines += [shape(f['geometry']) for f in d['features']]
 band=unary_union(lines).buffer(.0002)
 west=max([Polygon(r) for p in band.geoms for r in p.interiors],key=lambda p:p.area).buffer(.0002).simplify(.001,preserve_topology=True)
 north=Polygon(YEMEN_LINE+[(40,20),(40,10),(43,10),YEMEN_LINE[0]])
 rows=[('west_berlin',west,'dl-de-zero-2.0','https://gdi.berlin.de/services/wfs/berlinermauer','1989-04-25','Union wall and political-boundary lines; buffer .0002 degrees; largest interior ring; buffer .0002; simplify .001. Clip to modern Berlin. 1988 minor exchanges not reversed; world-scale 1982 approximation.'),('north_yemen_mask',north,'Public domain US government factual trace','https://maps.lib.utexas.edu/maps/onc/txu-pclmaps-oclc-8322829_k_6.jpg','ONC K-6 edition 4','Manual graticule trace, generalized coordinates; intersect modern Yemen; remainder is South Yemen including Socotra. Northeastern undefined boundary closed by approximate drawing convention from 45.53E 15.15N through 46.5E 17.4N; modern Saudi external footprint retained. Not a legally delimited border.')]
 out={'type':'FeatureCollection','features':[{'type':'Feature','properties':{'key':k,'license':lic,'source':src,'source_date':date,'accuracy':note},'geometry':mapping(g)} for k,g,lic,src,date,note in rows]}
 (ROOT/'historical_overrides.json').write_text(json.dumps(out,indent=2)+'\n', encoding='utf-8')
if __name__=='__main__':main()
