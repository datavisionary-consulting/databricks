# Global Shipping Chokepoints

**Interactive map:** https://claude.ai/code/artifact/ac3a0fa7-574b-47af-9d3f-261c8215e0ee

## Goal

A global view of the world's shipping traffic and its major chokepoints, built at lakehouse scale in Databricks, using real, independently sourced data rather than a single dashboard's own numbers.

## The measurements

Two real, independent datasets measure the same 9 major global shipping chokepoints: the Strait of Malacca, Suez Canal, Panama Canal, Strait of Hormuz, Bab-el-Mandeb, the Danish Straits, Strait of Dover, Strait of Gibraltar, and Bosphorus Strait.

| Chokepoint | Nearest port | AIS traffic density share | Real capacity share (IMF) |
|---|---|---:|---:|
| Danish Straits | Hundested, DK | 69.5% | 0.5% |
| Strait of Malacca | Teluk Anson, MY | 14.0% | 39.3% |
| Strait of Hormuz | Khawr Khasab, OM | 6.4% | 6.8% |
| Strait of Dover | Calais, FR | 5.1% | 15.7% |
| Strait of Gibraltar | Tangier-Mediterranean, MA | 1.7% | 16.0% |
| Bab-el-Mandeb | Assab, ER | 1.6% | 5.8% |
| Suez Canal | El Ismailiya, EG | 0.8% | 6.8% |
| Bosphorus Strait | Istinye, TR | 0.8% | 5.0% |
| Panama Canal | Vacamonte, PA | 0.08% | 4.2% |

By traffic density (how often a ship's position was recorded in the area), the Danish Straits rank first. By real cargo-carrying capacity (IMF PortWatch, measured independently from the density data), the Strait of Malacca ranks first.

**Why the two rankings differ:** traffic density counts vessel position reports; cargo capacity measures the freight-carrying capacity of the vessels making those reports. A narrow, engineered canal (Panama, Suez) routes ships single-file through one corridor, producing fewer distinct position reports per transit than a wide strait carrying a comparable or smaller amount of cargo. A wide strait with frequent short-distance regional traffic (the Danish Straits) produces many position reports from vessels that individually carry comparatively little cargo.

## Data (real, free, global, all independently verified)

1. **World Bank Global Shipping Traffic Density** — a global grid built from real AIS ship positions (Jan 2015 – Feb 2021), ~0.005° (~500m) native resolution, all vessel types combined. [Catalog page](https://datacatalog.worldbank.org/search/dataset/0037580/global-shipping-traffic-density).
2. **NGA World Port Index** — 3,669 world ports with name, country, coordinates, via [ArcGIS Hub](https://hub.arcgis.com/datasets/EDT::world-port-index) (CSV export).
3. **IMF PortWatch** — daily vessel transit counts and cargo-carrying capacity for the same 28 named global chokepoints, built from real AIS signals on ~90,000 ships. Public, unauthenticated ArcGIS FeatureServer, no API key required: `https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/services/Daily_Chokepoints_Data/FeatureServer/0/query`. [Methodology](https://portwatch.imf.org/pages/data-and-methodology).

## Method

1. **`01_download_and_load`** — downloads the World Bank raster (a 511MB zip containing a 9.2GB GeoTIFF) and the World Port Index CSV, decimates the raster from its native ~500m grid to a 0.05° grid using GDAL's overview-aware decimated read (`Resampling.average`, scaled to recover an equivalent sum — `Resampling.sum` is warp-only in rasterio, not usable on a plain read), and lands both as Delta tables. 3,040,763 non-zero 0.05° cells survive out of ~24.5M possible globally.
2. **`02_find_chokepoints`** — defines the 9 chokepoints by real geographic bounding box, sums real measured traffic density inside each box, and labels each with its nearest real port from the World Port Index.
3. **`03_trade_capacity_crosscheck`** — pulls a trailing 365-day average of real daily vessel capacity from IMF PortWatch for the same 9 chokepoints (mapped to PortWatch's own canonical chokepoint IDs) and joins it against the density ranking from step 2. This produces the table above.
4. **`04_export_for_map`** — re-aggregates the native 3M-row grid to a 0.5° grid for visualization, keeps the top half by density to bound the payload, and exports both that grid and the final comparison table as compact JSON.
5. **`05_visualize_map`** — renders the same data with a real basemap (Plotly's tokenless MapLibre traces, no Mapbox account needed) directly inside Databricks, producing the map figure used on the site and in this README.

## Files

- `Notebook/01_download_and_load.ipynb` through `Notebook/05_visualize_map.ipynb` — the actual Databricks notebooks, in run order, with real outputs included.
- `figures/world_map.png`, `figures/density_vs_capacity.png` — the two figures used on [datavisionary-consulting.github.io](https://datavisionary-consulting.github.io/#solutions).

## Notes on the method

- The World Bank raster download actually serves the **all-vessel-types combined** density layer (fishing, passenger, oil & gas, leisure, commercial), not a commercial-only layer, even though the catalog page also lists one separately.
- Bounding-box aggregation conflates channel geometry with traffic volume: a narrow engineered canal (Panama, Suez) touches far fewer 0.05° cells per transit than a wide strait (Malacca, the Danish Straits) even at an equal vessel count.
- "Danish Straits" is a broader box than PortWatch's own more specific "Oresund Strait" — the two aren't an identical footprint, which is why the mapping is documented explicitly in `03_trade_capacity_crosscheck` rather than treated as interchangeable.
