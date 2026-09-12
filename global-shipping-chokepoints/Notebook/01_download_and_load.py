# Databricks notebook source
# MAGIC %md
# MAGIC # Global Shipping Chokepoints — 01: Download and Load
# MAGIC
# MAGIC Downloads two real, free, global datasets and loads them into Delta tables:
# MAGIC
# MAGIC 1. **World Bank Global Shipping Traffic Density** — a worldwide grid built from real
# MAGIC    AIS ship positions (Jan 2015 - Feb 2021), ~500m resolution at the equator, commercial
# MAGIC    vessels only. This is the real "did a ship actually pass through here" data.
# MAGIC    Catalog page: https://datacatalog.worldbank.org/search/dataset/0037580/global-shipping-traffic-density
# MAGIC 2. **NGA World Port Index** — ~3,700 ports worldwide with name, country, and coordinates,
# MAGIC    used to label whatever chokepoints the density data turns up.
# MAGIC    Source used: https://hub.arcgis.com/datasets/EDT::world-port-index (CSV export)

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
# MAGIC **Action needed:** open the World Bank catalog page above, find the download link for
# MAGIC the "Global Ship Density - Commercial Ships" GeoTIFF (~458 MB), and paste it into the
# MAGIC `wget` command below in place of `PASTE_URL_HERE`. Catalog download links carry a token
# MAGIC and can't be hardcoded reliably.

# COMMAND ----------

# MAGIC %sh
# MAGIC cd /Volumes/workspace/global_shipping/raw_data
# MAGIC wget -O ShipDensity_Commercial1.tif "PASTE_URL_HERE"
# MAGIC ls -lh

# COMMAND ----------

# MAGIC %pip install rasterio
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

import rasterio

RASTER_PATH = "/Volumes/workspace/global_shipping/raw_data/ShipDensity_Commercial1.tif"

with rasterio.open(RASTER_PATH) as src:
    print("CRS:", src.crs)
    print("Size (width x height):", src.width, "x", src.height)
    print("Bounds:", src.bounds)
    print("Native pixel size (degrees):", src.res)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Downsample to a Spark-friendly grid
# MAGIC
# MAGIC The native grid is far too fine (hundreds of millions of cells, mostly zero — land, or
# MAGIC open ocean nobody crosses) to reason about globally. We block-sum to a 0.05-degree grid
# MAGIC (~5.5 km at the equator): coarse enough to keep row counts sane, fine enough that a
# MAGIC strait only a few km wide (Malacca, Bab-el-Mandeb) still shows up as a small cluster of
# MAGIC very hot cells rather than getting averaged away. Only non-zero cells are kept.

# COMMAND ----------

import numpy as np
import pandas as pd

BLOCK = 10  # 10 native pixels/side -> 0.05-degree cells, since native resolution is 0.005 degree

rows = []
with rasterio.open(RASTER_PATH) as src:
    strip_height = 2000
    for row_off in range(0, src.height, strip_height):
        h = min(strip_height, src.height - row_off)
        window = rasterio.windows.Window(0, row_off, src.width, h)
        data = src.read(1, window=window)
        if data.max() == 0:
            continue
        h_trim = (data.shape[0] // BLOCK) * BLOCK
        w_trim = (data.shape[1] // BLOCK) * BLOCK
        block_sum = (
            data[:h_trim, :w_trim]
            .reshape(h_trim // BLOCK, BLOCK, w_trim // BLOCK, BLOCK)
            .sum(axis=(1, 3))
        )
        nz_rows, nz_cols = np.nonzero(block_sum)
        for r, c in zip(nz_rows, nz_cols):
            lon, lat = src.xy(row_off + r * BLOCK, c * BLOCK)
            rows.append((float(lat), float(lon), int(block_sum[r, c])))

pdf = pd.DataFrame(rows, columns=["lat", "lon", "traffic_density"])
print(f"{len(pdf):,} non-zero 0.05-degree cells kept (out of ~26M possible globally)")

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

PORT_CSV_PATH = "/Volumes/workspace/global_shipping/raw_data/world_port_index.csv"

ports = (
    spark.read.option("header", True)
    .option("inferSchema", True)
    .csv(PORT_CSV_PATH)
)
print(f"{ports.count():,} ports loaded")
ports.write.format("delta").mode("overwrite").saveAsTable("workspace.global_shipping.world_port_index")
display(ports.limit(10))
