# PNDA Catalog Inventory

**Status: inventory/exploration layer, not a finished case study.** No dataset-specific business logic here on purpose — this notebook exists to decide which datasets in Peru's National Open Data Platform are worth pursuing next, not to analyze any of them yet.

## What this is

An inventory of every dataset published on [datosabiertos.gob.pe](https://www.datosabiertos.gob.pe) (Peru's national open data portal, ~4,714 datasets), built in Databricks: metadata for the full catalog, a lightweight way to peek at any dataset's actual data without downloading it in full, and a report grouping the catalog by publishing entity and file format.

## Two real API quirks

Verified directly against the live API, not assumed from CKAN documentation:

1. **The portal runs DKAN, not CKAN**, despite exposing CKAN-style API paths. `/api/3/action/package_search` returns a 404 here — only `package_list` and `package_show` work.
2. **`package_show` returns `result` as a list containing one dataset**, not a bare object (`{"result": [{...}]}`). Treating it like standard CKAN's `{"result": {...}}` silently breaks on every call.
3. **There is no `organization` field.** The publishing entity lives at `groups[0]['title']`, with `maintainer` as a fallback when a dataset has no group.

A fourth thing showed up on the first real run rather than in isolated tests: a sustained pass at 10 concurrent workers over ~4,714 calls outlasts whatever rate-limiting the portal applies, and a batch of otherwise-normal slugs (plain ASCII, nothing exotic) starts failing after several minutes even though each one works fine on its own. Nothing is lost — failures are checkpointed, not dropped — see the retry step below.

## Method

1. `fetch_catalog()` — one call to `package_list`, returns every dataset slug (~4,714).
2. `enrich_metadata()` — `package_show` for every slug, up to 10 concurrent requests, 3 retries with exponential backoff per slug, checkpointed to a `.jsonl` file every 200 records so an interrupted run resumes instead of restarting. Failed slugs (after retries) are logged to `failed_slugs.jsonl`, not silently dropped.
3. `retry_failed_slugs()` — after the main pass, reads `failed_slugs.jsonl`, pauses briefly for the server to recover, and retries just those slugs with a deliberately gentler configuration (3 workers instead of 10, longer backoff, 5 attempts instead of 3). Safe to re-run.
4. Metadata lands as `workspace.pnda_catalog.bronze_pnda_catalogo` (slug, titulo, descripcion, entidad, n_recursos, formatos, urls, plus timestamps and the `private` flag).
5. `sample_resource()` — reads the first 200 rows of a CSV resource via a genuine partial HTTP read (`pandas.read_csv(url, nrows=...)`). XLSX has no partial-read equivalent for a remote URL, so it's size-capped (25MB) via a `HEAD` request first, then truncated to 200 rows after loading. Anything else (PDF, nested JSON, etc.) is logged and skipped, never raises.
6. `build_report()` — datasets by entity (top 20), datasets by format, and how many datasets have zero downloadable resources at all.

## Files

- `Notebook/01_catalog_inventory.py` — the full pipeline, in run order.

## Next step

Use `bronze_pnda_catalogo` and the entity/format report to pick specific datasets worth a real case study. This repo's other projects follow the standard in [`../research/README.md`](https://github.com/datavisionary-consulting/datavisionary-consulting.github.io/blob/main/research/README.md) once that point is reached: real findings, real sources, no invented numbers.
