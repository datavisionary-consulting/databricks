# Global Shipping Chokepoints

**Status: in progress.** This README will be rewritten once real results exist — see `research/README.md` in the [datavisionary-consulting.github.io](https://github.com/datavisionary-consulting/datavisionary-consulting.github.io) repo for the standard every case study here follows (lead with money/legal-risk/optimization, never invent a number the data can't support).

## The idea

A global map of real maritime shipping traffic, built at lakehouse scale in Databricks, to find where the world's shipping chokepoints actually are and quantify two things a non-technical reader cares about: how much trade depends on each one, and what's exposed if one closes.

## Data (real, free, global)

1. **World Bank Global Shipping Traffic Density** — a global grid built from real AIS ship positions (Jan 2015 – Feb 2021), ~500m resolution, commercial vessels only. [Catalog page](https://datacatalog.worldbank.org/search/dataset/0037580/global-shipping-traffic-density).
2. **NGA World Port Index** — ~3,700 world ports with name, country, coordinates. [NGA page](https://msi.nga.mil/Publications/WPI).
3. **UN Comtrade** — global bilateral trade value by country, to convert chokepoint traffic into dollar exposure. [comtradeplus.un.org](https://comtradeplus.un.org/).

## Planned output

An interactive map (not a static chart, unlike the other case studies here) showing global shipping density with labeled chokepoints and their trade-value exposure — built to be shared directly, including on LinkedIn.

## Files

- `Notebook/01_download_and_load.py` — downloads the raster and port index, downsamples the global grid to a Spark-friendly resolution, and lands both as Delta tables. Requires pasting the real download URLs from the catalog pages above (they carry a token and aren't stable to hardcode).
