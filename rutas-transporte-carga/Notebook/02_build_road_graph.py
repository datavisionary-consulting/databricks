# Databricks notebook source
# MAGIC %md
# MAGIC # 02 — Build the navigable road graph
# MAGIC
# MAGIC Turns `bronze_red_vial_2016` (3,750 polylines) into a routable graph: nodes = junctions and
# MAGIC dead ends, edges = road pieces between them, each with its real geodesic length and the
# MAGIC attributes of the MTC record it came from.
# MAGIC
# MAGIC ## Why this is not trivial (measured in 01 / README)
# MAGIC
# MAGIC Using the shapefile endpoints as-is gives **293 disconnected components** (the largest holds
# MAGIC only 51 % of the km). Two real causes:
# MAGIC 1. **T-junctions**: a road often starts on the *middle* of another road, not at one of its
# MAGIC    endpoints. The other road must be split there, or the junction does not exist in the graph.
# MAGIC 2. **Digitizing gaps**: endpoints that should meet are a few metres apart.
# MAGIC
# MAGIC The fix is explicit and parameterised: split at T-junctions and merge endpoints within a
# MAGIC tolerance `TOL_M`. Crossings where neither line ends (e.g., bridges/overpasses) are **not**
# MAGIC turned into junctions on purpose. Whatever is still disconnected afterwards is reported, not
# MAGIC forced: some of it is real geography (e.g., Loreto has roads with no land link to the rest).
# MAGIC
# MAGIC Geometry operations run in UTM 18S (EPSG:32718, metres). Edge lengths are geodesic (WGS84),
# MAGIC not UTM. The graph is undirected (`cSentido` does not encode one-way restrictions usable here).

# COMMAND ----------

# MAGIC %pip install -q shapely==2.0.6 pyproj==3.6.1 networkx==3.3

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import numpy as np
import pandas as pd
import shapely
import networkx as nx
from shapely.ops import substring
from pyproj import Transformer, Geod

SRC = "workspace.rutas_transporte.bronze_red_vial_2016"
T_NODES = "workspace.rutas_transporte.silver_graph_nodes"
T_EDGES = "workspace.rutas_transporte.silver_graph_edges"
T_COMPS = "workspace.rutas_transporte.silver_graph_components"
T_SENS = "workspace.rutas_transporte.silver_graph_tolerance_sensitivity"
T_VALID = "workspace.rutas_transporte.silver_graph_route_validation"
T_LOOPS = "workspace.rutas_transporte.silver_graph_self_loops"

TOLERANCES_M = [5, 20, 50, 100, 250]   # sensitivity sweep
TOL_M = 50                              # final choice; justified by the sweep below

ATTRS = ["Id", "cCodRuta", "dkmInicio", "dkmFinal", "dLongitud", "cSentido", "dNroCarril",
         "dAncCalzad", "cClasifica", "cDepartame", "cRegion", "cTopografi", "dVelProTra",
         "cSuperfici", "cEstadoDic"]

to_utm = Transformer.from_crs(4326, 32718, always_xy=True)
to_wgs = Transformer.from_crs(32718, 4326, always_xy=True)
geod = Geod(ellps="WGS84")

def reproject(geoms, tr):
    return shapely.transform(geoms, lambda xy: np.column_stack(tr.transform(xy[:, 0], xy[:, 1])))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Load and explode into single lines

# COMMAND ----------

roads = spark.table(SRC).select(*ATTRS, "geometry_wkt").toPandas()
geoms_wgs = shapely.from_wkt(roads["geometry_wkt"].values)
roads = roads.drop(columns="geometry_wkt")

parts_wgs, owner = shapely.get_parts(geoms_wgs, return_index=True)
parts_utm = reproject(parts_wgs, to_utm)

# geodesic km of each part, and a per-part factor to convert UTM metres -> geodesic km
geo_km = np.array([geod.geometry_length(g) / 1000 for g in parts_wgs])
utm_m = shapely.length(parts_utm)
keep = utm_m > 0
parts_utm, owner, geo_km, utm_m = parts_utm[keep], owner[keep], geo_km[keep], utm_m[keep]
km_per_m = geo_km / utm_m

print(f"records={len(roads)} parts={len(parts_utm)} geodesic_km={geo_km.sum():,.0f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Graph builder (split at T-junctions + merge endpoints within tolerance)

# COMMAND ----------

def split_at_t_junctions(lines, tol):
    """Split each line where another line's endpoint touches its interior (within tol)."""
    n = len(lines)
    ends = np.concatenate([shapely.get_point(lines, 0), shapely.get_point(lines, -1)])
    end_owner = np.concatenate([np.arange(n), np.arange(n)])
    tree = shapely.STRtree(lines)
    e_idx, l_idx = tree.query(ends, predicate="dwithin", distance=tol)
    mask = end_owner[e_idx] != l_idx
    e_idx, l_idx = e_idx[mask], l_idx[mask]
    d = shapely.line_locate_point(lines[l_idx], ends[e_idx])
    L = shapely.length(lines[l_idx])
    inner = (d > tol) & (d < L - tol)
    cuts = pd.DataFrame({"line": l_idx[inner], "d": d[inner]})

    pieces, piece_src = [], []
    cut_map = {k: np.sort(g["d"].values) for k, g in cuts.groupby("line")}
    n_cuts = 0
    for i, line in enumerate(lines):
        ds = cut_map.get(i)
        if ds is None:
            pieces.append(line); piece_src.append(i); continue
        merged = [ds[0]]
        for x in ds[1:]:
            if x - merged[-1] > tol:
                merged.append(x)
        n_cuts += len(merged)
        bounds = [0.0, *merged, line.length]
        for a, b in zip(bounds[:-1], bounds[1:]):
            if b - a > 0:
                pieces.append(substring(line, a, b)); piece_src.append(i)
    return np.array(pieces, dtype=object), np.array(piece_src), n_cuts


def cluster_points(points, tol):
    """Union-find over points closer than tol. Returns cluster id per point."""
    parent = np.arange(len(points))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    a, b = shapely.STRtree(points).query(points, predicate="dwithin", distance=tol)
    for i, j in zip(a, b):
        if i < j:
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[rj] = ri
    roots = np.array([find(i) for i in range(len(points))])
    _, cid = np.unique(roots, return_inverse=True)
    return cid


def build(lines, tol):
    pieces, src, n_cuts = split_at_t_junctions(lines, tol)
    m = len(pieces)
    ends = np.concatenate([shapely.get_point(pieces, 0), shapely.get_point(pieces, -1)])
    cid = cluster_points(ends, tol)
    u, v = cid[:m], cid[m:]
    km = shapely.length(pieces) * km_per_m[src]
    edges = pd.DataFrame({"u": u, "v": v, "part": src, "km": km})
    self_loops = (edges["u"] == edges["v"]).values
    # keep what is dropped, so it can be audited (section 6)
    loop_geoms = pieces[self_loops]
    loops = edges[self_loops].rename(columns={"u": "node"}).drop(columns="v").reset_index(drop=True)
    loops["length_m_utm"] = shapely.length(loop_geoms)
    loops["end_gap_m"] = shapely.distance(shapely.get_point(loop_geoms, 0), shapely.get_point(loop_geoms, -1))
    edges = edges[~self_loops].reset_index(drop=True)
    pieces = pieces[~self_loops]
    xy = shapely.get_coordinates(ends)
    nodes = (pd.DataFrame({"node": cid, "x": xy[:, 0], "y": xy[:, 1]})
               .groupby("node", as_index=False)[["x", "y"]].mean())
    return nodes, edges, pieces, n_cuts, loops, loop_geoms


def components(edges):
    G = nx.Graph()
    G.add_edges_from(zip(edges["u"], edges["v"]))
    comp_of = {}
    for k, c in enumerate(sorted(nx.connected_components(G), key=len, reverse=True)):
        for n in c:
            comp_of[n] = k
    return comp_of

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Tolerance sensitivity

# COMMAND ----------

# Single denominator for every km share in this notebook: the full network geometry,
# before anything is dropped. Shares over the final graph only would hide the self-loop km.
total_km = geo_km.sum()
sens = []
for tol in TOLERANCES_M:
    nodes, edges, _, n_cuts, loops, _ = build(parts_utm, tol)
    comp_of = components(edges)
    edges["comp"] = edges["u"].map(comp_of)
    km_by_comp = edges.groupby("comp")["km"].sum().sort_values(ascending=False)
    deg = pd.concat([edges["u"], edges["v"]]).value_counts()
    sens.append({
        "tol_m": tol, "t_junction_cuts": n_cuts, "nodes": len(nodes), "edges": len(edges),
        "self_loops_dropped": len(loops), "self_loops_km": float(loops["km"].sum()),
        "network_km": float(total_km), "graph_km": float(edges["km"].sum()),
        "components": len(km_by_comp),
        "largest_comp_km_share": float(km_by_comp.iloc[0] / total_km),
        "dead_ends": int((deg == 1).sum()),
    })
sens_df = pd.DataFrame(sens)
spark.createDataFrame(sens_df).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(T_SENS)
display(sens_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Final graph with `TOL_M`

# COMMAND ----------

nodes, edges, pieces, n_cuts, loops, loop_geoms = build(parts_utm, TOL_M)
comp_of = components(edges)
edges["comp"] = edges["u"].map(comp_of)
nodes["comp"] = nodes["node"].map(comp_of)
deg = pd.concat([edges["u"], edges["v"]]).value_counts()
nodes["degree"] = nodes["node"].map(deg).fillna(0).astype(int)

lon, lat = to_wgs.transform(nodes["x"].values, nodes["y"].values)
nodes["lon"], nodes["lat"] = lon, lat

# attach MTC attributes of the source record
edges["row"] = owner[edges["part"].values]
edges = edges.join(roads, on="row")
edges.insert(0, "edge_id", np.arange(len(edges)))
simpl = shapely.simplify(pieces, 25)                     # 25 m, for maps only
edges["geometry_wkt"] = shapely.to_wkt(reproject(simpl, to_wgs), rounding_precision=6)
edges = edges.drop(columns=["part", "row"]).rename(columns={"km": "length_km", "Id": "tramo_id"})

print(f"TOL_M={TOL_M}: nodes={len(nodes)} edges={len(edges)} cuts={n_cuts} "
      f"components={edges['comp'].nunique()} km={edges['length_km'].sum():,.0f}")

# COMMAND ----------

(spark.createDataFrame(nodes[["node", "lon", "lat", "degree", "comp"]])
    .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(T_NODES))
(spark.createDataFrame(edges)
    .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(T_EDGES))
spark.sql(f"COMMENT ON TABLE {T_EDGES} IS 'Undirected road graph edges (TOL_M={TOL_M} m). length_km geodesic. geometry simplified 25 m.'")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. What stays disconnected, and why

# COMMAND ----------

comps = (edges.groupby("comp")
         .agg(km=("length_km", "sum"), edges=("edge_id", "count"),
              rutas=("cCodRuta", lambda s: ", ".join(sorted(set(s)))),
              departamentos=("cDepartame", lambda s: ", ".join(sorted(set(s)))))
         .reset_index().sort_values("km", ascending=False))
comps["km_share"] = comps["km"] / total_km          # same denominator as section 3
print(f"network_km={total_km:,.1f} graph_km={edges['length_km'].sum():,.1f} "
      f"self_loops={len(loops)} self_loops_km={loops['km'].sum():,.1f}")
spark.createDataFrame(comps).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(T_COMPS)
display(comps.head(25))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Self-loops: what the graph drops
# MAGIC
# MAGIC A piece whose two ends fall in the same node cluster becomes a self-loop and is dropped
# MAGIC (it can never shorten a route). Its km leave the graph, so they are audited here, by cause:
# MAGIC - `corto`: the piece is no longer than `TOL_M` (digitizing noise or a tiny stub).
# MAGIC - `extremos_cercanos`: longer than `TOL_M` but its two ends are within `TOL_M` (a closed ring,
# MAGIC   e.g. a roundabout or a loop road).
# MAGIC - `cadena`: its ends are farther than `TOL_M` apart, yet union-find merged them through a
# MAGIC   chain of intermediate endpoints. This is the case to review: a real road collapsed.

# COMMAND ----------

loops["tipo"] = np.select(
    [loops["length_m_utm"] <= TOL_M, loops["end_gap_m"] <= TOL_M],
    ["corto", "extremos_cercanos"], default="cadena")
loops["row"] = owner[loops["part"].values]
loops = loops.join(roads[["Id", "cCodRuta", "cDepartame", "cSuperfici", "dkmInicio", "dkmFinal"]], on="row")
loops["geometry_wkt"] = shapely.to_wkt(reproject(loop_geoms, to_wgs), rounding_precision=6)
loops = (loops.drop(columns=["part", "row"])
              .rename(columns={"km": "length_km", "Id": "tramo_id"})
              .sort_values("length_km", ascending=False).reset_index(drop=True))
spark.createDataFrame(loops).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(T_LOOPS)

display(loops.groupby("tipo").agg(n=("length_km", "size"), km=("length_km", "sum"),
                                  max_km=("length_km", "max"), max_gap_m=("end_gap_m", "max"))
             .reset_index())
display(loops.drop(columns="geometry_wkt").head(25))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Validation against the official kilometre markers
# MAGIC
# MAGIC For each trunk route, the shortest path *inside that route's own edges* between its first and
# MAGIC last record should match `max(dkmFinal) - min(dkmInicio)` (the official progressive km).
# MAGIC No external distances are used.

# COMMAND ----------

def route_check(code):
    e = edges[edges["cCodRuta"] == code]
    G = nx.Graph()
    for r in e.itertuples():
        if not G.has_edge(r.u, r.v) or G[r.u][r.v]["w"] > r.length_km:
            G.add_edge(r.u, r.v, w=r.length_km)
    first = e.loc[e["dkmInicio"] == e["dkmInicio"].min()]
    last = e.loc[e["dkmFinal"] == e["dkmFinal"].max()]
    starts = set(first["u"]) | set(first["v"])
    stops = set(last["u"]) | set(last["v"])
    best = None
    for s in starts:
        dist = nx.single_source_dijkstra_path_length(G, s, weight="w")
        for t in stops:
            if t in dist and (best is None or dist[t] > best):
                best = dist[t]
    official = e["dkmFinal"].max() - e["dkmInicio"].min()
    return {"ruta": code, "km_oficial": float(official),
            "km_grafo": None if best is None else float(best),
            "dif_pct": None if best is None else float((best - official) / official),
            "subgrafo_conexo": nx.is_connected(G), "componentes_ruta": nx.number_connected_components(G)}

valid = pd.DataFrame([route_check(c) for c in ["PE-1N", "PE-1S", "PE-3N", "PE-3S", "PE-5N", "PE-22"]])
spark.createDataFrame(valid).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(T_VALID)
display(valid)
