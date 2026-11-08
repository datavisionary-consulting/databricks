"""Ubica en la página los valores que devuelve M2 y los evalúa con el evaluador
oficial de DocILE (KILE y LIR).

M2 (ai_extract) devuelve texto, no recuadros. Para la métrica oficial, cada valor
se busca entre las palabras del OCR del corpus: se prueba toda secuencia de
palabras consecutivas (hasta MAX_WORDS) y se elige la más parecida comparando
solo letras y dígitos. Si la similitud no llega a MIN_RATIO, el valor se descarta
(cuenta como no extraído). El recuadro del campo es la unión de esas palabras.

Uso:
  python localize_and_eval.py <dataset_path> <m2_extracted.json> <docids.json> <salida_dir>
No guarda texto de facturas en el repositorio: la salida va a <salida_dir>.
"""
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

from docile.dataset import BBox, CachingConfig, Dataset, Field, KILE_FIELDTYPES, LIR_FIELDTYPES, store_predictions
from docile.evaluation import evaluate_dataset

MAX_WORDS = 40
MIN_RATIO = 0.8


def norm(s):
    return re.sub(r"[^0-9a-z]", "", str(s).lower())


def union(fields):
    return BBox(min(f.bbox.left for f in fields), min(f.bbox.top for f in fields),
                max(f.bbox.right for f in fields), max(f.bbox.bottom for f in fields))


def locate(value, words):
    """Devuelve (inicio, fin, similitud) de la mejor secuencia de palabras."""
    t = norm(value)
    if not t:
        return None
    best = (None, None, 0.0)
    wn = [norm(w.text) for w in words]
    for i in range(len(words)):
        acc = ""
        for j in range(i, min(i + MAX_WORDS, len(words))):
            acc += wn[j]
            if len(acc) > 2 * len(t) + 5:
                break
            if not acc:
                continue
            r = SequenceMatcher(None, acc, t, autojunk=False).ratio()
            if r > best[2]:
                best = (i, j, r)
            if r == 1.0:
                return best
    return best if best[2] >= MIN_RATIO else None


def to_fields(doc, resp):
    """Convierte la respuesta de ai_extract en predicciones KILE y LIR ubicadas."""
    pages = range(doc.page_count)
    words = {p: doc.ocr.get_all_words(p, snapped=True) for p in pages}
    kile, lir, stats = [], [], {"valores": 0, "ubicados": 0}

    def place(value, fieldtype, score, li_id=None):
        stats["valores"] += 1
        for p in pages:
            hit = locate(value, words[p])
            if hit:
                i, j, r = hit
                stats["ubicados"] += 1
                return Field(bbox=union(words[p][i:j + 1]), page=p, score=score,
                             text=str(value), fieldtype=fieldtype, line_item_id=li_id)
        return None

    for k, v in resp.items():
        if k == "line_items" or k not in KILE_FIELDTYPES or not v or v.get("value") in (None, ""):
            continue
        f = place(v["value"], k, v.get("confidence_score") or 0.0)
        if f:
            kile.append(f)
    for li_id, item in enumerate(resp.get("line_items") or []):
        for k, v in item.items():
            if k not in LIR_FIELDTYPES or not v or v.get("value") in (None, ""):
                continue
            f = place(v["value"], k, v.get("confidence_score") or 0.0, li_id)
            if f:
                lir.append(f)
    return kile, lir, stats


def main(dataset_path, extracted_path, docids_path, out_dir):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    ext = json.loads(Path(extracted_path).read_text(encoding="utf-8"))
    docids = [d["docid"] if isinstance(d, dict) else d for d in json.loads(Path(docids_path).read_text(encoding="utf-8"))]
    full = Dataset("val", dataset_path, cache_images=CachingConfig.OFF)
    ds = Dataset.from_documents("subset", [full[d] for d in docids])
    kile, lir, tot = {}, {}, {"valores": 0, "ubicados": 0}
    for doc in ds:
        k, l, s = to_fields(doc, ext[doc.docid]["response"])
        kile[doc.docid], lir[doc.docid] = k, l
        for x in tot:
            tot[x] += s[x]
    store_predictions(out / "m2_kile_predictions.json", kile)
    store_predictions(out / "m2_lir_predictions.json", lir)
    res = evaluate_dataset(ds, kile, lir)
    res.to_file(out / "m2_evaluation.json")
    print(f"Valores devueltos por M2: {tot['valores']} | ubicados en el OCR: {tot['ubicados']}")
    for task in ("kile", "lir"):
        m = res.get_metrics(task)
        print(task.upper(), {k: round(v, 3) for k, v in m.items()})


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(*sys.argv[1:5])
