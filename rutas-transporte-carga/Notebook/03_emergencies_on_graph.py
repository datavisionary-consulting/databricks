# Databricks notebook source
# MAGIC %md
# MAGIC # 03 — Road emergencies on the graph
# MAGIC
# MAGIC Places every MTC-COES road emergency (Jan 1 – Aug 20, 2026) on an edge of the road graph built
# MAGIC in 02, so later notebooks can attach an interruption frequency to each road segment.
# MAGIC
# MAGIC | Source (exact portal title) | File | Publisher |
# MAGIC |---|---|---|
# MAGIC | Emergencias en la Red Vial Nacional | `3. Reporte Emergencias 01.01 al 20.08.2026 COES-MTC.csv` + data dictionary XLSX + metadata PDF | MTC-COES |
# MAGIC
# MAGIC ## Real quirks found before writing this (2026-11-25)
# MAGIC
# MAGIC 1. Scripted download from the portal is blocked (same WAF as in 01); the files were downloaded
# MAGIC    from a browser and uploaded to `workspace.rutas_transporte.raw_data`.
# MAGIC 2. CSV: `;` separator, cp1252 encoding, 1,362 rows, 22 columns.
# MAGIC 3. Column names differ from the data dictionary: `FECHA_OCURRENCIA` (dict: FECHA),
# MAGIC    `DEPARTEMENTO` (typo), `TRAMO_AFECADO` (typo). They are renamed here.
# MAGIC 4. `FECHA_CIERRE` = end of works, back to NORMAL (per the dictionary). It is the duration of the
# MAGIC    emergency, **not** of the traffic cut. 122 rows have no close date (still open at cut-off).
# MAGIC 5. Every `AFECTACION` carries an official kilometre range (`Km 720+000 - Km 781+000`). It gives a
# MAGIC    second, independent way to place the event, used here to validate the coordinates.
# MAGIC
# MAGIC ## Method
# MAGIC
# MAGIC - **Primary: coordinates.** Each event goes to the nearest edge **of its own route**
# MAGIC   (`RED_AFECTADA` = `cCodRuta`). The nearest edge of any route is also recorded, to expose
# MAGIC   coordinates that sit on another road.
# MAGIC - **Check: kilometres.** The matched edge inherits `dkmInicio`/`dkmFinal` of its MTC record; the
# MAGIC   event's km range should overlap it.
# MAGIC - Nothing is dropped in this run. Distances and the km check are reported so the acceptance
# MAGIC   threshold is chosen from data, not assumed.

# COMMAND ----------

# MAGIC %pip install -q shapely==2.0.6 pyproj==3.6.1

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import re
import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer

RAW = "/Volumes/workspace/rutas_transporte/raw_data/3. Reporte Emergencias 01.01 al 20.08.2026 COES-MTC.csv"
T_EDGES = "workspace.rutas_transporte.silver_graph_edges"
T_BRONZE = "workspace.rutas_transporte.bronze_emergencias_2026"
T_MATCH = "workspace.rutas_transporte.silver_emergencias_on_edges"
T_ROUTES = "workspace.rutas_transporte.silver_emergencias_route_coverage"

to_utm = Transformer.from_crs(4326, 32718, always_xy=True)

def reproject(geoms, tr):
    return shapely.transform(geoms, lambda xy: np.column_stack(tr.transform(xy[:, 0], xy[:, 1])))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Load and type the CSV → `bronze_emergencias_2026`

# COMMAND ----------

raw = pd.read_csv(RAW, sep=";", encoding="cp1252", dtype=str, keep_default_na=False)
EXPECTED = ["ID_EMERGENCIA", "CODIGO_REPORTE", "FECHA_OCURRENCIA", "CLASE_FENOMENO", "FENOMENO", "EVENTO",
            "DEPARTEMENTO", "PROVINCIA", "DISTRITO", "AFECTACION", "RED_AFECTADA", "TRAMO_AFECADO",
            "SECTOR_AFECTADO", "HECHOS", "NOVEDADES", "FUENTE", "ESTADO_INICIAL", "FECHA_CIERRE",
            "ESTADO_ACTUAL", "LATITUD", "LONGITUD", "FECHA_CORTE"]
assert list(raw.columns) == EXPECTED, f"columns changed: {list(raw.columns)}"

em = raw.rename(columns={"FECHA_OCURRENCIA": "FECHA", "DEPARTEMENTO": "DEPARTAMENTO",
                         "TRAMO_AFECADO": "TRAMO_AFECTADO"}).copy()
em = em.apply(lambda s: s.str.strip())
em["ID_EMERGENCIA"] = em["ID_EMERGENCIA"].astype(int)
em["FECHA"] = pd.to_datetime(em["FECHA"], format="%d/%m/%Y")
em["FECHA_CIERRE"] = pd.to_datetime(em["FECHA_CIERRE"].replace("", None), format="%d/%m/%Y")
em["LATITUD"] = em["LATITUD"].astype(float)
em["LONGITUD"] = em["LONGITUD"].astype(float)
em["dias_hasta_normal"] = (em["FECHA_CIERRE"] - em["FECHA"]).dt.days      # NaN = still open at cut-off

KM = re.compile(r"Km\.?\s*(\d+)\s*\+\s*(\d+)", re.I)
def km_range(text):
    hits = [int(a) + int(b) / 1000 for a, b in KM.findall(text)]      # "720+500" -> 720.5 km
    if not hits:
        return np.nan, np.nan
    return min(hits), max(hits)

em[["km_ini", "km_fin"]] = em["AFECTACION"].apply(lambda t: pd.Series(km_range(t)))

print(f"rows={len(em)}  dates {em['FECHA'].min():%Y-%m-%d}..{em['FECHA'].max():%Y-%m-%d}  "
      f"km parsed={em['km_ini'].notna().sum()}  open={em['FECHA_CIERRE'].isna().sum()}")
assert em["dias_hasta_normal"].dropna().ge(0).all(), "close date before occurrence"

(spark.createDataFrame(em).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(T_BRONZE))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Route coverage: which emergency routes exist in the 2016 graph

# COMMAND ----------

edges = spark.table(T_EDGES).select("edge_id", "u", "v", "comp", "cCodRuta", "tramo_id", "dkmInicio",
                                    "dkmFinal", "length_km", "geometry_wkt").toPandas()
graph_routes = set(edges["cCodRuta"])

cov = (em.groupby("RED_AFECTADA")
         .agg(eventos=("ID_EMERGENCIA", "count"),
              interrumpido_inicial=("ESTADO_INICIAL", lambda s: int((s == "INTERRUMPIDO").sum())))
         .reset_index().rename(columns={"RED_AFECTADA": "ruta"}))
cov["en_grafo"] = cov["ruta"].isin(graph_routes)
cov = cov.sort_values("eventos", ascending=False)
spark.createDataFrame(cov).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(T_ROUTES)
display(cov.groupby("en_grafo").agg(rutas=("ruta", "count"), eventos=("eventos", "sum")).reset_index())
display(cov[~cov["en_grafo"]])

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Snap each event to the graph

# COMMAND ----------

edge_geom = reproject(shapely.from_wkt(edges["geometry_wkt"].values), to_utm)
ex, ey = to_utm.transform(em["LONGITUD"].values, em["LATITUD"].values)
pts = shapely.points(ex, ey)

# nearest edge of any route
tree_all = shapely.STRtree(edge_geom)
p_idx, e_idx = tree_all.query_nearest(pts, return_distance=False, all_matches=False)
near_any = pd.Series(e_idx, index=p_idx)

# nearest edge of the event's own route
own_edge = np.full(len(em), -1)
own_dist = np.full(len(em), np.nan)
for route, rows in em.groupby("RED_AFECTADA").groups.items():
    cand = np.where(edges["cCodRuta"].values == route)[0]
    if len(cand) == 0:
        continue
    rows = np.asarray([em.index.get_loc(r) for r in rows])
    t = shapely.STRtree(edge_geom[cand])
    pi, ei = t.query_nearest(pts[rows], return_distance=False, all_matches=False)
    own_edge[rows[pi]] = cand[ei]
    own_dist[rows[pi]] = shapely.distance(pts[rows[pi]], edge_geom[cand[ei]])

m = em[["ID_EMERGENCIA", "FECHA", "FECHA_CIERRE", "dias_hasta_normal", "FENOMENO", "EVENTO",
        "ESTADO_INICIAL", "ESTADO_ACTUAL", "RED_AFECTADA", "km_ini", "km_fin", "LATITUD", "LONGITUD"]].copy()
any_i = near_any.reindex(range(len(em))).values
m["edge_any"] = edges["edge_id"].values[any_i]
m["ruta_any"] = edges["cCodRuta"].values[any_i]
m["dist_any_m"] = shapely.distance(pts, edge_geom[any_i])
has_own = own_edge >= 0
m["edge_id"] = np.where(has_own, edges["edge_id"].values[np.where(has_own, own_edge, 0)], -1)
m["dist_m"] = own_dist

# km check against the MTC record of the matched edge (1 km slack for rounding of progresivas)
rec_ini = np.where(has_own, edges["dkmInicio"].values[np.where(has_own, own_edge, 0)], np.nan)
rec_fin = np.where(has_own, edges["dkmFinal"].values[np.where(has_own, own_edge, 0)], np.nan)
m["rec_km_ini"], m["rec_km_fin"] = rec_ini, rec_fin
m["km_coincide"] = has_own & (m["km_ini"] <= rec_fin + 1) & (m["km_fin"] >= rec_ini - 1)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Match quality (no threshold applied yet)

# COMMAND ----------

def band(d):
    return pd.cut(d, [-0.1, 100, 500, 1000, 5000, 20000, np.inf],
                  labels=["<=100 m", "100-500 m", "0.5-1 km", "1-5 km", "5-20 km", ">20 km"])

m["banda_dist"] = band(m["dist_m"]).astype(str).where(has_own, "ruta no en grafo")
# another route's edge is clearly closer than the event's own route (coordinates on another road?)
m["otra_ruta_mas_cerca"] = has_own & (m["ruta_any"] != m["RED_AFECTADA"]) & (m["dist_any_m"] + 1 < m["dist_m"])
q = (m.groupby("banda_dist")
       .agg(eventos=("ID_EMERGENCIA", "count"), km_coincide=("km_coincide", "sum"),
            otra_ruta_mas_cerca=("otra_ruta_mas_cerca", "sum"))
       .reset_index())
display(q)
print("distance to own route, percentiles (m):",
      np.nanpercentile(m["dist_m"], [50, 75, 90, 95, 99]).round(0))
print("km check agrees:", int(m["km_coincide"].sum()), "of", int(has_own.sum()), "events on graph routes")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Acceptance rule (chosen from section 4, run of 2026-11-25)
# MAGIC
# MAGIC What section 4 showed:
# MAGIC - 1,235 of 1,277 events on graph routes lie within 100 m of their own route (median 7 m, p95 49 m).
# MAGIC   The coordinates are reliable.
# MAGIC - 16 events lie > 20 km from their own route but 1–44 m from **another** route: the route code
# MAGIC   in the report is wrong, the point is on a real road.
# MAGIC - The km check fails for 198 events sitting on their own route (≤ 100 m), with offsets up to
# MAGIC   > 100 km (PE-3N median 31 km). The 2026 kilometre markers do not follow the 2016 shapefile on
# MAGIC   several routes, so km cannot validate the match; it is kept as information only.
# MAGIC
# MAGIC Rule:
# MAGIC 1. `ruta_propia`: own route edge within `OWN_MAX_M`.
# MAGIC 2. `ruta_corregida`: own route farther than `RELABEL_MIN_M` (or not in the graph) **and** an edge
# MAGIC    of another route within `ANY_MAX_M` → assigned to that edge; the reported route is kept in
# MAGIC    `RED_AFECTADA` and the edge's route in `ruta_any`.
# MAGIC 3. Anything else: `no_ubicado` (not used downstream, reported).

# COMMAND ----------

OWN_MAX_M, RELABEL_MIN_M, ANY_MAX_M = 500, 5000, 100

own_ok = has_own & (m["dist_m"] <= OWN_MAX_M)
relabel = ~own_ok & (~has_own | (m["dist_m"] > RELABEL_MIN_M)) & (m["dist_any_m"] <= ANY_MAX_M)
m["metodo"] = np.select([own_ok, relabel], ["ruta_propia", "ruta_corregida"], default="no_ubicado")
m["edge_final"] = np.select([own_ok, relabel], [m["edge_id"], m["edge_any"]], default=-1).astype("int64")
m["dist_final_m"] = np.select([own_ok, relabel], [m["dist_m"], m["dist_any_m"]], default=np.nan)

summary = (m.groupby("metodo").agg(eventos=("ID_EMERGENCIA", "count"),
                                   interrumpido=("ESTADO_INICIAL", lambda s: int((s == "INTERRUMPIDO").sum())))
             .reset_index())
display(summary)

# COMMAND ----------

m["banda_dist"] = m["banda_dist"].astype(str)
(spark.createDataFrame(m).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(T_MATCH))
spark.sql(f"COMMENT ON TABLE {T_MATCH} IS 'MTC-COES emergencies 2026 placed on silver_graph_edges. "
          f"Use edge_final (-1 = no_ubicado). metodo: ruta_propia / ruta_corregida / no_ubicado.'")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Emergencies per edge → `silver_edge_emergencias`
# MAGIC
# MAGIC Observation window: 2026-01-01 to 2026-08-20 (one rainy season). Counts, not probabilities yet:
# MAGIC turning them into an interruption probability is a modelling choice for 04.

# COMMAND ----------

T_EDGE_STATS = "workspace.rutas_transporte.silver_edge_emergencias"
ok = m[m["edge_final"] >= 0].copy()
ok["lluvia"] = ok["FENOMENO"].eq("Precipitaciones Pluviales")
ok["interrumpido"] = ok["ESTADO_INICIAL"].eq("INTERRUMPIDO")
ok["abierta"] = ok["FECHA_CIERRE"].isna()

stats = (ok.groupby("edge_final")
           .agg(eventos=("ID_EMERGENCIA", "count"),
                eventos_lluvia=("lluvia", "sum"),
                interrumpido_inicial=("interrumpido", "sum"),
                abiertas_al_corte=("abierta", "sum"),
                dias_hasta_normal_mediana=("dias_hasta_normal", "median"),
                dias_hasta_normal_max=("dias_hasta_normal", "max"),
                tipos=("EVENTO", lambda s: ", ".join(f"{k} ({v})" for k, v in s.value_counts().items())))
           .reset_index().rename(columns={"edge_final": "edge_id"}))
stats = stats.merge(edges[["edge_id", "cCodRuta", "tramo_id", "length_km", "comp"]], on="edge_id", how="left")
stats["eventos_por_100km"] = stats["eventos"] / stats["length_km"] * 100
stats = stats.sort_values("eventos", ascending=False)
spark.createDataFrame(stats).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(T_EDGE_STATS)

print(f"edges with >=1 emergency: {len(stats)} of {len(edges)} "
      f"({stats['length_km'].sum():,.0f} km of {edges['length_km'].sum():,.0f} km)")
display(stats.head(20))
