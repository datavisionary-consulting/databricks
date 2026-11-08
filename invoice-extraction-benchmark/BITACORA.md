# Bitácora de experimentos

Cada entrada registra qué se hizo, con qué datos, el comando exacto, el resultado y la decisión que se tomó. Solo hay cifras agregadas: el texto de las facturas no se publica, porque la licencia de DocILE es solo para investigación.

## Entorno

| Pieza | Valor |
|---|---|
| Plataforma | Databricks Free Edition (cuenta personal). CLI con el perfil `free` |
| Catálogo y esquema | `workspace.invoice_extraction_benchmark` |
| Volume | `/Volumes/workspace/invoice_extraction_benchmark/docile_pdfs/` con `dev/` (20, entrenamiento), `val_pilot/` (20, validación) y `val/` (500, validación) |
| Datos locales (fuera del repo) | `~/docile/data/docile` (corpus), `~/docile/data/baselines` (M1), `~/docile/dev`, `~/docile/piloto` |
| Librería oficial | `docile-benchmark` 0.3.5 |

**Regla de método:** el método M2 se ajusta solo con `dev/` (entrenamiento). La validación se evalúa una sola vez, con el método congelado.

---

## E0 · Descarga y verificación del corpus (2026-11-07)

- **Comando:** `./download_dataset.sh TOKEN annotated-trainval data/docile --unzip`
- **Resultado:** 5680 PDF, 5680 anotaciones y 5680 OCR. `train.json` = 5180 y `val.json` = 500.
- **Nota:** el nombre correcto del conjunto es `annotated-trainval`. `labeled-trainval`, que aparece en la ayuda del script, no existe en el servidor.

## E1 · Disponibilidad de funciones de IA en Free Edition (2026-11-08)

- **Notebook:** `Notebook/01_parse_test`.
- **Resultado:** `ai_parse_document` funciona. Devuelve bloques con su texto y coordenadas.
- **Observación:** una tabla devolvió cientos de filas vacías. En ese documento, los totales no aparecieron en la salida.

## E2 · M2 v1: esquema con los nombres de campo de DocILE (2026-11-08)

- **Notebook:** `Notebook/02_extract_m2` (celdas 1 a 3).
- **Datos:** `val_pilot` (20). ⚠️ Es validación, así que este resultado queda congelado y no se usa para ajustar nada.
- **Resultado con la métrica oficial de ubicación** (`tools/localize_and_eval.py`):

| Tarea | F1 |
|---|---|
| KILE | 0.312 |
| LIR | 0.250 |

## E3 · Control de validez de la ubicación (oráculo) (2026-11-08)

- **Comando:** `python tools/control_oraculo.py <dataset> <docids.json> <salida>`
- **Qué mide:** se ubican en el OCR los valores **correctos** de la propia anotación.
- **Resultado:**

| Tarea | F1 del oráculo |
|---|---|
| KILE | 0.663 |
| LIR | 0.381 |

- **Decisión:** la métrica de ubicación no es válida para M2, porque ni siquiera un extractor perfecto supera 0.66 con este procedimiento. La métrica principal pasa a ser **por valor**, igual para M1 y M2. La métrica oficial queda como referencia para M1.

## E4 · Confianza de `ai_extract` (2026-11-08)

- **Datos:** salida de E2.
- **Resultado:** 161 de 218 campos tienen confianza 1.0, pero solo 45 % acierta, medido por texto. La confianza no sirve para decidir qué revisar.

## E5 · M2 v2: método de producción (2026-11-08)

- **Notebook:** `Notebook/03_extract_m2_v2` (celdas 1 y 2).
- **Datos:** `dev/` (20, entrenamiento).
- **Esquema:** cabecera (número, fechas, emisor, moneda, total del PDF) y líneas (código, descripción, cantidad, costo unitario e importe, numéricos).
- **Tiempo:** 60.6 s de lectura y 145.9 s de extracción para 20 documentos.
- **Evaluación:** `python tools/eval_valores.py <dataset> m2v2_extracted_dev.json muestra_dev.json [detalle.xlsx]`
- **Tolerancias:** cantidad exacta, costo unitario con diferencia menor a 0.01, importe con diferencia menor a 0.50. Precio e importe toman el valor bruto y, si no existe, el neto.

**Cabecera**

| Campo | Aciertos |
|---|---|
| Número | 13/15 (86.7 %) |
| Fecha de emisión | 17/19 (89.5 %) |
| Vencimiento | 3/3 |
| Emisor | 11/15 (73.3 %) |
| Moneda | 12/13 (92.3 %) |
| Total | 15/19 (78.9 %) |

**Líneas:** 95 anotadas, 101 extraídas y 89 emparejadas (exhaustividad 93.7 %, precisión 88.1 %).

| Valor | Aciertos |
|---|---|
| Cantidad | 85/85 (100 %) |
| Costo unitario | 84/85 (98.8 %) |
| Importe | 87/88 (98.9 %) |
| Línea completa | 88/89 (98.9 %) |

**Alertas:** 13 de 20 facturas tienen algún error. La alerta señala 3, deja pasar 10 y da 6 falsas alarmas.

- **Decisión:** M2 v2 se congela sin ajustes el 2026-11-08 (commit `baf7930`).

## E6 · M1: predicciones publicadas de LayoutLMv3 (2026-11-08)

- **Descarga:** `./download_dataset.sh TOKEN baselines-layoutlmv3-ours data/baselines --unzip` (1.24 GB).
- **Verificación:** las predicciones reproducen las métricas oficiales sobre `val`:

| Tarea | AP | F1 |
|---|---|---|
| KILE | 0.513 | 0.657 |
| LIR | 0.546 | 0.666 |

- **Adaptación al esquema:** `python tools/m1_to_schema.py <predicciones> m1_val_schema.json`
- **Auditoría del adaptador:** M1 etiqueta algunos precios como netos. Se corrigió con la regla "bruto y, si no existe, neto", aplicada igual a la referencia y a las predicciones.
- **Resultado sobre `val_pilot` (20), métrica por valor:**

| Indicador | M1 |
|---|---|
| Cantidad | 90.5 % |
| Costo unitario | 88.3 % |
| Importe | 84.0 % |
| Línea completa | 82.5 % |
| Líneas encontradas | 69.6 % |

- **Tiempo de M1:** 500 documentos en ~3 min, según el registro de inferencia de los autores. El hardware no se publica.

## E7 · Evaluación final M1 vs. M2 v2 sobre `val` (500)

- **Extracción:** `Notebook/03_extract_m2_v2` (celdas 3 y 4). 341.7 s de lectura y 408.1 s de extracción para 500 documentos.
- **Evaluación:** `Notebook/04_evaluate` (usa `tools/eval_valores.py` y `tools/comparar.py`). Entradas en el volume `eval_inputs/`.
- **Resultados** (tabla `ieb_eval_resumen`, hoja pública `ieb_resultados_publicos`):

| Indicador | M1 | M2 v2 | Prueba | p |
|---|---|---|---|---|
| Línea completa, documentos con líneas (458) | 61.4 % | 72.7 % | Wilcoxon | < 0.001 |
| Diseños no vistos, 0-shot (98) | 32.8 % | 77.1 % | Wilcoxon | < 0.001 |
| Diseños vistos 1 a 3 veces (117) | 52.4 % | 63.6 % | Wilcoxon | 0.039 |
| Diseños vistos 4 o más veces (243) | 77.2 % | 75.3 % | Wilcoxon | 0.491 |
| Total del documento (468) | 87.8 % | 93.2 % | McNemar | 0.004 |
| Moneda (331) | 4.5 % | 92.7 % | McNemar | < 0.001 |

- **Lectura:** M2 supera a M1 sobre todo en diseños no vistos. En diseños frecuentes no hay diferencia significativa.
- **IC 95 % bootstrap:** generador propio con semilla 42 (commit `ca856da`). Con el generador global, Databricks daba intervalos distintos en cada corrida.

## E8 · Publicación en Google Sheets (2026-11-08)

- **Notebook:** `Notebook/05_export_gsheets`. Credencial en el secret `invoice-extraction-benchmark/gsheets_sa_json`.
- **Llave:** columna `clave` en cada pestaña. **Carga:** `hash_fila`, `id_carga` y `cargado_en` (hora de Lima). Bitácora de cargas en la pestaña `cargas`.
- **Prueba de idempotencia:** 04 → 05 → 04 → 05 en modo incremental. La segunda carga dio 0 filas nuevas y 0 actualizadas.

---

## Cómo verificar a mano

1. Abre el detalle en Excel: `~/docile/dev/DETALLE_M2v2_dev.xlsx` o `~/docile/piloto/DETALLE_M1_val_pilot.xlsx`. Tiene tres hojas: `cabecera`, `lineas` y `alertas`.
2. Elige una fila y abre el PDF de ese `docid`, en `~/docile/data/docile/pdfs/<docid>.pdf` o en el volume.
3. Compara el valor **anotado** y el **extraído** con lo que muestra la factura.
4. Para ver la salida cruda de M2, ejecuta en el SQL Editor de Free Edition:

   ```sql
   SELECT docid, extracted
   FROM workspace.invoice_extraction_benchmark.m2v2_extracted_dev
   WHERE docid = '<docid>';
   ```
