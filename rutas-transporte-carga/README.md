# Rutas de Transporte Terrestre de Mercancías (Perú)

**Status (2026-11-24): grafo vial construido y validado (notebooks 01 y 02). Pendiente: modelo de costo (03) y comparación de rutas (04).**

## Estado actual

| Notebook | Estado | Tablas en `workspace.rutas_transporte` |
|---|---|---|
| `01_download_and_load` | Corrido | `bronze_red_vial_2016` (3.750 tramos, 150 rutas), `bronze_peajes_2024_2025` (233 filas = 78 peajes × 3 cortes), `bronze_source_files` |
| `02_build_road_graph` | Corrido | `silver_graph_nodes`, `silver_graph_edges`, `silver_graph_components`, `silver_graph_tolerance_sensitivity`, `silver_graph_route_validation`, `silver_graph_self_loops`, `silver_graph_geometry_fixes` |
| `03_cost_model` | Por construir | — |
| `04_route_and_compare` | Por construir | — |

Dato clave para 03: **el GeoJSON de peajes no trae tarifas**; hay que sacarlas de otra fuente (OSITRAN / Provías, ver fuentes 5).

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

## El objetivo

Entre dos puntos cualquiera de Perú, encontrar la ruta terrestre de **menor costo real** para transportar mercancía, no la de menor distancia. Distancia y costo no son lo mismo en un país con la geografía de Perú: una ruta más corta por sierra puede salir más cara en combustible y tiempo que una ruta más larga mayormente pavimentada de costa, y los peajes cambian el cálculo según el tramo exacto elegido.

No es un problema de la ruta más corta (eso es geometría de grafos sin más). Es un problema de **costo mínimo sobre un grafo con pesos reales**, donde el peso de cada arista combina distancia, tipo de superficie, peaje y combustible — ahí es donde entra un modelo real, no solo correr Dijkstra sobre distancia.

## Fuentes de datos reales (verificadas en el catálogo del portal de datos abiertos de Perú)

Todas confirmadas como datasets reales y descargables durante la construcción de [`pnda-catalog-inventory`](../pnda-catalog-inventory/). Nombres exactos tal como aparecen en el portal:

1. **"MTC - DATOS ESPACIALES DE LA RED VIAL NACIONAL (2016)"** (MTC) — ZIP, probablemente shapefile con la geometría real de la red vial nacional.
2. **"Red vial nacional del Sistema Nacional de Carreteras 2022 a 2025"** (MTC) — CSV/DOCX/XLSX, datos tabulares de la red vial actualizados.
3. **"Infraestructura vial del Sistema Nacional de Carreteras por tipo de superficie, según departamento, 2022"** (MTC) — CSV, tipo de superficie por tramo/departamento.
4. **"MTC - DATOS ESPACIALES - PEAJES (2014)"** (ZIP) y **"Unidades de Peaje de la Red Vial Nacional 2024 – 2025"** (MTC, GEOJSON + PDF) — ubicación real de las unidades de peaje.
5. **"Recaudación en Soles - CARRETERAS"** (OSITRAN) y **"Recaudación de Unidades de Peaje a cargo de Provías Nacional"** (Provías Nacional) — tarifas/recaudación real por peaje.
6. **"Lista de Precios de combustibles, diaria"** (OSINERGMIN) — precio real y diario de combustibles, por región.
7. Opcional para una capa de riesgo: **"Accidentes de Tránsito - CARRETERAS"** (OSITRAN y SUTRAN por separado), **"Emergencias en la Red Vial Nacional"** (MTC).
8. Contexto/validación: **"Transporte Terrestre de Carga Nacional 2022-2025"** (MTC) y **"Parque vehicular habilitado para el Transporte Terrestre de Carga Internacional 2023-2025"** (MTC).

## Enfoque técnico

1. **Grafo de la red vial**: cargar la geometría de la red vial nacional con `geopandas`, construir un grafo navegable (nodos = intersecciones/puntos de la vía, aristas = tramos) con `networkx`. Si el shapefile del MTC viene con huecos (rutas no conectadas entre sí), documentarlo como limitación real, no forzar conectividad donde no la hay.
2. **Peso de cada arista** (el costo real del tramo), combinando: distancia × tiempo estimado según tipo de superficie, consumo de combustible estimado × precio vigente en la región, y peaje si el tramo pasa por una unidad de peaje (join espacial contra el GeoJSON de peajes).
3. **Selección de ruta**: algoritmo de camino de costo mínimo (Dijkstra o A*) sobre el grafo con esos pesos.
4. **Dónde entra el aprendizaje automático, específicamente**: el consumo de combustible por tramo no es un número fijo conocido, hay que estimarlo. Un modelo de regresión (Gradient Boosting o similar) entrenado sobre tipo de superficie, pendiente/elevación del tramo, y velocidad promedio, para predecir consumo real por km, en vez de asumir un factor constante. Esto es lo que separa este proyecto de un simple algoritmo de grafos: el costo de cada arista es una predicción, no un dato fijo.
5. **Salida**: dados origen y destino, la ruta de menor costo total (soles), con el desglose: km recorridos, costo estimado de combustible, costo de peajes, tiempo estimado — comparada contra la ruta de menor distancia simple, para evidenciar que no son la misma ruta.

## Método (notebooks, en orden)

1. `01_download_and_load` — descarga y carga los datasets de MTC/OSITRAN/OSINERGMIN como tablas Delta, siguiendo el mismo patrón de verificación de API que los demás proyectos de este repositorio.
2. `02_build_road_graph` — construye el grafo navegable de la red vial nacional a partir del shapefile.
3. `03_cost_model` — entrena el modelo de consumo de combustible por tramo y calcula el peso real de cada arista.
4. `04_route_and_compare` — calcula la ruta de menor costo entre dos puntos de ejemplo y la compara contra la ruta de menor distancia simple.

## Files

- `Notebook/01_download_and_load.py` — carga de red vial 2016 y peajes 2024-2025 a bronze.
- `Notebook/02_build_road_graph.py` — grafo navegable, sensibilidad a la tolerancia, componentes y validación.
