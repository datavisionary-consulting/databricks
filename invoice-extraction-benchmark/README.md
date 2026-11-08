# Invoice Extraction Benchmark (DocILE)

**Status: piloto.** Este README es el plan de trabajo, como los demás proyectos de este repositorio antes de tener resultados reales.

## El objetivo

Comparar, sobre los mismos documentos, dos formas de extraer información de facturas comerciales:

- **M1 – modelo especializado:** LayoutLMv3 con los pesos publicados por los autores de DocILE.
- **M2 – modelo de lenguaje multimodal sin entrenamiento:** `ai_parse_document` + `ai_extract` en Databricks, con un esquema genérico y sin ejemplos.

La pregunta: ¿un modelo general, sin entrenamiento, alcanza o supera a uno especializado, sobre todo en diseños de factura que nunca vio?

## Datos

[DocILE](https://github.com/rossumai/docile) (Šimsa et al., ICDAR 2023): 6680 documentos comerciales anotados, de 1152 diseños.
- **Muestra:** la partición de validación, 500 documentos y 204 diseños.
- **Grupos por diseño:** 124 de diseños no vistos (0-shot), 126 vistos de 1 a 3 veces y 250 vistos 4 veces o más.

⚠️ **Los datos no se suben a este repositorio.** El acceso a DocILE es solo para investigación y requiere un token propio. Los PDF viven en un Volume de Unity Catalog: `/Volumes/workspace/invoice_extraction_benchmark/docile_pdfs/`.

## Métricas

Las del evaluador oficial de DocILE:
- **KILE** (información clave): AP, F1, precisión y exhaustividad.
- **LIR** (ítems de línea): F1.

Se calculan en total, por campo y por grupo de diseño, y se suman el tiempo y el costo por documento. Las diferencias M1 vs. M2 se contrastan por documento: Shapiro-Wilk para la normalidad, luego t pareada o Wilcoxon, McNemar por campo y bootstrap para los intervalos.

## Método (notebooks, en orden)

1. `01_parse_test`: prueba `ai_parse_document` con un PDF. ¿Están las funciones de IA en Free Edition?
2. `02_extract_m2`: `ai_extract` con el esquema genérico sobre el piloto de 20 documentos.
3. `03_infer_m1`: inferencia de LayoutLMv3 (GPU serverless o Colab).
4. `04_evaluate`: conversión al formato de predicciones de DocILE, evaluación y pruebas estadísticas.

## Files

- `Notebook/`: notebooks en orden de ejecución.
