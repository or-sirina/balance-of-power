# Historical geography and cartographic conventions

The map is a **generalized reconstruction of the political geography of 1982**, using modern Natural Earth geometry. It is not a surveyed historical boundary dataset. The intended reference date is **1 January 1982**. This date is a design convention, not a date encoded by Natural Earth. In particular, a map described only as “1982” cannot consistently represent both the beginning and end of that year's territorial events.

## Data rights and provenance

Natural Earth is the geometry source. Its [terms of use](https://www.naturalearthdata.com/about/terms-of-use/) place its raster and vector data in the public domain and permit modification and commercial use. This is suitable for a possible commercial game release. Preserve the upstream version, download URL, local source archive and checksum in the generated dataset's provenance. Historical reference links below support facts; their text, maps and illustrations are not copied into the game. CShapes, with its noncommercial/share-alike licensing, is not used.

Natural Earth's [country documentation](https://www.naturalearthdata.com/downloads/110m-cultural-vectors/110m-admin-0-countries/) says its default boundaries follow de facto status. Consequently, grouping modern features is insufficient by itself to establish every 1982 border. Historical unions remove anachronistic internal state lines, but do not reverse all subsequent boundary treaties, river changes, reclamation, enclave changes or disputed control lines. Coastlines, small islands and narrow territories remain scale dependent.

## Simulation identity

`data/world_data.json` contains 80 simulation countries. Its stored `id` is **one based**; the simulation's array index is **zero based** (`id - 1`). Never use a source feature's ISO numeric code or polygon order as a simulation index. Multiple polygons may select the same simulation country. Unmodeled countries and dependencies remain visible neutral land and have no country-policy target; neutral means “outside the simulation”, not politically neutral.

These crosswalks identify the historical units that must be represented. The geometry generator and its output metadata are authoritative about the actual implemented geometry and approximations.

| Historical unit | JSON id / simulation index | Reconstruction rule |
| --- | --- | --- |
| Soviet Union | 2 / 1 | Unite Russia, Ukraine, Belarus, Moldova, Estonia, Latvia, Lithuania, Georgia, Armenia, Azerbaijan, Kazakhstan, Kyrgyzstan, Tajikistan, Turkmenistan and Uzbekistan. Do not leave modern international borders inside the union. |
| Yugoslavia | 26 / 25 | Unite Slovenia, Croatia, Bosnia and Herzegovina, Serbia, Montenegro, North Macedonia and the source's separately encoded Kosovo. Kosovo must not appear as an independent 1982 state. |
| Czechoslovakia | 25 / 24 | Unite Czechia and Slovakia. |
| West Germany | 20 / 19 | Reconstruct from the historical western Länder rather than assigning all modern Germany. Berlin requires the qualification below. |
| East Germany | 23 / 22 | Reconstruct from the historical eastern Länder; do not draw the modern unified Germany as either simulation country. |
| Sudan | 35 / 34 | Unite Sudan and South Sudan; their modern internal boundary disappears. |
| Ethiopia | 36 / 35 | Unite Ethiopia and Eritrea; this describes the state grouping, not control of every area during the Eritrean war. |
| Indonesia | 61 / 60 | Indonesia proper; East Timor is a separate neutral territory under the convention below. |
| Somalia | none | Unite Somalia and Somaliland into one neutral 1982 country footprint. |
| Yemen Arab Republic; People's Democratic Republic of Yemen | none | Two distinct neutral states, not a unified 1982 Yemen. A modern single Yemen polygon requires a historically sourced split; absent that split, declare the limitation. |
| Namibia | none | Separate neutral territory; do not merge into South Africa's simulation footprint. |
| Hong Kong; Macao | none | Separate neutral dependencies/territories where source scale supports them; do not silently treat their modern Chinese administrative status as the 1982 status. |

The UN records the [1990 Yemen and German unifications](https://www.un.org/en/about-us/growth-in-un-membership), [Czechoslovakia's dissolution at the end of 1992](https://www.un.org/en/about-us/member-states/czechoslovakia), and [Yugoslavia's successor states](https://www.un.org/en/about-us/member-states/yugoslavia). A [UN economic survey](https://digitallibrary.un.org/record/147176/files/1992wes.pdf) describes the Soviet Union's dissolution into 15 republics in 1991. The [UN account of Eritrea](https://assemblyforpeace.unu.edu/cases/unover/) documents annexation by Ethiopia and the 1993 independence process; the [UN South Sudan history](https://www.un.org/en/node/122910) dates its secession to 9 July 2011. Somaliland's [own foreign ministry history](https://mfagovsomaliland.org/recognition/restoration-sovereignty) dates its renewed independence declaration to 1991; that later event is not projected backwards onto 1982.

## Occupation, dependence and disputed sovereignty

A fill color and a click target are game mechanics, not recognition of sovereign title. Use the following conventions explicitly in map metadata and release documentation:

- **Baltic republics:** grouping Estonia, Latvia and Lithuania into the USSR represents Soviet administration in 1982. It does not endorse annexation. The [US Office of the Historian](https://history.state.gov/countries/estonia) records US nonrecognition of forcible incorporation.
- **Berlin:** West Berlin was not an ordinary West German Land; the city retained Four Power status. If West Berlin selects West Germany and East Berlin selects East Germany, label that a gameplay association. A modern undivided Berlin polygon or a straight approximation is not an exact 1982 sector boundary. The [Berlin Commissioner for the Study of the SED Dictatorship's historical guide](https://www.aufarbeitung-berlin.de/fileadmin/user_upload/Dokumente/Publikationen/BAB_LZPB_Berlin_questions_and_answers_II_screen.pdf) explains the status and sector division.
- **Namibia:** South African administration does not justify a sovereign South Africa union. The [UN peacekeeping history](https://peacekeeping.un.org/sites/default/files/past/untagFT.htm) describes South Africa as the de facto but illegal occupying power; [independence was on 21 March 1990](https://namibia.un.org/en/175155-uns-role-namibian-independence). Separate neutral rendering avoids converting occupation into simulation ownership. Modern Namibia geometry also does not itself reconstruct the historical Walvis Bay arrangement.
- **East Timor:** leave a separate neutral territory. The [UN mission history](https://peacekeeping.un.org/sites/default/files/past/unmiset/background.html) states that the UN never recognized Indonesia's integration of East Timor. This convention does not deny Indonesian military control in 1982.
- **Hong Kong and Macao:** separate neutral rendering represents their distinct administration in 1982, not independent statehood. The [Hong Kong government's 1997 yearbook](https://www.yearbook.gov.hk/1997/ch2/e2a.htm) records the 1 July 1997 transition, and the [Macao government's history](https://www.gcs.gov.mo/news/detail/pt/M19CSYwY0t) records Portuguese administration until 20 December 1999.
- **Other dependencies:** retain separate source territories as neutral unless there is a documented, intentional gameplay association. Greenland, overseas territories and possessions must not become simulation countries simply because they have polygons.
- **Disputes:** Western Sahara, Kashmir, Taiwan, the West Bank/Gaza, Golan Heights, Cyprus, the Falkland Islands and other contested areas require declared rendering conventions. Do not describe a modern source polygon as an uncontested 1982 sovereign boundary. Taiwan is a distinct simulation actor (id 52/index 51), which is a game-model choice. Where historical control is not reconstructed, disclose the modern geometry approximation rather than inventing precision.

## Names and temporal limits

Preserve simulation keys and compatibility names independently of map display names. In particular, id 69 is stored as `Burkina Faso`, but its 1982 name was **Upper Volta**: the [UN country history](https://www.un.org/en/about-us/member-states/burkina-faso) records the name change in 1984. `Zaire` (id 38), `Burma` (id 59), and the two German states are intentional period labels; `Central Africa` (id 74) maps to the Central African Republic, and `Congo` (id 75) maps to the Republic of the Congo, not Zaire.

The date applies to political units and names, not a global snapshot of military control. Egypt retains its sovereign Sinai footprint; the April 1982 Israeli withdrawal is not a change to this map layer. The map does not model changing front lines, military occupation or civil-war control zones. If those are later required, they need separate dated layers and explicit sources.

## Review requirements for subsequent updates

Check all 80 selectable identities, the separate German footprints, historical unions, neutral coverage, island hit targets, antimeridian seams and absence of post-1982 successor-state borders. Keep a machine-readable record of source feature names, simulation indices, union/split operations and approximations. A release should say “generalized 1982 reconstruction” until all historical-boundary limitations have been resolved and independently checked.

## Historical split overlays shipped with this build

`data/geography/historical_overrides.json` is rebuilt by `python tools/prepare_historical_overrides.py`. The source audit is `data/geography/historical_sources.json`. Both overlays are deliberately generalized at world-map scale.

**Berlin:** the [Berlin open-data catalogue](https://daten.berlin.de/datensaetze/verlauf-der-berliner-mauer-1989-wfs-3dcda64c) licenses the official service's wall and political-boundary linework under [Datenlizenz Deutschland Zero 2.0](https://www.govdata.de/dl-de/zero-2-0). The two raw WFS layers are vendored as gzip GeoJSON. Union the lines, buffer 0.0002 degrees to close digitization gaps, select the largest interior polygon, restore that buffer distance and simplify by 0.001 degrees; the exporter clips this mask to Berlin and associates the western area with West Germany. This is an approximately 481 km² western footprint, not an exact 1982 cadastral/sector boundary. The source describes April 1989 imagery. The [Berlin monuments authority](https://www.berlin.de/landesdenkmalamt/denkmale/highlight-berliner-mauer/mauer-denkmale/buddestrasse-1270929.php) documents a 1988 border adjustment: these minor land exchanges are not reversed.

**Yemen:** the original factual coordinate trace follows the North/South border on [US Defense Mapping Agency ONC K-6, edition 4](https://maps.lib.utexas.edu/maps/onc/txu-pclmaps-oclc-8322829_k_6.jpg), read against its graticule and generalized; the [J-6 northern sheet](https://maps.lib.utexas.edu/maps/onc/txu-pclmaps-oclc-8322829_j_6.jpg) was inspected for the desert frontier. The trace includes the Taiz/Al Dhale border's bends rather than projecting a modern governorate union backwards. The northeastern frontier was undefined/indefinite on the charts: the mask closes it by a declared approximate drawing line from 45.53° E, 15.15° N through 46.5° E, 17.4° N. Intersect the mask with the modern Yemen footprint for North Yemen; its remainder, including Socotra, is South Yemen. This retains the modern external Saudi footprint and is not a claim to have reconstructed a delimited 1982 desert border. The underlying charts are US government works; the shipped line is a new factual trace, not a copied illustration. Their original boundary-authority caveats remain applicable.
