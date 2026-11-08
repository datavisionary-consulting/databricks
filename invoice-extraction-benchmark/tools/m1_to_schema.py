"""Convierte las predicciones de M1 (LayoutLMv3, publicadas por DocILE para val)
al esquema de producción, para evaluarlas con eval_valores.py igual que M2.

Cabecera: por cada campo, la predicción de mayor confianza del tipo DocILE
equivalente. Líneas: se agrupan por line_item_id; en cada línea, el valor de mayor
confianza por tipo; la descripción une sus fragmentos en orden de lectura.
Solo se usan predicciones con use_only_for_ap = False (las que cuentan para F1).

Uso: python m1_to_schema.py <predicciones_dir> <salida.json>
"""
import json
import sys
from pathlib import Path

from docile.dataset import load_predictions

HEAD = {"invoice": ["document_id"], "invoice_date": ["date_issue"], "due_date": ["date_due"],
        "vendor_name": ["vendor_name"], "moneda": ["currency_code_amount_due"],
        "total_factura_pdf": ["amount_total_gross", "amount_due"]}
LI = {"item": ["line_item_code"], "cantidad": ["line_item_quantity"],
      "costo_unitario": ["line_item_unit_price_gross", "line_item_unit_price_net"],
      "importe": ["line_item_amount_gross", "line_item_amount_net"]}


def best(fields):
    return max(fields, key=lambda f: f.score or 0.0) if fields else None


def main(pred_dir, out):
    P = Path(pred_dir)
    kile = load_predictions(P / "val_predictions_KILE.json")
    lir = load_predictions(P / "val_predictions_LIR.json")
    res = {}
    for d in kile:
        ks = [f for f in kile[d] if not f.use_only_for_ap]
        resp = {}
        for k, src in HEAD.items():
            b = None
            for s in src:
                b = best([f for f in ks if f.fieldtype == s])
                if b:
                    break
            resp[k] = {"value": b.text if b else None, "confidence_score": b.score if b else None}
        items = {}
        for f in lir.get(d, []):
            if not f.use_only_for_ap and f.line_item_id is not None:
                items.setdefault(f.line_item_id, []).append(f)
        lines = []
        for _, fs in sorted(items.items(), key=lambda kv: min((f.page, f.bbox.top) for f in kv[1])):
            li = {}
            for k, ts in LI.items():
                b = None
                for t in ts:
                    b = best([f for f in fs if f.fieldtype == t])
                    if b:
                        break
                li[k] = {"value": b.text if b else None, "confidence_score": b.score if b else None}
            desc = sorted([f for f in fs if f.fieldtype == "line_item_description"], key=lambda f: (f.page, f.bbox.top, f.bbox.left))
            li["descripcion"] = {"value": " ".join(f.text for f in desc) if desc else None}
            lines.append(li)
        resp["line_items"] = lines
        res[d] = {"response": resp}
    Path(out).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print(f"{len(res)} documentos convertidos -> {out}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(*sys.argv[1:3])
