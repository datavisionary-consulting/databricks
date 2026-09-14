# Databricks notebook source
# MAGIC %md
# MAGIC # PNDA Catalog Inventory — Peru's National Open Data Platform
# MAGIC
# MAGIC Inventory and exploration layer for https://www.datosabiertos.gob.pe (DKAN, not CKAN,
# MAGIC despite the CKAN-compatible API paths). Downloads **metadata only** for the full
# MAGIC catalog (~4,714 datasets as of this writing), lands it as a Delta table, and produces
# MAGIC an exploratory report to decide which datasets are worth pursuing later. No
# MAGIC dataset-specific business logic here on purpose.
# MAGIC
# MAGIC ## Two real API quirks this notebook works around
# MAGIC
# MAGIC Verified directly against the live API before writing this:
# MAGIC
# MAGIC 1. **`package_show` returns `result` as a list containing one dataset, not a bare
# MAGIC    object** (`{"result": [{...}]}`, not `{"result": {...}}`) — a DKAN-vs-CKAN
# MAGIC    difference. Every call below does `result[0]`.
# MAGIC 2. **There is no `organization` field.** The publishing entity lives at
# MAGIC    `groups[0]['title']` instead, with `maintainer` as a fallback when `groups` is
# MAGIC    empty. Assuming a CKAN-standard `organization.title` here would silently produce
# MAGIC    an empty "entidad" column for every row.
# MAGIC
# MAGIC `/api/3/action/package_search` is a 404 on this portal — DKAN doesn't implement it the
# MAGIC way CKAN does. Only `package_list` and `package_show` are used here.
# MAGIC
# MAGIC A third thing showed up on the first real run, not in isolated single-request tests:
# MAGIC a sustained pass at 10 concurrent workers over ~4,714 calls outlasts whatever
# MAGIC rate-limiting this small government portal applies, and a batch of otherwise-normal
# MAGIC slugs (`teatros`, `infracciones`, plain ASCII, nothing exotic) starts failing after
# MAGIC several minutes even though each one works fine in isolation. Nothing is lost --
# MAGIC failures are checkpointed to `failed_slugs.jsonl`, not dropped -- and a second,
# MAGIC deliberately gentler pass (3 workers, longer backoff, more attempts, a cooldown pause
# MAGIC first) retries just those slugs after the main run.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Setup

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE SCHEMA IF NOT EXISTS workspace.pnda_catalog;
# MAGIC CREATE VOLUME IF NOT EXISTS workspace.pnda_catalog.checkpoints;

# COMMAND ----------

import json
import time
import random
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("pnda")

BASE_URL = "https://www.datosabiertos.gob.pe/api/3/action"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; pnda-catalog-inventory/1.0)"}

MAX_WORKERS = 10
MAX_RETRIES = 3
REQUEST_TIMEOUT = 20          # seconds
REQUEST_DELAY = 0.05          # small pause per request, on top of the thread pool's natural pacing
CHECKPOINT_EVERY = 200        # records

CHECKPOINT_PATH = Path("/Volumes/workspace/pnda_catalog/checkpoints/metadata_checkpoint.jsonl")
FAILED_PATH = Path("/Volumes/workspace/pnda_catalog/checkpoints/failed_slugs.jsonl")

# COMMAND ----------

# MAGIC %md
# MAGIC ## `fetch_catalog()` — the full list of dataset slugs

# COMMAND ----------

def fetch_catalog() -> list[str]:
    """Calls package_list once and returns every dataset slug in the portal."""
    resp = requests.get(f"{BASE_URL}/package_list", headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("success"):
        raise RuntimeError(f"package_list did not return success=true: {payload}")
    slugs = payload["result"]
    log.info(f"fetch_catalog: {len(slugs):,} dataset slugs")
    return slugs

# COMMAND ----------

# MAGIC %md
# MAGIC ## `enrich_metadata()` — package_show for every slug, in parallel, checkpointed
# MAGIC
# MAGIC Runs up to `MAX_WORKERS` requests concurrently, retries each failed request up to
# MAGIC `MAX_RETRIES` times with exponential backoff + jitter, and appends completed records
# MAGIC to a checkpoint file on disk every `CHECKPOINT_EVERY` records — so a crash partway
# MAGIC through the ~4,714 calls loses at most one checkpoint interval of work, not the whole
# MAGIC run. Slugs already present in the checkpoint file are skipped on a re-run.

# COMMAND ----------

def _load_already_done(checkpoint_path: Path) -> dict[str, dict]:
    """Reads whatever checkpoint already exists, keyed by slug, so re-runs can resume."""
    done = {}
    if checkpoint_path.exists():
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    done[rec["slug"]] = rec
                except json.JSONDecodeError:
                    continue
    return done


def _fetch_one(slug: str, max_retries: int = MAX_RETRIES, request_delay: float = REQUEST_DELAY,
                backoff_base: float = 2.0, backoff_cap: float = 30.0) -> dict:
    """package_show for a single slug, with retries + exponential backoff. Raises on
    final failure so the caller can log it to the failed-slugs file instead of silently
    dropping it. Backoff/delay/retry count are parameters (not just module constants) so
    a gentler second pass over just the failed slugs can use different settings without
    duplicating this function."""
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            time.sleep(request_delay)
            resp = requests.get(
                f"{BASE_URL}/package_show",
                params={"id": slug},
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            payload = resp.json()
            if not payload.get("success"):
                raise RuntimeError(f"success=false for slug={slug}: {payload}")

            result = payload["result"]
            # DKAN quirk: result is a list containing one dataset, not a bare object.
            if isinstance(result, list):
                if not result:
                    raise RuntimeError(f"empty result list for slug={slug}")
                dataset = result[0]
            else:
                dataset = result

            resources = dataset.get("resources") or []
            groups = dataset.get("groups") or []
            entidad = groups[0]["title"] if groups else (dataset.get("maintainer") or "Sin entidad")

            return {
                "slug": slug,
                "titulo": dataset.get("title"),
                "descripcion": dataset.get("notes"),
                "entidad": entidad,
                "n_recursos": len(resources),
                "formatos": sorted({(r.get("format") or "").upper() for r in resources if r.get("format")}),
                "urls": [r.get("url") for r in resources if r.get("url")],
                "metadata_created": dataset.get("metadata_created"),
                "metadata_modified": dataset.get("metadata_modified"),
                "private": dataset.get("private"),
            }
        except Exception as exc:  # noqa: BLE001 -- deliberately broad: any failure should retry, not crash the pipeline
            last_exc = exc
            if attempt < max_retries:
                backoff = min(backoff_cap, (backoff_base ** (attempt - 1))) + random.uniform(0, 0.5)
                time.sleep(backoff)
    raise RuntimeError(f"failed after {max_retries} attempts: {slug}") from last_exc


def enrich_metadata(slugs: list[str], max_workers: int = MAX_WORKERS, max_retries: int = MAX_RETRIES,
                     request_delay: float = REQUEST_DELAY, backoff_base: float = 2.0,
                     backoff_cap: float = 30.0) -> list[dict]:
    """Fetches package_show for every slug not already checkpointed, writing results
    (and failures) to disk incrementally. Returns the full combined result set,
    checkpointed records included. Concurrency/retry/backoff are parameters so a gentler
    second pass over just the failed slugs (see retry_failed_slugs below) can turn the
    load down without a second copy of this function."""
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)

    already_done = _load_already_done(CHECKPOINT_PATH)
    pending = [s for s in slugs if s not in already_done]
    log.info(f"enrich_metadata: {len(already_done):,} already checkpointed, {len(pending):,} to fetch "
             f"(max_workers={max_workers}, max_retries={max_retries})")

    checkpoint_file = open(CHECKPOINT_PATH, "a", encoding="utf-8")
    failed_file = open(FAILED_PATH, "a", encoding="utf-8")
    processed_since_flush = 0
    total_done = len(already_done)
    newly_failed = []

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_fetch_one, slug, max_retries, request_delay, backoff_base, backoff_cap): slug
                for slug in pending
            }
            for future in as_completed(futures):
                slug = futures[future]
                try:
                    record = future.result()
                    checkpoint_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                    already_done[slug] = record
                except Exception as exc:  # noqa: BLE001
                    log.warning(f"giving up on slug={slug}: {exc}")
                    failed_file.write(json.dumps({"slug": slug, "error": str(exc)}, ensure_ascii=False) + "\n")
                    newly_failed.append(slug)

                total_done += 1
                processed_since_flush += 1
                if processed_since_flush >= CHECKPOINT_EVERY:
                    checkpoint_file.flush()
                    failed_file.flush()
                    processed_since_flush = 0
                    log.info(f"{total_done:,}/{len(slugs):,} processed")
    finally:
        checkpoint_file.close()
        failed_file.close()

    log.info(f"enrich_metadata: done. {len(already_done):,} succeeded, {len(newly_failed):,} newly failed "
             f"this pass, see {FAILED_PATH} for the full failure log.")
    return list(already_done.values())

# COMMAND ----------

# MAGIC %md
# MAGIC ## Run it
# MAGIC
# MAGIC Safe to re-run: anything already in the checkpoint file is skipped, so an interrupted
# MAGIC run just picks up where it left off instead of starting over.

# COMMAND ----------

slugs = fetch_catalog()
records = enrich_metadata(slugs)
print(f"Final: {len(records):,} datasets with metadata, out of {len(slugs):,} in the catalog")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Retry the ones that failed, gently
# MAGIC
# MAGIC A first pass at 10 concurrent workers over ~4,714 calls can outlast whatever
# MAGIC rate-limiting this small government portal applies under sustained load — slugs that
# MAGIC fail here aren't necessarily broken, they may have just been rejected while the server
# MAGIC was busy. This second pass reads `failed_slugs.jsonl`, waits for the earlier burst to
# MAGIC clear, and retries only those slugs with much lower concurrency, longer backoff, and
# MAGIC more attempts. Safe to run more than once: each pass's remaining failures overwrite
# MAGIC the failed-slugs file, and anything that now succeeds is checkpointed normally.

# COMMAND ----------

def retry_failed_slugs(cooldown_seconds: int = 30) -> list[dict]:
    """Reads whatever is currently in FAILED_PATH and retries just those slugs with a
    gentler configuration (3 workers instead of 10, longer backoff, more attempts).
    Returns the newly-recovered records; anything still failing after this pass stays
    logged in FAILED_PATH for a human to look at."""
    if not FAILED_PATH.exists():
        log.info("retry_failed_slugs: no failed_slugs.jsonl yet, nothing to retry")
        return []

    with open(FAILED_PATH, "r", encoding="utf-8") as f:
        failed_slugs = sorted({json.loads(line)["slug"] for line in f if line.strip()})

    if not failed_slugs:
        log.info("retry_failed_slugs: failure log is empty")
        return []

    log.info(f"retry_failed_slugs: {len(failed_slugs):,} slugs to retry, "
             f"waiting {cooldown_seconds}s first so the server can recover from the first pass")
    time.sleep(cooldown_seconds)

    # Start this pass's failure log fresh -- whatever still fails after the gentle retry
    # is what actually needs a human look, not a mix of two passes' worth of noise.
    FAILED_PATH.unlink(missing_ok=True)

    recovered = enrich_metadata(
        failed_slugs,
        max_workers=3,
        max_retries=5,
        request_delay=0.3,
        backoff_base=3.0,
        backoff_cap=60.0,
    )
    log.info(f"retry_failed_slugs: recovered {len(recovered):,} of {len(failed_slugs):,}")
    return recovered


retried = retry_failed_slugs()
if FAILED_PATH.exists():
    with open(FAILED_PATH, "r", encoding="utf-8") as f:
        still_failing = sum(1 for line in f if line.strip())
    print(f"{still_failing} slugs still failing after the gentle retry -- see {FAILED_PATH}")
else:
    print("No slugs failing after the gentle retry.")

# Reload everything from the checkpoint file so `records` reflects the retry pass too.
records = list(_load_already_done(CHECKPOINT_PATH).values())
print(f"Final: {len(records):,} datasets with metadata, out of {len(slugs):,} in the catalog")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Land `bronze.pnda_catalogo`

# COMMAND ----------

from pyspark.sql.types import StructType, StructField, StringType, IntegerType, ArrayType, BooleanType

schema = StructType([
    StructField("slug", StringType()),
    StructField("titulo", StringType()),
    StructField("descripcion", StringType()),
    StructField("entidad", StringType()),
    StructField("n_recursos", IntegerType()),
    StructField("formatos", ArrayType(StringType())),
    StructField("urls", ArrayType(StringType())),
    StructField("metadata_created", StringType()),
    StructField("metadata_modified", StringType()),
    StructField("private", BooleanType()),
])

catalog_df = spark.createDataFrame(records, schema=schema)
catalog_df.write.format("delta").mode("overwrite").saveAsTable("workspace.pnda_catalog.bronze_pnda_catalogo")
print(f"Saved workspace.pnda_catalog.bronze_pnda_catalogo -- {catalog_df.count():,} rows")
display(catalog_df.limit(10))

# COMMAND ----------

# MAGIC %md
# MAGIC ## `sample_resource()` — peek at a dataset's main resource without downloading it fully
# MAGIC
# MAGIC `pandas.read_csv(url, nrows=N)` genuinely streams only the first N rows over HTTP for
# MAGIC CSV. Excel has no equivalent partial-read for a remote URL — `pandas.read_excel`
# MAGIC always parses the whole workbook — so for XLSX this does a `HEAD` request first and
# MAGIC skips anything above `MAX_XLSX_BYTES` rather than silently downloading an
# MAGIC arbitrarily large file, then truncates to N rows after loading.

# COMMAND ----------

import pandas as pd

TABULAR_FORMATS = {"CSV", "XLSX", "XLS"}
MAX_XLSX_BYTES = 25_000_000  # 25MB safety cap for the "full download" XLSX path


def sample_resource(url: str, formato: str, nrows: int = 200) -> pd.DataFrame | None:
    """Returns up to `nrows` rows of a CSV/XLSX resource, or None (with a logged reason)
    for anything else -- never raises, so one bad resource never stops a batch of samples."""
    formato = (formato or "").upper()
    if formato not in TABULAR_FORMATS:
        log.info(f"sample_resource: skipping non-tabular format '{formato}' for {url}")
        return None

    try:
        if formato == "CSV":
            return pd.read_csv(url, nrows=nrows, on_bad_lines="skip")

        # XLSX / XLS: check size before pulling the whole file
        try:
            head = requests.head(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            size = int(head.headers.get("Content-Length", 0))
        except Exception:  # noqa: BLE001 -- HEAD support varies; fall through and try anyway
            size = 0
        if size and size > MAX_XLSX_BYTES:
            log.info(f"sample_resource: skipping {url}, {size:,} bytes exceeds {MAX_XLSX_BYTES:,} cap")
            return None
        return pd.read_excel(url).head(nrows)

    except Exception as exc:  # noqa: BLE001
        log.warning(f"sample_resource: failed for {url} ({formato}): {exc}")
        return None

# COMMAND ----------

# MAGIC %md
# MAGIC ### Try it on a few real datasets

# COMMAND ----------

sample_candidates = (
    catalog_df.filter(catalog_df.n_recursos > 0)
    .filter(catalog_df.formatos.isNotNull())
    .limit(5)
    .collect()
)

for row in sample_candidates:
    if not row.urls or not row.formatos:
        continue
    url, formato = row.urls[0], row.formatos[0]
    print(f"\n=== {row.titulo} ({formato}) ===")
    df = sample_resource(url, formato)
    if df is not None:
        print(df.shape)
        print(df.head(3))
    else:
        print("(not sampled -- see log above)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## `build_report()` — what's actually in the catalog

# COMMAND ----------

from pyspark.sql import functions as F


def build_report(df):
    print("=== Datasets by entity (top 20) ===")
    by_entity = (
        df.groupBy("entidad")
        .agg(F.count("*").alias("n_datasets"))
        .orderBy(F.desc("n_datasets"))
    )
    display(by_entity.limit(20))

    print("=== Datasets by format ===")
    by_format = (
        df.withColumn("formato", F.explode_outer("formatos"))
        .groupBy("formato")
        .agg(F.count("*").alias("n_datasets"))
        .orderBy(F.desc("n_datasets"))
    )
    display(by_format)

    print("=== Datasets with zero resources (metadata-only, nothing to sample) ===")
    zero_resource = df.filter(F.col("n_recursos") == 0).count()
    print(f"{zero_resource:,} of {df.count():,} datasets have no downloadable resource")

    return by_entity, by_format


by_entity, by_format = build_report(catalog_df)
