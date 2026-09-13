# Databricks notebook source
# MAGIC %md
# MAGIC # Global Shipping Chokepoints — 04: Export a Light Version for the Web Map
# MAGIC
# MAGIC The full traffic grid (3,040,763 rows) is too big and too fine-grained to put in a
# MAGIC browser map. This notebook re-aggregates it to a coarser 0.5-degree grid (still real
# MAGIC data, just fewer, bigger cells — good enough for a world-scale heat map) and prints it
# MAGIC as compact JSON directly in the cell output, along with the final chokepoint comparison
# MAGIC table, so both can be copied straight out of the downloaded notebook without needing to
# MAGIC download a separate file from a volume.

# COMMAND ----------

from pyspark.sql import functions as F

GRID_DEGREES = 0.5  # heat-map resolution: coarse enough for a world map, still built from real data

traffic = spark.table("workspace.global_shipping.traffic_density_grid")

coarse = (
    traffic
    .withColumn("grid_lat", F.floor(F.col("lat") / GRID_DEGREES) * GRID_DEGREES)
    .withColumn("grid_lon", F.floor(F.col("lon") / GRID_DEGREES) * GRID_DEGREES)
    .groupBy("grid_lat", "grid_lon")
    .agg(F.sum("traffic_density").alias("traffic_density"))
)

print(f"Coarse grid cells: {coarse.count():,} (down from {traffic.count():,} at native 0.05-degree resolution)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Print as compact JSON
# MAGIC
# MAGIC Rounds density to the nearest thousand and drops the smallest 50% of cells (the
# MAGIC faintest, least visually meaningful traffic) to keep the printed payload small — this
# MAGIC is purely a size cut for the visualization, the full real data stays in the Delta table
# MAGIC untouched for anyone who wants the complete grid.

# COMMAND ----------

import json

pdf = coarse.toPandas()
median_density = pdf["traffic_density"].median()
pdf = pdf[pdf["traffic_density"] >= median_density].copy()
pdf["traffic_density"] = (pdf["traffic_density"] / 1000).round().astype("int64")  # store in thousands

records = pdf.round({"grid_lat": 2, "grid_lon": 2}).to_dict(orient="records")
print(f"Cells in export (>= median density): {len(records):,}")
print(json.dumps(records, separators=(",", ":")))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Print the final chokepoint comparison table as JSON too

# COMMAND ----------

final = spark.table("workspace.global_shipping.chokepoints_final_comparison").toPandas()
print(json.dumps(final.to_dict(orient="records"), default=str, separators=(",", ":")))
