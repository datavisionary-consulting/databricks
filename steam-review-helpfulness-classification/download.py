"""
Databricks notebook cell (Python) -- NOT meant to be run on a laptop.

Downloads the real "Steam Review Dataset (2017)" by Antoni Sobkowicz
(National Information Processing Institute), published on Zenodo:
DOI 10.5281/zenodo.1000885 -- 6.4 million English-language Steam reviews,
CC BY-NC 4.0. Columns (no header row in the source file):
    game_id, review_text, recommended (0/1), helpful_votes

Run this as the first cell of the Databricks notebook. It downloads
directly into DBFS -- the ~506 MB compressed file (and the ~6.4M-row
decompressed CSV) never touch a local machine, and are never committed to
this git repo (see .gitignore). Only code + small derived artifacts
(figures, results.json, a tiny sample CSV for the README) live in git.
"""

# Databricks: %sh cell
DBFS_PATH = "/dbfs/FileStore/steam_reviews/steam.csv.bz2"
URL = "https://zenodo.org/records/1000885/files/steam.csv.bz2?download=1"

# %sh
# mkdir -p /dbfs/FileStore/steam_reviews
# wget -O {DBFS_PATH} "{URL}"
# bunzip2 -k {DBFS_PATH}

# Then, in a Python cell, load it as a Spark DataFrame with an explicit
# schema (the source file has no header row):
from pyspark.sql.types import StructType, StructField, StringType, IntegerType

schema = StructType([
    StructField("game_id", StringType(), True),
    StructField("review_text", StringType(), True),
    StructField("recommended", IntegerType(), True),
    StructField("helpful_votes", IntegerType(), True),
])

df = (
    spark.read
    .option("multiLine", True)
    .option("escape", '"')
    .schema(schema)
    .csv("dbfs:/FileStore/steam_reviews/steam.csv")
)

print(f"Rows: {df.count():,}")
df.limit(5).show(truncate=80)

# Persist as a governed Delta table for the rest of the pipeline.
df.write.format("delta").mode("overwrite").saveAsTable("steam_reviews_raw")
