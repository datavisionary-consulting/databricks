# Rutas de Transporte Terrestre de Mercancías (Perú)

**Status: pendiente de descargar los dos archivos base.** No construido todavía — este README es el plan de trabajo, como los demás proyectos de este repositorio antes de tener resultados reales.

## ⚠️ Pendiente antes de empezar a construir

Descargar estos dos archivos desde [datosabiertos.gob.pe](https://www.datosabiertos.gob.pe) y confirmar su estructura real (columnas, sistema de coordenadas, si la red es un grafo conexo) antes de escribir cualquier pipeline:

1. **"MTC - DATOS ESPACIALES DE LA RED VIAL NACIONAL (2016)"** (ZIP)
2. **"Unidades de Peaje de la Red Vial Nacional 2024 – 2025"** (GEOJSON)

No asumir el esquema de ninguno de los dos sin haberlos abierto primero.

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

- `Notebook/` — notebooks reales, en orden de ejecución, una vez construidos.
