#!/usr/bin/env python3
"""Re-create compact vendored Natural Earth inputs; verifies pinned upstream bytes."""
import gzip
import hashlib
import json
import urllib.request
from pathlib import Path
SOURCE = Path(__file__).resolve().parents[1] / 'data/geography'

def main():
    for source in json.loads((SOURCE/'sources.json').read_text(encoding='utf-8')):
        raw = urllib.request.urlopen(source['url']).read()
        assert hashlib.sha256(raw).hexdigest() == source['upstream_sha256']
        features = json.loads(raw)['features']
        if 'admin_1' in source['file']:
            keys = ['adm0_a3','name','iso_3166_2']
            features = [f for f in features if f['properties']['adm0_a3'] in ['DEU','YEM']]
        elif 'map_units' in source['file']:
            keys = ['ADM0_A3','NAME','GU_A3']
        else:
            keys = ['ADM0_A3','NAME','ADM0CAP','LATITUDE','LONGITUDE']
            features = [f for f in features if f['properties']['ADM0CAP']==1 or f['properties']['NAME'] in ['Bonn','Dar es Salaam','Rangoon','Abidjan','La Paz']]
        features = [{'type':'Feature','properties':{k:f['properties'][k] for k in keys},'geometry':f['geometry']} for f in features]
        blob = gzip.compress(json.dumps({'type':'FeatureCollection','features':features},separators=(',',':')).encode(),mtime=0)
        assert hashlib.sha256(blob).hexdigest() == source['sha256']
        (SOURCE/source['file']).write_bytes(blob)
        print(source['file'])
if __name__=='__main__': main()
