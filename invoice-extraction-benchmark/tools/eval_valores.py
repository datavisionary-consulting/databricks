"""Evaluación por VALOR (métrica principal de la tesis) para el esquema de producción.

Cabecera: el valor extraído es correcto si, normalizado, coincide con alguna
anotación del campo equivalente de DocILE.
Líneas: emparejamiento óptimo (húngaro) entre líneas extraídas y anotadas; luego
cantidad exacta, costo unitario |Δ| < 0.01, importe |Δ| < 0.50 (tolerancias del E1).
Alertas (validación matemática del revisor): línea con |cant × costo − importe| > 1
o |Σ importes − total| > 1. Se compara la alerta con el error real de la factura.

Uso: python eval_valores.py <dataset_path> <extracted.json> <docids.json> [salida.json]
"""
import json
import re
import sys
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from scipy.optimize import linear_sum_assignment

TOL = {"cantidad": 1e-6, "costo_unitario": 0.01, "importe": 0.50}
# precio e importe: bruto y, si no está anotado, neto (el esquema no distingue)
LI_MAP = {"cantidad": ["line_item_quantity"],
          "costo_unitario": ["line_item_unit_price_gross", "line_item_unit_price_net"],
          "importe": ["line_item_amount_gross", "line_item_amount_net"],
          "descripcion": ["line_item_description"]}
CUR = {"$": "usd", "us$": "usd", "usd": "usd", "€": "eur", "eur": "eur", "£": "gbp", "gbp": "gbp", "cad": "cad"}


def alnum(s):
    return re.sub(r"[^0-9a-z]", "", str(s).lower())


def num(s):
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    t = str(s).strip()
    neg = t.startswith("(") and t.endswith(")") or t.startswith("-") or t.endswith("-")
    t = re.sub(r"[^0-9.,]", "", t)
    if not t:
        return None
    if "," in t and "." in t:
        t = t.replace(",", "") if t.rfind(".") > t.rfind(",") else t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", "") if re.search(r",\d{3}$", t) else t.replace(",", ".")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


DATE_FMTS = ["%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y", "%Y-%m-%d", "%d/%m/%Y", "%B %d, %Y",
             "%b %d, %Y", "%b %d %Y", "%d-%b-%y", "%d-%b-%Y", "%m.%d.%Y", "%m.%d.%y", "%d %b %Y", "%d %B %Y"]


def date(s):
    t = " ".join(str(s).replace(",", ", ").split()).replace(" ,", ",")
    for f in DATE_FMTS:
        try:
            return datetime.strptime(t, f).date()
        except ValueError:
            pass
    return None


def same(kind, pred, refs):
    if pred in (None, "") or not refs:
        return False
    if kind == "date":
        p = date(pred)
        return any((p is not None and p == date(r)) or alnum(pred) == alnum(r) for r in refs)
    if kind == "num":
        p = num(pred)
        return p is not None and any(num(r) is not None and abs(p - num(r)) < 0.50 for r in refs)
    if kind == "cur":
        return CUR.get(str(pred).strip().lower(), alnum(pred)) in {CUR.get(str(r).strip().lower(), alnum(r)) for r in refs}
    return any(alnum(pred) == alnum(r) for r in refs)


HEADER = {  # campo del esquema: (tipo, campos DocILE aceptados)
    "invoice": ("txt", ["document_id"]),
    "invoice_date": ("date", ["date_issue"]),
    "due_date": ("date", ["date_due"]),
    "vendor_name": ("txt", ["vendor_name"]),
    "moneda": ("cur", ["currency_code_amount_due"]),
    "total_factura_pdf": ("num", ["amount_total_gross", "amount_due"]),
}


def val(v):
    return v.get("value") if isinstance(v, dict) else v


def evaluate(ann, resp):
    by = {}
    for f in ann["field_extractions"]:
        by.setdefault(f["fieldtype"], []).append(f["text"])
    head = {}
    for k, (kind, src) in HEADER.items():
        refs = [t for s in src for t in by.get(s, [])]
        p = val(resp.get(k))
        head[k] = {"ref": bool(refs), "pred": p not in (None, ""), "ok": same(kind, p, refs)}
    # líneas anotadas
    gl = {}
    for f in ann["line_item_extractions"]:
        gl.setdefault(f["line_item_id"], {}).setdefault(f["fieldtype"], f["text"])
    def pick(r, srcs):
        return next((r[x] for x in srcs if r.get(x) not in (None, "")), None)
    g = [{k: (num(pick(r, v)) if k != "descripcion" else pick(r, v)) for k, v in LI_MAP.items()} for _, r in sorted(gl.items())]
    p = [{k: (num(val(li.get(k))) if k != "descripcion" else val(li.get(k))) for k in LI_MAP} for li in (resp.get("line_items") or [])]

    def score(a, b):
        s = 0.0
        for k in ("importe", "cantidad", "costo_unitario"):
            if a[k] is not None and b[k] is not None and abs(a[k] - b[k]) < TOL[k] + 1e-9:
                s += 2 if k == "importe" else 1
        if a["descripcion"] and b["descripcion"]:
            s += SequenceMatcher(None, alnum(a["descripcion"]), alnum(b["descripcion"])).ratio()
        return s

    pairs = []
    if g and p:
        cost = [[-score(a, b) for b in p] for a in g]
        rows, cols = linear_sum_assignment(cost)
        pairs = [(r, c) for r, c in zip(rows, cols) if -cost[r][c] >= 1.0]
    lines = []
    for r, c in pairs:
        a, b = g[r], p[c]
        res = {k: (abs(a[k] - b[k]) < TOL[k] + 1e-9) if (a[k] is not None and b[k] is not None) else (None if a[k] is None else False)
               for k in ("cantidad", "costo_unitario", "importe")}
        res["completa"] = all(v for v in res.values() if v is not None)
        lines.append(res)
    # alertas de validación matemática (sobre lo extraído)
    alert = False
    for li in p:
        if li["cantidad"] and li["costo_unitario"] and li["importe"] is not None:
            if abs(li["cantidad"] * li["costo_unitario"] - li["importe"]) > 1.0:
                alert = True
    tot = num(val(resp.get("total_factura_pdf")))
    s = sum(li["importe"] for li in p if li["importe"] is not None)
    if tot is not None and p and abs(s - tot) > 1.0:
        alert = True
    error = (len(pairs) < len(g)) or (len(p) > len(pairs)) or any(not l["completa"] for l in lines) \
        or any(h["ref"] and not h["ok"] for h in head.values())
    return {"head": head, "n_ref_lines": len(g), "n_pred_lines": len(p), "lines": lines, "alerta": alert, "error": error}


def main(dataset_path, extracted_path, docids_path, out=None):
    A = Path(dataset_path) / "annotations"
    ext = json.loads(Path(extracted_path).read_text(encoding="utf-8"))
    ids = [d["docid"] if isinstance(d, dict) else d for d in json.loads(Path(docids_path).read_text(encoding="utf-8"))]
    R = {d: evaluate(json.loads((A / f"{d}.json").read_text(encoding="utf-8")), ext[d]["response"]) for d in ids}
    print("CABECERA (docs con el campo anotado)")
    for k in HEADER:
        n = sum(r["head"][k]["ref"] for r in R.values()); ok = sum(r["head"][k]["ok"] for r in R.values())
        fp = sum(r["head"][k]["pred"] and not r["head"][k]["ref"] for r in R.values())
        print(f"  {k:18} {ok:3}/{n:<3} = {ok / n if n else 0:5.1%}   extraído sin anotación: {fp}")
    nr = sum(r["n_ref_lines"] for r in R.values()); npd = sum(r["n_pred_lines"] for r in R.values())
    L = [l for r in R.values() for l in r["lines"]]
    print(f"LÍNEAS  anotadas {nr} | extraídas {npd} | emparejadas {len(L)} "
          f"(exhaustividad {len(L) / nr if nr else 0:.1%}, precisión {len(L) / npd if npd else 0:.1%})")
    for k in ("cantidad", "costo_unitario", "importe", "completa"):
        v = [l[k] for l in L if l[k] is not None]
        print(f"  {k:15} {sum(v):4}/{len(v):<4} = {sum(v) / len(v) if v else 0:5.1%}")
    tp = sum(r["alerta"] and r["error"] for r in R.values()); fn = sum((not r["alerta"]) and r["error"] for r in R.values())
    fp = sum(r["alerta"] and not r["error"] for r in R.values()); tn = sum(not r["alerta"] and not r["error"] for r in R.values())
    print(f"ALERTAS (validación matemática)  facturas con error: {tp + fn}/{len(R)} | detectadas por alerta: {tp} | "
          f"no detectadas: {fn} | falsas alarmas: {fp} | correctas sin alerta: {tn}")
    if out:
        Path(out).write_text(json.dumps(R, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(*sys.argv[1:5])
