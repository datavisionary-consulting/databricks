# Databricks notebook source
# MAGIC %md
# MAGIC # Global Shipping Chokepoints — 05: A Real Map, Rendered in Databricks
# MAGIC
# MAGIC The hand-drawn SVG map used for the web version doesn't read as a "real" map --
# MAGIC no coastline detail, no place labels, no basemap. This notebook renders the same real
# MAGIC data with an actual basemap (streets/labels via free, tokenless map tiles) using Plotly,
# MAGIC which `display()` in Databricks renders natively. Take a screenshot of whichever cell's
# MAGIC output looks best, or use the "Download as PNG" option in Plotly's own toolbar
# MAGIC (top-right of the chart) to export a static image straight from Databricks.

# COMMAND ----------

# MAGIC %pip install plotly
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

from pyspark.sql import functions as F
import plotly.express as px
import plotly.graph_objects as go

# Re-aggregate to a coarser grid for plotting -- 60,000+ points renders very slowly
# in an interactive Plotly map; ~10,000-15,000 is smooth and still shows the real lanes.
PLOT_GRID_DEGREES = 1.0

traffic = spark.table("workspace.global_shipping.traffic_density_grid")
plot_grid = (
    traffic
    .withColumn("grid_lat", F.floor(F.col("lat") / PLOT_GRID_DEGREES) * PLOT_GRID_DEGREES)
    .withColumn("grid_lon", F.floor(F.col("lon") / PLOT_GRID_DEGREES) * PLOT_GRID_DEGREES)
    .groupBy("grid_lat", "grid_lon")
    .agg(F.sum("traffic_density").alias("traffic_density"))
    .toPandas()
)
print(f"Plotting {len(plot_grid):,} cells")

chokepoints = spark.table("workspace.global_shipping.chokepoints_final_comparison").toPandas()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Option A: density heatmap + chokepoint markers on a real basemap

# COMMAND ----------

fig = go.Figure()

fig.add_trace(go.Densitymapbox(
    lat=plot_grid["grid_lat"], lon=plot_grid["grid_lon"], z=plot_grid["traffic_density"],
    radius=10, colorscale="Teal", showscale=False, opacity=0.75,
))

fig.add_trace(go.Scattermapbox(
    lat=chokepoints["center_lat"], lon=chokepoints["center_lon"],
    mode="markers+text",
    marker=dict(
        size=8 + 26 * (chokepoints["capacity_share"] / chokepoints["capacity_share"].max()) ** 0.5,
        color="#A9782E", opacity=0.9,
    ),
    text=chokepoints["chokepoint"],
    textposition="top center",
    textfont=dict(color="white", size=12),
    hovertext=[
        f"{row.chokepoint}<br>Density share: {row.share_of_ranked_total:.1%}<br>Capacity share (IMF): {row.capacity_share:.1%}"
        for row in chokepoints.itertuples()
    ],
    hoverinfo="text",
))

fig.update_layout(
    mapbox_style="carto-darkmatter",  # free, no token needed
    mapbox_zoom=1, mapbox_center={"lat": 20, "lon": 20},
    margin=dict(l=0, r=0, t=40, b=0),
    height=650,
    title="Real AIS traffic density vs. real chokepoint capacity (brass markers, sized by IMF capacity share)",
    showlegend=False,
)
fig.show()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Option B: same data, a lighter basemap (better if the dark version prints too dark)

# COMMAND ----------

fig2 = go.Figure(fig)
fig2.update_layout(mapbox_style="carto-positron")
fig2.show()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Option C: just the 9 chokepoints, no density layer, paired-bar style hover
# MAGIC
# MAGIC Useful if the density heatmap ends up feeling too busy for a clean static image.

# COMMAND ----------

fig3 = px.scatter_mapbox(
    chokepoints, lat="center_lat", lon="center_lon",
    size="avg_daily_capacity", color="capacity_share",
    color_continuous_scale="Oranges",
    hover_name="chokepoint",
    hover_data={"share_of_ranked_total": ":.1%", "capacity_share": ":.1%", "center_lat": False, "center_lon": False},
    zoom=1, height=600,
    title="The 9 chokepoints, sized and colored by real cargo capacity share",
)
fig3.update_layout(mapbox_style="carto-darkmatter", margin=dict(l=0, r=0, t=40, b=0))
fig3.show()
