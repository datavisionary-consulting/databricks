"""Ejecuta SQL en Databricks Free Edition (perfil CLI `free`) y devuelve filas.

Uso: python dbsql.py "SELECT ..."   |   from dbsql import run; run(sql)
Nunca usa otro perfil: el proyecto es personal (ver README).
"""
import json, os, subprocess, sys, time

PROFILE = "free"
WAREHOUSE = "05dc603b71d87c91"  # Serverless Starter Warehouse
ENV = dict(os.environ, MSYS_NO_PATHCONV="1")


def _api(method, path, body=None):
    cmd = ["databricks", "api", method, path, "--profile", PROFILE]
    if body is not None:
        cmd += ["--json", json.dumps(body)]
    out = subprocess.run(cmd, capture_output=True, text=True, env=ENV, encoding="utf-8")
    if out.returncode:
        raise RuntimeError(out.stderr or out.stdout)
    return json.loads(out.stdout)


def run(sql, timeout_s=1800):
    r = _api("post", "/api/2.0/sql/statements",
             {"warehouse_id": WAREHOUSE, "statement": sql, "wait_timeout": "50s",
              "disposition": "INLINE", "format": "JSON_ARRAY"})
    t0 = time.time()
    while r["status"]["state"] in ("PENDING", "RUNNING"):
        if time.time() - t0 > timeout_s:
            raise TimeoutError(r["statement_id"])
        time.sleep(5)
        r = _api("get", f"/api/2.0/sql/statements/{r['statement_id']}")
    if r["status"]["state"] != "SUCCEEDED":
        raise RuntimeError(r["status"])
    cols = [c["name"] for c in r.get("manifest", {}).get("schema", {}).get("columns", [])]
    rows = r.get("result", {}).get("data_array", []) or []
    chunks = r.get("manifest", {}).get("total_chunk_count", 1)
    for i in range(1, chunks):
        c = _api("get", f"/api/2.0/sql/statements/{r['statement_id']}/result/chunks/{i}")
        rows += c.get("data_array", [])
    return cols, rows, round(time.time() - t0, 1)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cols, rows, secs = run(sys.argv[1])
    print(cols); [print(r) for r in rows]; print(f"{len(rows)} filas, {secs} s")
