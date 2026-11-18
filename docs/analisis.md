# Conclusiones del análisis

Datos: histórico USGS de **2025** (1 ene – 31 dic, UTC), terremotos (`eventType=earthquake`) de **magnitud ≥ 4** de todo el mundo, **18.302 eventos** (ver [procedencia.md](procedencia.md)). Todas las cifras salen de `observatorio.historical_events`, sin filas sintéticas (que solo existen en el esquema temporal del benchmark). Las consultas se pueden ejecutar tal cual con `psql`.

## Conclusión 1 — La actividad de 2025 está dominada por una sola secuencia sísmica

*Filtros:* periodo 2025-01-01 → 2025-12-31, M ≥ 4, sin filtro de país.

- Julio concentra **2.684** eventos frente a una media mensual de **1.525** (18.302 / 12): **+76 %** (×1,76). Agosto (2.222) también queda por encima; el resto de meses oscila entre 1.156 y 1.604.
- El día con más eventos es el **30 de julio** (**645** eventos) frente a una media diaria de 50,1 (18.302 / 365): **×12,9** en un solo día. Los tres días siguientes (315, 234 y el 20 de julio con 198) son también los más altos del año.
- La causa está en los propios datos: el evento de mayor magnitud del año es el **M 8,8 de la península de Kamchatka (29 de julio)**, y julio es además el mes con más eventos M ≥ 6 (**28**, frente a 3–16 en los demás meses).

```sql
SELECT to_char(date_trunc('day', time_utc),'YYYY-MM-DD') dia, count(*) FROM observatorio.historical_events GROUP BY 1 ORDER BY 2 DESC LIMIT 5;
SELECT to_char(date_trunc('month', time_utc),'YYYY-MM') mes, count(*), count(*) FILTER (WHERE mag >= 6) FROM observatorio.historical_events GROUP BY 1 ORDER BY 1;
SELECT place, mag, time_utc FROM observatorio.historical_events ORDER BY mag DESC LIMIT 3;
```

*Lectura:* una media anual esconde la estructura temporal; la réplica de un gran terremoto (≈ 650 réplicas M ≥ 4 en 24 h) distorsiona cualquier comparación «24 h frente a la media», por lo que la razón del panel debe interpretarse con esta cautela.

## Conclusión 2 — La distribución de magnitudes sigue una ley de potencias (Gutenberg-Richter)

*Filtros:* 2025, M ≥ 4, todo el mundo.

| Umbral | Eventos | % del total | Factor respecto al umbral anterior |
|---|---:|---:|---:|
| M ≥ 4 | 18.302 | 100 % | — |
| M ≥ 5 | 2.129 | 11,6 % | ÷ 8,6 |
| M ≥ 6 | 145 | 0,79 % | ÷ 14,7 |
| M ≥ 7 | 16 | 0,087 % | ÷ 9,1 |
| M ≥ 8 | 1 | 0,005 % | ÷ 16 |

Cada unidad de magnitud reduce el número de eventos en un factor ≈ 9–15 (cercano a 10, es decir, *b* ≈ 1). Magnitud media 4,51: la inmensa mayoría son eventos moderados y los grandes terremotos son raros (16 de M ≥ 7 en todo el año).

```sql
SELECT count(*) FILTER (WHERE mag>=5) m5, count(*) FILTER (WHERE mag>=6) m6, count(*) FILTER (WHERE mag>=7) m7, count(*) FILTER (WHERE mag>=8) m8, count(*) FROM observatorio.historical_events;
```

## Conclusión 3 — La mayor parte de la sismicidad M ≥ 4 es marina y superficial, y el país asignado es una aproximación

*Filtros:* 2025, M ≥ 4, todo el mundo; asignación por punto en polígono (catálogo Natural Earth de baja resolución).

- **78,4 %** de los eventos (**14.350**) quedan como «Sin país asignado»: epicentros en mar abierto o en costas fuera de los polígonos simplificados. Entre los que sí tienen país lideran **China (354; 1,9 %)**, **Chile (348)**, **Indonesia (306)**, **Etiopía (265)** y **Argentina (236)**.
- Profundidad: mediana **20,9 km**; **13.689 eventos (74,8 %) son superficiales (< 70 km)** y solo **1.102 (6,0 %) profundos (≥ 300 km)**.
- Exactitud medida: entre los **1.630** eventos a ≤ 20 km de su pueblo de referencia, la asignación coincide con el país nombrado en `place` en el **71,6 %** (ver [calidad.md](calidad.md), dimensión 6). Los fallos son costas e islas pequeñas que el catálogo no recoge (p. ej. Port-Vila, Vanuatu).

```sql
SELECT coalesce(c.name,'Sin país asignado') pais, count(*) n, round(100.0*count(*)/(SELECT count(*) FROM observatorio.historical_events),1) pct
FROM observatorio.historical_events h LEFT JOIN observatorio.dim_country c USING (country_id) GROUP BY 1 ORDER BY 2 DESC LIMIT 8;
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY depth), count(*) FILTER (WHERE depth<70), count(*) FILTER (WHERE depth>=300) FROM observatorio.historical_events;
```

*Lectura:* los recuentos por país no miden «peligrosidad por país» sino «eventos cuyo epicentro cae dentro del polígono»; con un catálogo de mayor resolución subiría la proporción asignada y aparecerían islas y costas hoy ausentes del ranking. La conclusión sobre el carácter marino y superficial se mantiene aunque cambie el catálogo, porque no depende de él.

## Observación en vivo (24 h frente a la media de 2025)

*Filtros:* `min_mag=4`, últimas 24 h hasta 2026-11-18 20:19 UTC, `GET /api/estadisticas?min_mag=4`: **23** eventos frente a una media diaria 2025 de **50,14** → razón **0,46×**. Es una instantánea (la API la recalcula en cada consulta) y el último periodo puede estar incompleto por revisiones tardías de USGS; no debe leerse como tendencia.
