"""Comparación M1 vs M2 sobre los mismos documentos, con pruebas de hipótesis.

Por documento (solo los que tienen líneas anotadas):
  score_lineas = líneas completas correctas / líneas anotadas.
HE2: Shapiro-Wilk sobre las diferencias; si no son normales, Wilcoxon de rangos con
signo (si lo son, t pareada). HE3: lo mismo dentro de cada grupo de diseño.
HE1: McNemar por campo de cabecera (acierto sí/no por documento con el campo anotado).
HE5: McNemar sobre "factura con error señalada por la alerta" (solo facturas con
error en ambos modelos no aplica: se comparan las facturas con error en cada modelo
como proporciones e IC bootstrap).
IC 95 %: bootstrap de 10 000 remuestreos de documentos.

Uso: python comparar.py <dataset> <m1.json> <m2.json> <val_grupos.json> [salida.json]
"""
import json
import random
import sys
from pathlib import Path

from scipy.stats import binomtest, shapiro, ttest_rel, wilcoxon

from eval_valores import HEADER, evaluate

random.seed(42)


def doc_score(r):
    return sum(l["completa"] for l in r["lines"]) / r["n_ref_lines"] if r["n_ref_lines"] else None


def boot_ci(a, b, n=10000):
    idx = range(len(a)); diffs = []
    for _ in range(n):
        s = [random.choice(idx) for _ in idx]
        diffs.append(sum(b[i] - a[i] for i in s) / len(s))
    diffs.sort()
    return diffs[int(0.025 * n)], diffs[int(0.975 * n)]


def paired(a, b):
    d = [y - x for x, y in zip(a, b)]
    out = {"n": len(a), "media_M1": sum(a) / len(a), "media_M2": sum(b) / len(b), "dif_media": sum(d) / len(d)}
    nz = [x for x in d if x != 0]
    out["shapiro_p"] = shapiro(d).pvalue if len(set(d)) > 2 else None
    if out["shapiro_p"] is not None and out["shapiro_p"] >= 0.05:
        out["prueba"] = "t pareada"; out["p"] = ttest_rel(b, a).pvalue
    else:
        out["prueba"] = "Wilcoxon"; out["p"] = wilcoxon(b, a).pvalue if nz else 1.0
    out["ic95_dif"] = boot_ci(a, b)
    return out


def mcnemar(x1, x2):
    b = sum(1 for p, q in zip(x1, x2) if p and not q)   # solo M1 acierta
    c = sum(1 for p, q in zip(x1, x2) if q and not p)   # solo M2 acierta
    p = binomtest(b, b + c, 0.5).pvalue if b + c else 1.0  # McNemar exacto
    return {"solo_M1": b, "solo_M2": c, "p": p}


def comparar(ann_dir, m1, m2, G):
    """ann_dir: carpeta de anotaciones; m1/m2: {docid: {"response": ...}}; G: {docid: grupo}.
    Devuelve (res, R1, R2). Idempotente: misma entrada, misma salida (semilla fija en cada llamada)."""
    random.seed(42)
    A = Path(ann_dir)
    R1, R2 = {}, {}
    for d in G:
        ann = json.loads((A / f"{d}.json").read_text(encoding="utf-8"))
        R1[d] = evaluate(ann, m1[d]["response"]); R2[d] = evaluate(ann, m2[d]["response"])
    res = {"lineas": {}, "cabecera": {}, "alertas": {}}
    docs = [d for d in G if R1[d]["n_ref_lines"]]
    for grupo in ("todos", "0-shot", "1-3", "4+"):
        ds = [d for d in docs if grupo == "todos" or G[d] == grupo]
        res["lineas"][grupo] = paired([doc_score(R1[d]) for d in ds], [doc_score(R2[d]) for d in ds])
    for k in HEADER:
        ds = [d for d in G if R1[d]["head"][k]["ref"]]
        x1 = [R1[d]["head"][k]["ok"] for d in ds]; x2 = [R2[d]["head"][k]["ok"] for d in ds]
        res["cabecera"][k] = {"n": len(ds), "M1": sum(x1) / len(ds), "M2": sum(x2) / len(ds), **mcnemar(x1, x2)}
    for nm, R in (("M1", R1), ("M2", R2)):
        err = [d for d in G if R[d]["error"]]
        res["alertas"][nm] = {"facturas_con_error": len(err), "señaladas": sum(R[d]["alerta"] for d in err),
                              "falsas_alarmas": sum(R[d]["alerta"] and not R[d]["error"] for d in G)}
    for nm, R in (("M1", R1), ("M2", R2)):
        L = [l for d in G for l in R[d]["lines"]]
        nr = sum(R[d]["n_ref_lines"] for d in G); npd = sum(R[d]["n_pred_lines"] for d in G)
        res[f"agregado_{nm}"] = {"lineas_anotadas": nr, "lineas_extraidas": npd, "emparejadas": len(L),
                                 **{k: sum(l[k] for l in L if l[k] is not None) / max(1, sum(1 for l in L if l[k] is not None))
                                    for k in ("cantidad", "costo_unitario", "importe", "completa")}}
    return res, R1, R2


def main(dataset, m1p, m2p, gp, out=None):
    m1 = json.loads(Path(m1p).read_text(encoding="utf-8")); m2 = json.loads(Path(m2p).read_text(encoding="utf-8"))
    G = {d["docid"]: d["grupo"] for d in json.loads(Path(gp).read_text(encoding="utf-8"))}
    res, _, _ = comparar(Path(dataset) / "annotations", m1, m2, G)
    print(json.dumps(res, ensure_ascii=False, indent=1, default=lambda x: round(x, 4) if isinstance(x, float) else str(x)))
    if out:
        Path(out).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(*sys.argv[1:6])
