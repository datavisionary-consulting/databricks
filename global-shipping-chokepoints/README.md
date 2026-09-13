# Global Shipping Chokepoints

**Interactive map:** https://claude.ai/code/artifact/ac3a0fa7-574b-47af-9d3f-261c8215e0ee

## The real finding

The world's busiest waterway by raw ship traffic barely moves any cargo. The Danish Straits (the gateway to the Baltic Sea) account for **69.5%** of the measured AIS traffic density across 9 major global chokepoints — more than the other eight combined — but only **0.46%** of their real, measured cargo-carrying capacity (IMF PortWatch). The Strait of Malacca, by contrast, carries **39.3%** of the group's real capacity while registering only 14.0% of the traffic density.

| Chokepoint | Nearest port | AIS density share | Real capacity share (IMF) |
|---|---|---:|---:|
| Danish Straits | Hundested, DK | **69.5%** | 0.5% |
| Strait of Malacca | Teluk Anson, MY | 14.0% | **39.3%** |
| Strait of Hormuz | Khawr Khasab, OM | 6.4% | 6.8% |
| Strait of Dover | Calais, FR | 5.1% | 15.7% |
| Strait of Gibraltar | Tangier-Mediterranean, MA | 1.7% | 16.0% |
| Bab-el-Mandeb | Assab, ER | 1.6% | 5.8% |
| Suez Canal | El Ismailiya, EG | 0.8% | 6.8% |
| Bosphorus Strait | Istinye, TR | 0.8% | 5.0% |
| Panama Canal | Vacamonte, PA | 0.08% | 4.2% |

**Why:** raw AIS position density measures *how often a ship passed*, not *how much it was carrying*. The Danish Straits see constant short-haul ferry and regional traffic spread across a wide lane — every trip pings the grid repeatedly. Panama and Suez are the opposite: narrow, engineered canals where ships travel single-file through a tight corridor, touching far fewer grid cells per transit even when each vessel is near-maximum capacity. **A chokepoint's importance to trade has to be measured in what ships are carrying, not how often their GPS pinged** — which is why this project cross-checks its own measurement against an independent, authoritative source (IMF PortWatch) rather than reporting the density ranking alone, the same honest-cross-check pattern used across this repo's other projects.

## Data (real, free, global, all independently verified)

1. **World Bank Global Shipping Traffic Density** — a global grid built from real AIS ship positions (Jan 2015 – Feb 2021), ~0.005° (~500m) native resolution, all vessel types combined. [Catalog page](https://datacatalog.worldbank.org/search/dataset/0037580/global-shipping-traffic-density).
2. **NGA World Port Index** — 3,669 world ports with name, country, coordinates, via [ArcGIS Hub](https://hub.arcgis.com/datasets/EDT::world-port-index) (CSV export).
3. **IMF PortWatch** — daily vessel transit counts and cargo-carrying capacity for the same 28 named global chokepoints, built from real AIS signals on ~90,000 ships. Public, unauthenticated ArcGIS FeatureServer, no API key required: `https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/services/Daily_Chokepoints_Data/FeatureServer/0/query`. [Methodology](https://portwatch.imf.org/pages/data-and-methodology).

## Method

1. **`01_download_and_load`** — downloads the World Bank raster (a 511MB zip containing a 9.2GB GeoTIFF) and the World Port Index CSV, decimates the raster from its native ~500m grid to a 0.05° grid using GDAL's overview-aware decimated read (`Resampling.average`, scaled to recover an equivalent sum — `Resampling.sum` is warp-only in rasterio, not usable on a plain read), and lands both as Delta tables. 3,040,763 non-zero 0.05° cells survive out of ~24.5M possible globally.
2. **`02_find_chokepoints`** — defines 9 known strategic chokepoints by real geographic bounding box (Malacca, Suez, Panama, Hormuz, Bab-el-Mandeb, the Danish Straits, Dover, Gibraltar, Bosphorus), sums real measured traffic density inside each box, and labels each with its nearest real port from the World Port Index.
3. **`03_trade_capacity_crosscheck`** — pulls a trailing 365-day average of real daily vessel capacity from IMF PortWatch for the same 9 chokepoints (mapped to PortWatch's own canonical chokepoint IDs) and joins it against the density ranking from step 2. This produces the table above.
4. **`04_export_for_map`** — re-aggregates the native 3M-row grid to a 0.5° grid for visualization, keeps the top half by density to bound the payload, and exports both that grid and the final comparison table as compact JSON for the interactive map.

## Files

- `Notebook/01_download_and_load.py`, `Notebook/02_find_chokepoints.py`, `Notebook/03_trade_capacity_crosscheck.py`, `Notebook/04_export_for_map.py` — the actual Databricks notebooks, in run order.

## Honest limits

- The World Bank raster download actually serves the **all-vessel-types combined** density layer (fishing, passenger, oil & gas, leisure, commercial), not a commercial-only layer, even though the catalog page also lists one separately. The major commercial chokepoints dominate regardless, but this is noted rather than silently assumed away.
- Bounding-box aggregation conflates channel geometry with traffic volume: a narrow engineered canal (Panama, Suez) touches far fewer 0.05° cells per transit than a wide strait (Malacca, the Danish Straits) even at equal vessel counts, which is itself part of why the IMF capacity cross-check exists rather than trusting the density box sums alone.
- "Danish Straits" is a broader box than PortWatch's own more specific "Oresund Strait" — the two aren't an identical footprint, which is why the mapping is documented explicitly in `03_trade_capacity_crosscheck` rather than treated as interchangeable.
