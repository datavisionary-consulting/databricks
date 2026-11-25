# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Download and load: national road network + toll units (Peru)
# MAGIC
# MAGIC Lands the two base datasets of this project as bronze Delta tables, unchanged except for
# MAGIC type casting and geometry serialization (WKT). No business logic here.
# MAGIC
# MAGIC | Source (exact portal title) | File | Publisher |
# MAGIC |---|---|---|
# MAGIC | MTC - DATOS ESPACIALES DE LA RED VIAL NACIONAL (2016) | `red_vial_nacional_dic16.zip` (shapefile) | MTC |
# MAGIC | Unidades de Peaje de la Red Vial Nacional 2024 – 2025 | `unidades_peaje_2024-2025.geojson` + data dictionary PDF | MTC |
# MAGIC
# MAGIC Download URLs (from `workspace.pnda_catalog`, built in `pnda-catalog-inventory`):
# MAGIC - https://www.datosabiertos.gob.pe/sites/default/files/red_vial_nacional_dic16.zip
# MAGIC - https://www.datosabiertos.gob.pe/sites/default/files/unidades_peaje_2024-2025.geojson
# MAGIC - https://www.datosabiertos.gob.pe/sites/default/files/Diccionario_Datos_Peaje_2024-2025.pdf
# MAGIC
# MAGIC ## Real quirks found before writing this
# MAGIC
# MAGIC 1. **Scripted downloads of `/sites/default/files/*` were blocked** (HTTP 418, a CloudWAF
# MAGIC    "access blocked" HTML page instead of the file) on 2026-11-21. The three files were
# MAGIC    downloaded from a browser and uploaded to the volume `workspace.rutas_transporte.raw_data`.
# MAGIC    This notebook reads from the volume and checks file sizes, so a silent HTML-instead-of-ZIP
# MAGIC    swap cannot slip through.
# MAGIC 2. **The shapefile ZIP has no data dictionary.** Surface codes (`cSuperfici`: 1, 2, 3, 4, 9, 11)
# MAGIC    are undocumented in the file itself; they are kept as raw codes here and decoded only once a
# MAGIC    real MTC source for them is found.
# MAGIC 3. **The toll GeoJSON stacks 3 snapshots** (`FECCORTE` = 20241230, 20250630, 20251231): 233 rows
# MAGIC    = 78 toll units × 3 (one unit missing in the first cut). It has **no tariffs**.
# MAGIC 4. Encodings: shapefile `.cst` says ISO-8859-1; GeoJSON is UTF-8 with CRS84 (= WGS84 lon/lat).

# COMMAND ----------

# MAGIC %pip install -q pyshp==2.3.1 shapely==2.0.6

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE SCHEMA IF NOT EXISTS workspace.rutas_transporte;
# MAGIC CREATE VOLUME IF NOT EXISTS workspace.rutas_transporte.raw_data;

# COMMAND ----------

import json
import math
import shutil
import hashlib
import zipfile
from pathlib import Path

import pandas as pd
import shapefile  # pyshp
from shapely.geometry import shape as to_shape

VOL = Path("/Volumes/workspace/rutas_transporte/raw_data")
RAW_ZIP = VOL / "red_vial_nacional_dic16.zip"
RAW_TOLLS = VOL / "unidades_peaje_2024-2025.geojson"
RAW_DICT = VOL / "Diccionario_Datos_Peaje_2024-2025.pdf"

# Sizes observed on the files downloaded from the portal on 2026-11-21.
EXPECTED_BYTES = {RAW_ZIP: 35_228_017, RAW_TOLLS: 148_126, RAW_DICT: 99_737}

T_ROADS = "workspace.rutas_transporte.bronze_red_vial_2016"
T_TOLLS = "workspace.rutas_transporte.bronze_peajes_2024_2025"
T_FILES = "workspace.rutas_transporte.bronze_source_files"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Verify the raw files

# COMMAND ----------

def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

rows = []
for p, expected in EXPECTED_BYTES.items():
    size = p.stat().st_size
    with open(p, "rb") as f:
        head = f.read(16)
    assert not head.lstrip().lower().startswith(b"<!doctype"), f"{p.name} is an HTML page, not data"
    assert size == expected, f"{p.name}: {size} bytes, expected {expected}"
    rows.append({"file": p.name, "bytes": size, "sha256": sha256(p)})

files_df = pd.DataFrame(rows)
spark.createDataFrame(files_df).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(T_FILES)
display(files_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Road network 2016 → `bronze_red_vial_2016`

# COMMAND ----------

work = Path("/tmp/rutas_rvn")
shutil.rmtree(work, ignore_errors=True)
work.mkdir(parents=True)
with zipfile.ZipFile(RAW_ZIP) as z:
    print(z.namelist())
    z.extractall(work)

prj = (work / "red_vial_nacional_dic16.prj").read_text()
assert 'AUTHORITY["EPSG","4326"]' in prj, "CRS is not WGS84 / EPSG:4326"
encoding = (work / "red_vial_nacional_dic16.cst").read_text().strip()
print("CRS: EPSG:4326 | encoding:", encoding)

# COMMAND ----------

def haversine_km(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    d = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(d))

def line_km(points, parts):
    bounds = list(parts) + [len(points)]
    return sum(
        haversine_km(points[j], points[j + 1])
        for i in range(len(bounds) - 1)
        for j in range(bounds[i], bounds[i + 1] - 1)
    )

reader = shapefile.Reader(str(work / "red_vial_nacional_dic16.shp"), encoding=encoding.lower())
fields = [f[0] for f in reader.fields[1:]]

records = []
for sr in reader.iterShapeRecords():
    rec = dict(zip(fields, sr.record))
    shp = sr.shape
    rec["n_parts"] = len(shp.parts)
    rec["n_points"] = len(shp.points)
    rec["length_km_geodesic"] = line_km(shp.points, shp.parts)
    rec["geometry_wkt"] = to_shape(shp.__geo_interface__).wkt
    records.append(rec)

roads = pd.DataFrame(records)
for c in ["cSentido", "cRegion", "cTopografi"]:
    roads[c] = roads[c].replace({"": None, " ": None})
print(roads.shape)

# COMMAND ----------

assert len(roads) == 3750, len(roads)
assert roads["Id"].is_unique
assert set(roads["cTipRedDic"]) == {"RN"}

(spark.createDataFrame(roads)
    .write.mode("overwrite").option("overwriteSchema", "true")
    .saveAsTable(T_ROADS))

spark.sql(f"COMMENT ON TABLE {T_ROADS} IS 'MTC national road network (Dec 2016), 1 row per shapefile record, WGS84 WKT. Raw codes, undecoded.'")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Toll units 2024-2025 → `bronze_peajes_2024_2025`

# COMMAND ----------

gj = json.loads(RAW_TOLLS.read_text(encoding="utf-8"))
assert gj["crs"]["properties"]["name"] == "urn:ogc:def:crs:OGC:1.3:CRS84"

tolls = pd.DataFrame([
    {**f["properties"],
     "lon": f["geometry"]["coordinates"][0],
     "lat": f["geometry"]["coordinates"][1]}
    for f in gj["features"]
])
assert len(tolls) == 233, len(tolls)
assert set(tolls["FECCORTE"]) == {"20241230", "20250630", "20251231"}

(spark.createDataFrame(tolls)
    .write.mode("overwrite").option("overwriteSchema", "true")
    .saveAsTable(T_TOLLS))

spark.sql(f"COMMENT ON TABLE {T_TOLLS} IS 'MTC toll units, 3 stacked snapshots (FECCORTE). Points WGS84. No tariffs.'")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Profile what was loaded

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT COUNT(*)                         AS tramos,
# MAGIC        ROUND(SUM(length_km_geodesic))   AS km_geometria,
# MAGIC        ROUND(SUM(dLongitud))            AS km_atributo,
# MAGIC        SUM(n_points)                    AS puntos,
# MAGIC        COUNT(DISTINCT cCodRuta)         AS rutas,
# MAGIC        SUM(CASE WHEN dVelProTra = 0 THEN 1 ELSE 0 END) AS vel_cero,
# MAGIC        SUM(CASE WHEN cTopografi IS NULL THEN 1 ELSE 0 END) AS topografia_nula
# MAGIC FROM workspace.rutas_transporte.bronze_red_vial_2016

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT cSuperfici, cEstadoDic, COUNT(*) AS tramos, ROUND(SUM(dLongitud)) AS km
# MAGIC FROM workspace.rutas_transporte.bronze_red_vial_2016
# MAGIC GROUP BY ALL ORDER BY km DESC

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT FECCORTE, COUNT(*) AS filas, COUNT(DISTINCT CODPEAJE) AS peajes,
# MAGIC        SUM(ES_CONCES) AS concesionados,
# MAGIC        SUM(CASE WHEN ESTADO <> 'Operativo' THEN 1 ELSE 0 END) AS no_operativos
# MAGIC FROM workspace.rutas_transporte.bronze_peajes_2024_2025
# MAGIC GROUP BY FECCORTE ORDER BY FECCORTE
