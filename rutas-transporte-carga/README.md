# Rutas de Transporte Terrestre de Mercancías (Perú)

**Status (2026-11-25): grafo vial (01-02) y emergencias 2026 ubicadas en el grafo (03). Siguiente: modelo de costo con costo esperado de interrupción (04).**

## Estado actual

| Notebook | Estado | Tablas en `workspace.rutas_transporte` |
|---|---|---|
| `01_download_and_load` | Corrido | `bronze_red_vial_2016` (3.750 tramos, 150 rutas), `bronze_peajes_2024_2025` (233 filas = 78 peajes × 3 cortes), `bronze_source_files` |
| `02_build_road_graph` | Corrido | `silver_graph_nodes`, `silver_graph_edges`, `silver_graph_components`, `silver_graph_tolerance_sensitivity`, `silver_graph_route_validation`, `silver_graph_self_loops`, `silver_graph_geometry_fixes` |
| `03_emergencies_on_graph` | Corrido | `bronze_emergencias_2026`, `silver_emergencias_route_coverage`, `silver_emergencias_on_edges`, `silver_edge_emergencias` |
| `04_cost_model` | Por construir | — |
| `05_routes_and_resilience` | Por construir | — |

Dato clave para 04: **el GeoJSON de peajes no trae tarifas**; hay que sacarlas de otra fuente (OSITRAN / Provías, ver fuente 5).

Archivos base en el volumen `workspace.rutas_transporte.raw_data` (subidos desde el navegador: la descarga por script devolvía HTTP 418 del WAF del portal).

### Resultados del grafo (tolerancia 50 m, corrida 2026-11-25)

- **3.758 nodos, 3.891 aristas, 3 componentes.** Sin corregir (extremos tal cual) eran 293 componentes y el mayor tenía 51 % de los km.
- **El componente principal cubre el 99,35 % de los km de la red** (28.488 km; 25 departamentos, todas las troncales). Fuera de él: PE-5NI en Loreto (176 km, sin enlace terrestre, real) y un fragmento de PE-5NA en Huánuco (0,3 km).
- **Validación contra el km oficial del MTC** (camino más corto dentro de cada ruta vs `max(dkmFinal) − min(dkmInicio)`): diferencia máxima 0,44 % (PE-22); PE-1N, PE-1S, PE-3N, PE-3S, PE-5N y PE-1NQ dentro de ±0,3 %, cada una en un solo componente.

### Correcciones de geometría

**Trazos de ida y vuelta** (`silver_graph_geometry_fixes`). Algunos registros del shapefile van hasta su punto más lejano y vuelven por el mismo camino al inicio. Como sus extremos coinciden, el grafo los descartaba enteros. Regla en 02: extremos a ≤ 50 m y la vuelta repite la ida (distancia de Hausdorff ≤ 5 m) → se conserva solo la ida. Un anillo real o una curva cerrada no cumplen la segunda condición.

| Ruta | Registro | Piezas | Desvío ida/vuelta | km antes | km después | km oficial (`dLongitud`) |
|---|---|---|---|---|---|---|
| PE-1NQ (Áncash) | 5493 | 1 | 0 m | 69,38 | 34,69 | 34,66 |
| PE-5NA (Huánuco) | 3540 | 21 | 0 m | 7,21 | 3,60 | 5,10 |

PE-1NQ estaba fuera del grafo y ahora entra completa (34,64 km por el grafo, −0,05 % vs oficial). En PE-5NA la mitad (3,6 km) no llega a los 5,1 km oficiales: falta revisar ese registro.

**Denominador único.** Todos los porcentajes de km en 02 se calculan sobre la red completa (28.488 km tras las correcciones), antes de descartar self-loops. `silver_graph_tolerance_sensitivity` trae `network_km`, `graph_km` y `self_loops_km`.

**Self-loops** (`silver_graph_self_loops`): tramos cuyos dos extremos caen en el mismo nodo; se descartan. A 50 m quedan 255 tramos y 7,9 km (antes de corregir los trazos de ida y vuelta eran 77,7 km):

| Tipo | Tramos | km | Qué es |
|---|---|---|---|
| `corto` | 217 | 4,8 | Pieza de ≤ 50 m |
| `extremos_cercanos` | 32 | 2,4 | Más larga que 50 m, termina a ≤ 50 m de donde empieza |
| `cadena` | 6 | 0,7 | Extremos a 51–76 m, unidos por una cadena de puntos intermedios |

Otros totales, para no confundir: `bronze_red_vial_2016.length_km_geodesic` suma 28.584 km y 02, antes de corregir, mide 28.526 km. 01 usa haversine (esfera) y 02 el elipsoide WGS84; esa es la causa probable de esa diferencia (0,2 %), no verificada. El atributo oficial `dLongitud` suma 28.502 km.

### Emergencias 2026 sobre el grafo (03, corrida 2026-11-25)

Fuente: MTC-COES, 1.362 emergencias del 01.01 al 20.08.2026; 86 % por lluvias. Las de enero a marzo suman 809.

| Ubicación | Eventos | Con interrupción inicial | Regla |
|---|---|---|---|
| `ruta_propia` | 1.246 | 251 | Arista de su misma ruta a ≤ 500 m (mediana 7 m, p95 49 m) |
| `ruta_corregida` | 24 | 5 | Su ruta está a > 5 km o no existe en el grafo, pero hay otra ruta a ≤ 100 m: el código de ruta del reporte está mal, el punto está sobre una vía real |
| `no_ubicado` | 92 | 30 | Sobre todo rutas que no existen en la red 2016 (PE-1SI, PE-5NG, PE-36G…) |

- **93 % de los eventos quedan ubicados** en 583 aristas, que suman 8.545 km (30 % de la red).
- Rutas con más eventos: PE-3N (128), PE-5N (108), PE-22 (58, 19 con interrupción inicial), PE-5NA (52). PE-3S tiene menos eventos (38), pero 24 empezaron con la vía interrumpida.
- **El km progresivo del reporte no sirve para validar**: en 198 eventos ubicados sobre su ruta, el km 2026 no coincide con el del shapefile 2016 (desfase mediano en PE-3N: 31 km). Se guarda como información; la ubicación usa las coordenadas.
- `dias_hasta_normal` mide hasta el fin de los trabajos, no la duración del corte.

## El objetivo

**Reducir lo que cuestan al Perú las interrupciones de carreteras por lluvias, huaicos e inundaciones, como las del Fenómeno El Niño.** Cuando un tramo se cae, la carga espera o se desvía, y ambas cosas cuestan dinero: combustible, horas de camión, peajes adicionales, mercancía perecible que se pierde.

El proyecto responde tres preguntas, en este orden:

1. **¿Qué tramos de la red vial nacional se interrumpen y con qué frecuencia?** A partir de los reportes oficiales de emergencias del MTC, ubicados sobre el grafo de la red.
2. **Entre dos puntos, ¿cuál es la ruta de menor costo esperado?** Costo esperado = combustible + peajes + tiempo + el costo probable de quedar detenido o desviado en tramos con historial de interrupciones. No es la ruta más corta: en Perú, una ruta más corta por sierra o por un valle propenso a huaicos puede salir más cara que una más larga y estable.
3. **Si un tramo crítico se corta, ¿cuál es la mejor alternativa y cuánto más cuesta?** Y, a la inversa: ¿qué tramos, al caerse, encarecen más el transporte o dejan zonas aisladas? Esos son los tramos donde la prevención o una ruta alterna preparada rinde más.

Uso previsto: apoyo a la decisión para transportistas, generadores de carga y entidades que planifican la respuesta (rutas alternas, priorización de mantenimiento preventivo). No es un sistema de alerta en tiempo real.

### Límites que hay que decir desde ya

- El archivo de emergencias publicado cubre **01.01 al 20.08.2026** (temporada de lluvias 2026). No incluye El Niño costero 2017 ni 2023. Con un solo periodo no se puede separar el efecto de El Niño del de una temporada de lluvias normal; el resultado será "tramos que se interrumpen en temporada de lluvias", no "tramos afectados por El Niño", salvo que se consigan periodos anteriores.
- La geometría de la red es de 2016. Rutas o variantes construidas después no están en el grafo.
- No se inventan cifras de costo: cada componente sale de un dato publicado (precios OSINERGMIN, peajes, reportes MTC) o se declara como supuesto, con sensibilidad.

## Fuentes de datos reales (verificadas en el catálogo del portal de datos abiertos de Perú)

Nombres exactos tal como aparecen en [datosabiertos.gob.pe](https://www.datosabiertos.gob.pe), tomados de `workspace.pnda_catalog.bronze_pnda_catalogo` (construido en [`pnda-catalog-inventory`](../pnda-catalog-inventory/)).

**Núcleo**

1. **"MTC - DATOS ESPACIALES DE LA RED VIAL NACIONAL (2016)"** (MTC) — shapefile. **Cargado** (`bronze_red_vial_2016`).
2. **"Unidades de Peaje de la Red Vial Nacional 2024 – 2025"** (MTC, GeoJSON + PDF). **Cargado** (`bronze_peajes_2024_2025`). Sin tarifas.
3. **"Emergencias en la Red Vial Nacional"** (MTC-COES) — CSV `3. Reporte Emergencias 01.01 al 20.08.2026 COES-MTC.csv` + diccionario XLSX + metadatos PDF; actualizado 2026-08-25. Según el portal trae: tipo de peligro que causa la afectación, ruta, tramo, sector, estado de la transitabilidad, administrador de la vía, departamento/provincia/distrito y coordenadas decimales. **En el volumen** `raw_data` (subido 2026-11-25, descargado desde el navegador). Revisado: 1.362 eventos, 22 columnas, `;` como separador, codificación cp1252; ocurrencias 01.01–20.08.2026; coordenadas todas dentro de Perú; cada `AFECTACION` trae rango de km progresivo (`Km 720+000 - Km 781+000`), utilizable para ubicar el evento con `dkmInicio`/`dkmFinal` además de las coordenadas. 93 de las 106 rutas (1.277 eventos) existen en el grafo 2016; 13 rutas (85 eventos) no, p. ej. PE-1SI (35), PE-5NG (20), PE-36G (17). `FECHA_CIERRE` marca el fin de los trabajos (vuelta a NORMAL), no la reapertura del tránsito: es duración de la emergencia, no del corte. Nombres de columna distintos al diccionario: `FECHA_OCURRENCIA` (dicc.: FECHA), `DEPARTEMENTO`, `TRAMO_AFECADO`.
4. **"Lista de Precios de combustibles, diaria"** (OSINERGMIN) — precio de combustible por región.
5. **"Recaudación en Soles - CARRETERAS"** (OSITRAN) y **"Recaudación de Unidades de Peaje a cargo de Provías Nacional"** (Provías Nacional) — para obtener tarifas, que el GeoJSON de peajes no trae.

**Apoyo y validación**

6. **"Infraestructura vial del Sistema Nacional de Carreteras por tipo de superficie, según departamento, 2022"** y **"Red vial nacional del Sistema Nacional de Carreteras 2022 a 2025"** (MTC) — superficie y red actualizada.
7. **"Llamadas de Emergencia - CARRETERAS"** (OSITRAN) — llamadas por periodo en vías concesionadas; posible contraste de frecuencia.
8. **"Accidentes de Tránsito - CARRETERAS"** (OSITRAN, SUTRAN) — riesgo de accidente por tramo (secundario frente a interrupciones).
9. **"Intervenciones período de lluvias 2015-2016 y Fenómeno El Niño"** (MEF) — gasto público en emergencias 2015-2016. Solo contexto de magnitud; no confirmado que esté georreferenciado.
10. **"Transporte Terrestre de Carga Nacional 2022-2025"** (MTC) — volumen de carga, para pesar qué rutas importan más.

## Enfoque técnico

1. **Grafo de la red vial** (hecho, 02): nodos = intersecciones, aristas = tramos con longitud geodésica y atributos MTC.
2. **Emergencias sobre el grafo** (03): cada evento se ubica en la arista más cercana de **su misma ruta** (coordenadas + código de ruta), con distancia de ajuste registrada y descartes reportados. Por arista: número de eventos, tipo de peligro, estado de transitabilidad (interrumpida / restringida) y, si el dato existe, duración. De ahí sale una frecuencia de interrupción por tramo en temporada de lluvias.
3. **Costo de cada arista** (04): combustible (consumo estimado × precio regional), peaje, tiempo según superficie, y **costo esperado de interrupción** = probabilidad de interrupción × costo de espera o desvío. El consumo por km se modela (regresión sobre superficie, pendiente y velocidad) en vez de usar un factor fijo; todo supuesto va con análisis de sensibilidad.
4. **Rutas y resiliencia** (05): ruta de menor costo esperado vs ruta más corta para pares origen-destino de carga real; luego, cortar uno por uno los tramos con más emergencias y medir el sobrecosto de la mejor alternativa o si el destino queda aislado. Salida: ranking de tramos críticos con su sobrecosto y su ruta alterna.

## Método (notebooks, en orden)

1. `01_download_and_load` — carga red vial 2016 y peajes 2024-2025 a bronze. **Hecho.**
2. `02_build_road_graph` — grafo navegable, correcciones de geometría, validación vs km oficial. **Hecho.**
3. `03_emergencies_on_graph` — carga el reporte de emergencias MTC-COES y lo ubica sobre las aristas del grafo. **Hecho.**
4. `04_cost_model` — costo de cada arista: combustible, peaje, tiempo y costo esperado de interrupción.
5. `05_routes_and_resilience` — rutas de menor costo esperado, escenarios de corte de tramos críticos y ranking de tramos.

## Files

- `Notebook/01_download_and_load.py` — carga de red vial 2016 y peajes 2024-2025 a bronze.
- `Notebook/02_build_road_graph.py` — grafo navegable, sensibilidad a la tolerancia, componentes y validación.
- `Notebook/03_emergencies_on_graph.py` — emergencias MTC-COES 2026 ubicadas en las aristas del grafo y resumen por arista.
