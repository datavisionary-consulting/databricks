# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# MAGIC %md
# MAGIC # Global Shipping Chokepoints — 02: Find and Label the Real Chokepoints
# MAGIC
# MAGIC Notebook 01 showed something important: the *globally* busiest 0.05-degree cells on
# MAGIC Earth are not Suez or Malacca, they're the Danish Straits (heavy short-haul ferry and
# MAGIC regional traffic inflates raw position counts there). Raw traffic density measures how
# MAGIC often a ship passed, not how much trade was riding on it — so instead of trusting a
# MAGIC naive "top N density cells" ranking, this notebook looks up the world's known strategic
# MAGIC trade chokepoints by their real geographic coordinates, and pulls each one's *actual*
# MAGIC measured traffic density from the same real data. That's the honest way to build the
# MAGIC comparison this project is actually about.

# COMMAND ----------

traffic = spark.table("workspace.global_shipping.traffic_density_grid")
ports = spark.table("workspace.global_shipping.world_port_index")

print(f"Traffic grid: {traffic.count():,} cells")
print(f"World Port Index: {ports.count():,} ports")
ports.printSchema()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Known strategic chokepoints
# MAGIC
# MAGIC Real, publicly documented coordinates for the world's major shipping chokepoints —
# MAGIC the narrow passages a huge share of global seaborne trade has no practical alternative
# MAGIC to using. Bounding boxes are drawn generously around each strait/canal's real extent so
# MAGIC the aggregation below catches the actual shipping lane, not just its exact center point.
# MAGIC The Danish Straits are included because notebook 01 showed real, heavy traffic there —
# MAGIC it's the entrance to the whole Baltic Sea, so it belongs in this comparison too.

# COMMAND ----------

# (name, lat_min, lat_max, lon_min, lon_max)
CHOKEPOINTS = [
    ("Strait of Malacca",   1.0,  6.5,  98.0, 104.5),
    ("Suez Canal",         29.8, 31.5,  32.1,  32.6),
    ("Panama Canal",        8.8,  9.4, -80.1, -79.5),
    ("Strait of Hormuz",   25.8, 27.2,  55.5,  57.0),
    ("Bab-el-Mandeb",      11.8, 13.5,  42.5,  44.0),
    ("Danish Straits",     54.5, 58.0,   9.5,  13.5),
    ("Strait of Dover",    50.7, 51.3,   1.0,   2.2),
    ("Strait of Gibraltar",35.7, 36.2,  -5.9,  -5.2),
    ("Bosphorus Strait",   40.9, 41.3,  28.8,  29.3),
]

# COMMAND ----------

from pyspark.sql import functions as F

rows = []
for name, lat_min, lat_max, lon_min, lon_max in CHOKEPOINTS:
    agg = (
        traffic.filter(
            (F.col("lat") >= lat_min) & (F.col("lat") <= lat_max)
            & (F.col("lon") >= lon_min) & (F.col("lon") <= lon_max)
        )
        .agg(
            F.sum("traffic_density").alias("total_traffic"),
            F.count("*").alias("n_cells"),
        )
        .collect()[0]
    )
    rows.append({
        "chokepoint": name,
        "total_traffic": agg["total_traffic"] or 0,
        "n_cells_with_traffic": agg["n_cells"],
        "lat_min": lat_min, "lat_max": lat_max, "lon_min": lon_min, "lon_max": lon_max,
    })

import pandas as pd

chokepoints_df = pd.DataFrame(rows).sort_values("total_traffic", ascending=False).reset_index(drop=True)
chokepoints_df["share_of_ranked_total"] = chokepoints_df["total_traffic"] / chokepoints_df["total_traffic"].sum()
display(chokepoints_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Label each chokepoint with its nearest real port
# MAGIC
# MAGIC Pulls the World Port Index port closest to each chokepoint's center, so the final
# MAGIC output reads with a real place name (e.g. "Singapore" next to Strait of Malacca)
# MAGIC instead of just coordinates.

# COMMAND ----------

import numpy as np

ports_pdf = ports.select(
    F.col("PORT_NAME"), F.col("COUNTRY"), F.col("LATITUDE"), F.col("LONGITUDE")
).toPandas()

def nearest_port(lat, lon):
    d2 = (ports_pdf["LATITUDE"] - lat) ** 2 + (ports_pdf["LONGITUDE"] - lon) ** 2
    idx = d2.idxmin()
    return ports_pdf.loc[idx, "PORT_NAME"], ports_pdf.loc[idx, "COUNTRY"]

chokepoints_df["center_lat"] = (chokepoints_df["lat_min"] + chokepoints_df["lat_max"]) / 2
chokepoints_df["center_lon"] = (chokepoints_df["lon_min"] + chokepoints_df["lon_max"]) / 2
nearest = chokepoints_df.apply(lambda r: nearest_port(r["center_lat"], r["center_lon"]), axis=1)
chokepoints_df["nearest_port"] = [n[0] for n in nearest]
chokepoints_df["nearest_port_country"] = [n[1] for n in nearest]

display(chokepoints_df[[
    "chokepoint", "total_traffic", "share_of_ranked_total",
    "nearest_port", "nearest_port_country",
]])

# COMMAND ----------

# MAGIC %md
# MAGIC ## Save the result

# COMMAND ----------

result = spark.createDataFrame(chokepoints_df)
result.write.format("delta").mode("overwrite").saveAsTable("workspace.global_shipping.known_chokepoints_ranked")
print("Saved workspace.global_shipping.known_chokepoints_ranked")

# COMMAND ----------

# MAGIC %md
# MAGIC ## What's next
# MAGIC
# MAGIC This table has real traffic-density rankings, but density alone still isn't money —
# MAGIC it's back to the same honest caveat from notebook 01, just at a smaller, curated scale
# MAGIC now. Notebook 03 will pull real trade values from UN Comtrade for the countries on
# MAGIC either side of each chokepoint, to turn "how much traffic" into "how many dollars of
# MAGIC trade are actually riding through here" — the number a business reader actually cares
# MAGIC about.