# Databricks notebook source
# MAGIC %md
# MAGIC # Global Shipping Chokepoints — 03: The Real Cross-Check
# MAGIC
# MAGIC Notebook 02 ranked chokepoints by raw AIS traffic density and found the Danish region
# MAGIC (Oresund Strait) dominating with ~69% of the measured total — 900x the Panama Canal.
# MAGIC That's real, but it measures *how often a ship passed*, not *how much cargo it carried*.
# MAGIC
# MAGIC This notebook pulls the IMF's own **PortWatch** dataset — a public, unauthenticated,
# MAGIC real dataset (no API key needed) tracking daily vessel transits and **cargo-carrying
# MAGIC capacity** at the same 28 named global chokepoints, built from real AIS signals on
# MAGIC ~90,000 ships. It's the honest independent cross-check this project needs: our own
# MAGIC ship-position density vs. the IMF's own measured cargo capacity, for the same places.
# MAGIC
# MAGIC Source: https://portwatch.imf.org/pages/data-and-methodology — public ArcGIS
# MAGIC FeatureServer, verified working with a plain unauthenticated request.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Map our chokepoints to PortWatch's official IDs
# MAGIC
# MAGIC PortWatch names 28 canonical global chokepoints. Eight of our nine from notebook 02
# MAGIC map directly onto theirs (Panama Canal, Bosporus/Bosphorus is the same strait despite
# MAGIC the spelling difference). Our broader "Danish Straits" box maps to their more specific
# MAGIC "Oresund Strait" — one real strait inside that same region, not the identical footprint,
# MAGIC which is worth being precise about rather than pretending they're the same box.

# COMMAND ----------

CHOKEPOINT_ID_MAP = {
    "Strait of Malacca":    ("chokepoint5",  "Malacca Strait"),
    "Suez Canal":           ("chokepoint1",  "Suez Canal"),
    "Panama Canal":         ("chokepoint2",  "Panama Canal"),
    "Strait of Hormuz":     ("chokepoint6",  "Strait of Hormuz"),
    "Bab-el-Mandeb":        ("chokepoint4",  "Bab el-Mandeb Strait"),
    "Danish Straits":       ("chokepoint10", "Oresund Strait"),
    "Strait of Dover":      ("chokepoint9",  "Dover Strait"),
    "Strait of Gibraltar":  ("chokepoint8",  "Gibraltar Strait"),
    "Bosphorus Strait":     ("chokepoint3",  "Bosporus Strait"),
}

# COMMAND ----------

# MAGIC %md
# MAGIC ## Pull the last full year of daily data for each chokepoint
# MAGIC
# MAGIC The public FeatureServer needs no auth, just an HTTP GET. We average over a full year
# MAGIC (rather than a single day) to get a stable, representative number instead of one day's
# MAGIC noise — shipping traffic varies a lot day to day.

# COMMAND ----------

import requests
import pandas as pd
from datetime import date, timedelta

BASE_URL = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/services/Daily_Chokepoints_Data/FeatureServer/0/query"

end_date = date.today() - timedelta(days=14)  # avoid the last ~2 weeks: data can still be backfilling
start_date = end_date - timedelta(days=365)

rows = []
for our_name, (portid, portwatch_name) in CHOKEPOINT_ID_MAP.items():
    params = {
        "where": f"portid='{portid}' AND date >= DATE '{start_date}' AND date <= DATE '{end_date}'",
        "outFields": "date,n_total,capacity",
        "f": "json",
        "resultRecordCount": 1000,
    }
    resp = requests.get(BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    features = resp.json().get("features", [])
    if not features:
        print(f"WARNING: no data returned for {our_name} ({portid})")
        continue
    daily = pd.DataFrame([f["attributes"] for f in features])
    rows.append({
        "chokepoint": our_name,
        "portwatch_name": portwatch_name,
        "portwatch_days_available": len(daily),
        "avg_daily_vessels": daily["n_total"].mean(),
        "avg_daily_capacity": daily["capacity"].mean(),
    })

portwatch_df = pd.DataFrame(rows)
display(portwatch_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Join with our own traffic-density ranking from notebook 02
# MAGIC
# MAGIC This is the actual point of the whole project: put our own measured ship-position
# MAGIC density share next to the IMF's own measured cargo-capacity share, for the same real
# MAGIC places, and let the gap between them speak for itself.

# COMMAND ----------

ours = spark.table("workspace.global_shipping.known_chokepoints_ranked").toPandas()

final = ours.merge(portwatch_df, on="chokepoint", how="left")
final["capacity_share"] = final["avg_daily_capacity"] / final["avg_daily_capacity"].sum()
final = final.sort_values("avg_daily_capacity", ascending=False).reset_index(drop=True)

display(final[[
    "chokepoint", "nearest_port", "nearest_port_country",
    "share_of_ranked_total", "avg_daily_vessels", "avg_daily_capacity", "capacity_share",
]].rename(columns={"share_of_ranked_total": "our_traffic_density_share"}))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Save the final comparison

# COMMAND ----------

result = spark.createDataFrame(final)
result.write.format("delta").mode("overwrite").saveAsTable("workspace.global_shipping.chokepoints_final_comparison")
print("Saved workspace.global_shipping.chokepoints_final_comparison")
