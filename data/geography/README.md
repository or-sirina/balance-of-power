# Continuous geographic map sources

Made with Natural Earth. Inputs are from the official Natural Earth vector
repository tag **v5.1.2**. Natural Earth puts all versions of its raster and vector
map data in the **public domain**, including modifications and commercial reuse:
https://www.naturalearthdata.com/about/terms-of-use/

Repository: https://github.com/nvkelso/natural-earth-vector/tree/v5.1.2/geojson
Country/map-unit description:
https://www.naturalearthdata.com/downloads/50m-cultural-vectors/50m-admin-0-countries-2/

`sources.json` records the exact upstream URLs, SHA-256 checksums of the original
GeoJSON downloads, and checksums of the compact, deterministic gzip files shipped
here. Geometry coordinates are preserved losslessly. Only unused properties and
unused admin-1 / populated-place features are removed. Run
`python tools/prepare_geography_sources.py` to download and verify the originals
and reproduce these compact inputs. No download is required to export the map.
No CShapes data is used or distributed.

Additional historical overlays use official Berlin open-data linework under
Datenlizenz Deutschland Zero 2.0 and an original factual trace from a public-domain
US federal government navigation chart. Their source checksums, licenses and
limitations are recorded in `historical_sources.json`, the overlay GeoJSON and
the historical audit linked below. Rebuild them with
`python tools/prepare_historical_overrides.py` (offline from vendored inputs).

Run `python tools/export_geographic_map.py` (requires Shapely 2.1+) to rebuild
`godot/assets/map.json` and `map_metadata.json`. The standard Godot asset exporter
also calls this exporter. The original Qt compass map remains unchanged.

The map uses a single continuous equirectangular world rectangle, longitude
-180…180 and latitude -60…85, 1200×600 logical pixels. Pacific-edge land is kept
in separate polygons; islands are retained, without enlarged insets. All 80
simulation IDs remain fixed. Holes are exported separately for outline/hit tests;
constrained triangulation excludes their area. Neutral land has ID -1.
The equirectangular standard parallel is 36.34° (the display has unequal
longitude/latitude scales). No independent simplification is applied to shared
borders; the original 1:50m coordinates are retained. Islands smaller than
0.002 square logical pixel are omitted. Geographic capital coordinates are
retained in metadata; graphical anchors may move less than one pixel onto the
generalized coast to keep them on their country.

This is a **generalized historical reconstruction**, not a legal boundary atlas.
See [the historical audit](../../docs/GEOGRAPHY_1982.md). USSR, Yugoslavia,
Czechoslovakia, Sudan and Ethiopia are restored by union of modern units.
Neutral Somalia and Somaliland are also reunited to remove the post-1991 border.
West/East Germany are reconstructed from modern Länder. West Berlin is
associated with West Germany for gameplay, using the official Berlin 1989
sector boundary generalized for world scale; the minor 1988 land exchanges
are not reversed. This association is not a claim that West Berlin was a
constituent part of the Federal Republic. See the historical audit for sources. Namibia and East Timor remain separate neutral land, not
sovereign parts of their occupiers. Hong Kong and Macau remain neutral.
North and South Yemen are separate neutral polygons using a generalized
boundary traced from the US Department of Defense ONC K-6 (1984); the undefined
northeastern frontier uses an explicit drawing convention. See
`historical_overrides.json` and `tools/prepare_historical_overrides.py`.
Other unmodeled neutral states retain Natural Earth's outlines. The Jan 1982 date describes the simulation baseline and
these documented restorations, not every unmodeled administrative boundary.
Natural Earth itself depicts contemporary de facto boundaries, including
contested borders. Small modern coastline and border differences remain.

Capital markers identify the historical seat of government in 1982: Pretoria
(executive seat), Dar es Salaam (government seat), Lagos, Rangoon, Abidjan and
Bonn are used rather than substituting present-day capital locations. La Paz
is Bolivia's seat of government. Russian display names are independently
maintained in `capital_names_ru.json`; names do not change simulation IDs.
