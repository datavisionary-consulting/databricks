"""Control de validez del script de ubicación: aplica localize_and_eval.to_fields a
los valores CORRECTOS de la anotación (oráculo). El F1 resultante es el techo que
impone la ubicación por OCR; la diferencia con 1 es error del procedimiento, no del
modelo.  Uso: python control_oraculo.py <dataset_path> <docids.json> <salida_dir>
"""
import json, sys
from pathlib import Path
from docile.dataset import CachingConfig, Dataset
from docile.evaluation import evaluate_dataset
from localize_and_eval import to_fields

def main(dataset_path, docids_path, out_dir):
    docids = [d["docid"] if isinstance(d, dict) else d for d in json.loads(Path(docids_path).read_text(encoding="utf-8"))]
    full = Dataset("val", dataset_path, cache_images=CachingConfig.OFF)
    ds = Dataset.from_documents("subset", [full[d] for d in docids])
    kile, lir = {}, {}
    for doc in ds:
        a = doc.annotation
        resp = {}
        for f in a.fields:
            resp.setdefault(f.fieldtype, {"value": f.text, "confidence_score": 1.0})
        items = {}
        for f in a.li_fields:
            items.setdefault(f.line_item_id, {}).setdefault(f.fieldtype, {"value": f.text, "confidence_score": 1.0})
        resp["line_items"] = [items[k] for k in sorted(items)]
        kile[doc.docid], lir[doc.docid], _ = to_fields(doc, resp)
    res = evaluate_dataset(ds, kile, lir)
    for t in ("kile", "lir"):
        print("ORÁCULO", t.upper(), {k: round(v, 3) for k, v in res.get_metrics(t).items()})

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8"); main(*sys.argv[1:4])
