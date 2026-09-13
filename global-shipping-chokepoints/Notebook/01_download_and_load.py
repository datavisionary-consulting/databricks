# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# MAGIC %md
# MAGIC # Global Shipping Chokepoints — 01: Download and Load
# MAGIC
# MAGIC Downloads two real, free, global datasets and loads them into Delta tables:
# MAGIC
# MAGIC 1. **World Bank Global Shipping Traffic Density** — a worldwide grid built from real
# MAGIC    AIS ship positions (Jan 2015 - Feb 2021), about 500m resolution at the equator, all vessel
# MAGIC    types combined (commercial, fishing, passenger, oil & gas, leisure). This is the real
# MAGIC    "did a ship actually pass through here" data.
# MAGIC    Catalog page: https://datacatalog.worldbank.org/search/dataset/0037580/global-shipping-traffic-density
# MAGIC 2. **NGA World Port Index** — about 3,700 ports worldwide with name, country, and coordinates,
# MAGIC    used to label whatever chokepoints the density data turns up.
# MAGIC    Source used: https://hub.arcgis.com/datasets/EDT::world-port-index (CSV export)
# MAGIC

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 0 — create the schema and volume
# MAGIC
# MAGIC `/Volumes/workspace/global_shipping/raw_data` only becomes a valid path once the
# MAGIC `global_shipping` schema and its `raw_data` volume exist in Unity Catalog. Run this once.

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE SCHEMA IF NOT EXISTS workspace.global_shipping;
# MAGIC CREATE VOLUME IF NOT EXISTS workspace.global_shipping.raw_data;

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1 — download the shipping density raster
# MAGIC
# MAGIC The World Bank catalog's download button for this dataset actually serves a ZIP
# MAGIC (`shipdensity_global.zip`, ~511 MB), containing the **all-vessel-types** combined
# MAGIC density layer — not the commercial-only layer the catalog page also lists separately.
# MAGIC We're using the combined layer: the major commercial chokepoints (Suez, Malacca,
# MAGIC Panama, Hormuz) dominate it regardless, and it saves a second multi-hundred-MB download.
# MAGIC Anything we publish from this will say "all vessel types," not "commercial only."

# COMMAND ----------

# MAGIC %sh
# MAGIC cd /Volumes/workspace/global_shipping/raw_data
# MAGIC wget -O shipdensity_global.zip "https://datacatalogfiles.worldbank.org/ddh-published/0037580/5/DR0045406/shipdensity_global.zip"
# MAGIC unzip -o shipdensity_global.zip -d shipdensity_extracted
# MAGIC ls -lh shipdensity_extracted

# COMMAND ----------

# MAGIC %pip install rasterio
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

import rasterio

RASTER_PATH = "/Volumes/workspace/global_shipping/raw_data/shipdensity_extracted/shipdensity_global.tif"

with rasterio.open(RASTER_PATH) as src:
    print("CRS:", src.crs)
    print("Size (width x height):", src.width, "x", src.height)
    print("Bounds:", src.bounds)
    print("Native pixel size (degrees):", src.res)
    print("Overview levels already built into the file:", src.overviews(1))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Downsample to a Spark-friendly grid
# MAGIC
# MAGIC The native grid is far too fine (billions of cells at about 500m resolution, mostly zero —
# MAGIC land, or open ocean nobody crosses) to reason about globally, and the uncompressed file
# MAGIC is 9.2 GB. Instead of reading every native pixel in Python, we ask GDAL (via rasterio)
# MAGIC to decimate directly to a 0.05-degree grid (about 5.5 km at the equator) using `Resampling.sum`
# MAGIC — it adds up the native cells inside each new, coarser cell, which is the correct way to
# MAGIC combine a *count/density* layer (unlike `average`, which would understate how much
# MAGIC traffic passes through a busy coarse cell). GDAL does this fast using the overview
# MAGIC pyramid already built into the file. Only non-zero cells are kept afterward.
# MAGIC

# COMMAND ----------

import numpy as np
import pandas as pd
from rasterio.enums import Resampling
from rasterio.transform import Affine

BLOCK = 10  # 10 native pixels/side -> ~0.05-degree cells if native res is ~0.005 degree (confirmed above)

with rasterio.open(RASTER_PATH) as src:
    out_height = src.height // BLOCK
    out_width = src.width // BLOCK
    # Resampling.sum only works for warp operations, not plain reads. Every block here is
    # exactly BLOCK x BLOCK, so average * (BLOCK*BLOCK) gives the same result as a true sum,
    # without needing the warp API. Reading as float64 avoids premature rounding.
    data = src.read(1, out_shape=(out_height, out_width), resampling=Resampling.average, out_dtype="float64")
    data = data * (BLOCK * BLOCK)
    out_transform = src.transform * Affine.scale(src.width / out_width, src.height / out_height)

nz_rows, nz_cols = np.nonzero(data)
lons, lats = rasterio.transform.xy(out_transform, nz_rows, nz_cols)

pdf = pd.DataFrame({
    "lat": lats,
    "lon": lons,
    "traffic_density": np.round(data[nz_rows, nz_cols]).astype("int64"),
})
print(f"{len(pdf):,} non-zero 0.05-degree cells kept (out of ~{out_height * out_width:,} possible globally)")

sdf = spark.createDataFrame(pdf)
sdf.write.format("delta").mode("overwrite").saveAsTable("workspace.global_shipping.traffic_density_grid")
display(sdf.orderBy(sdf.traffic_density.desc()).limit(20))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2 — load the World Port Index
# MAGIC
# MAGIC The ArcGIS Hub CSV download button doesn't give a stable, copyable URL — it just
# MAGIC downloads straight to your computer. So upload the file by hand instead of `wget`:
# MAGIC
# MAGIC 1. In the left sidebar, go to **Catalog**.
# MAGIC 2. Navigate to **workspace → global_shipping → raw_data** (the volume created in Step 0).
# MAGIC 3. Click **Upload to this volume**, and select the CSV file you already downloaded
# MAGIC    from ArcGIS Hub (check your Downloads folder — something like `World_Port_Index.csv`).
# MAGIC 4. Once it finishes uploading, run the cell below. If the uploaded filename is
# MAGIC    different from `world_port_index.csv`, update `PORT_CSV_PATH` to match.

# COMMAND ----------

# MAGIC %sh
# MAGIC ls -la /Volumes/workspace/global_shipping/raw_data/
# MAGIC

# COMMAND ----------

PORT_CSV_PATH = "/Volumes/workspace/global_shipping/raw_data/World_Port_Index.csv"

ports = (
    spark.read.option("header", True)
    .option("inferSchema", True)
    .csv(PORT_CSV_PATH)
)
print(f"{ports.count():,} ports loaded")
ports.write.format("delta").mode("overwrite").saveAsTable("workspace.global_shipping.world_port_index")
display(ports.limit(10))
