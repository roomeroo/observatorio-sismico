"""Data-quality report (6 dimensions, before/after, sample records).

Reproduce the figures in docs/calidad.md:

    docker compose run --rm producer python tools/quality.py            # markdown on stdout
    docker compose run --rm producer python tools/quality.py --json     # machine-readable

Every figure comes from the SQL printed next to it; nothing is hard-coded.
"""

import argparse
import json
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from observatorio.database import postgres_connection_parameters  # noqa: E402
from observatorio.geo import get_catalog  # noqa: E402

CE = "observatorio.current_events"
MAX_REFERENCE_KM = 20
QUERIES: dict[str, tuple[str, str]] = {
    # ---- BEFORE: raw feed as downloaded (all stored payloads) ----
    "raw_polls": ("Sondeos con payload guardado", "SELECT count(*) FROM observatorio.poll_log WHERE payload_hash IS NOT NULL"),
    "raw_features": (
        "Features recibidas (suma de todos los sondeos)",
        "SELECT coalesce(sum(jsonb_array_length(r.payload->'features')),0) FROM observatorio.poll_log p "
        "JOIN observatorio.raw_payloads r USING (payload_hash)",
    ),
    "raw_non_quake": (
        "Features que no son `earthquake` (excluidas)",
        "SELECT count(*) FROM observatorio.poll_log p JOIN observatorio.raw_payloads r USING (payload_hash), "
        "jsonb_array_elements(r.payload->'features') f WHERE f->'properties'->>'type' <> 'earthquake'",
    ),
    "raw_distinct_versions": (
        "Versiones distintas (id, updated) de terremotos en los payloads",
        "SELECT count(*) FROM (SELECT DISTINCT f->>'id', f->'properties'->>'updated' "
        "FROM observatorio.raw_payloads r, jsonb_array_elements(r.payload->'features') f "
        "WHERE f->'properties'->>'type'='earthquake') t",
    ),
    "raw_distinct_ids": (
        "Eventos distintos (id) de terremotos en los payloads",
        "SELECT count(DISTINCT f->>'id') FROM observatorio.raw_payloads r, jsonb_array_elements(r.payload->'features') f "
        "WHERE f->'properties'->>'type'='earthquake'",
    ),
    "raw_null_mag": (
        "Terremotos con magnitud nula en el payload (versiones distintas)",
        "SELECT count(*) FROM (SELECT DISTINCT f->>'id' i, f->'properties'->>'updated' u FROM observatorio.raw_payloads r, "
        "jsonb_array_elements(r.payload->'features') f WHERE f->'properties'->>'type'='earthquake' "
        "AND f->'properties'->>'mag' IS NULL) t",
    ),
    # ---- AFTER: current state ----
    "current_events": ("Eventos en `current_events`", f"SELECT count(*) FROM {CE}"),
    "versions": ("Versiones en `event_versions`", "SELECT count(*) FROM observatorio.event_versions"),
    "quarantine": ("Registros en cuarentena", "SELECT count(*) FROM observatorio.quarantine_records"),
    # completeness
    "null_mag": ("Magnitud nula", f"SELECT count(*) FROM {CE} WHERE mag IS NULL"),
    "null_place": ("Lugar nulo", f"SELECT count(*) FROM {CE} WHERE place IS NULL"),
    "null_depth": ("Profundidad nula", f"SELECT count(*) FROM {CE} WHERE depth IS NULL"),
    "null_country": ("Sin país asignado", f"SELECT count(*) FROM {CE} WHERE country_id IS NULL"),
    "hist_total": ("Histórico 2025: eventos", "SELECT count(*) FROM observatorio.historical_events"),
    "hist_null_mag": ("Histórico 2025: magnitud nula", "SELECT count(*) FROM observatorio.historical_events WHERE mag IS NULL"),
    "hist_null_depth": ("Histórico 2025: profundidad nula", "SELECT count(*) FROM observatorio.historical_events WHERE depth IS NULL"),
    "hist_null_country": ("Histórico 2025: sin país", "SELECT count(*) FROM observatorio.historical_events WHERE country_id IS NULL"),
    # validity
    "invalid_coords": (
        "Coordenadas fuera de rango",
        f"SELECT count(*) FROM {CE} WHERE longitude NOT BETWEEN -180 AND 180 OR latitude NOT BETWEEN -90 AND 90",
    ),
    "invalid_mag": ("Magnitud fuera de [-2, 10]", f"SELECT count(*) FROM {CE} WHERE mag IS NOT NULL AND mag NOT BETWEEN -2 AND 10"),
    "invalid_depth": ("Profundidad fuera de [-10, 800] km", f"SELECT count(*) FROM {CE} WHERE depth NOT BETWEEN -10 AND 800"),
    "future_time": ("Eventos con hora en el futuro", f"SELECT count(*) FROM {CE} WHERE time_utc > clock_timestamp()"),
    "non_quake_current": ("`event_type` distinto de earthquake en el estado actual", f"SELECT count(*) FROM {CE} WHERE event_type <> 'earthquake'"),
    # uniqueness
    "dup_versions": (
        "Pares (id, updated) repetidos en `event_versions`",
        "SELECT count(*) FROM (SELECT event_id, updated FROM observatorio.event_versions GROUP BY 1,2 HAVING count(*)>1) t",
    ),
    "dup_current": (
        "ids repetidos en `current_events`",
        f"SELECT count(*) FROM (SELECT event_id FROM {CE} GROUP BY 1 HAVING count(*)>1) t",
    ),
    "multi_version": (
        "Eventos con más de una versión (revisados)",
        "SELECT count(*) FROM (SELECT event_id FROM observatorio.event_versions GROUP BY 1 HAVING count(*)>1) t",
    ),
    # consistency
    "stale_current": (
        "Eventos cuyo estado actual no es la versión más reciente",
        f"SELECT count(*) FROM {CE} c JOIN (SELECT event_id, max(updated) m FROM observatorio.event_versions GROUP BY 1) v "
        "USING (event_id) WHERE c.updated <> v.m",
    ),
    "updated_before_time": ("Revisión anterior a la hora del evento", f"SELECT count(*) FROM {CE} WHERE updated_utc < time_utc"),
    "orphan_country": (
        "country_id sin fila en `dim_country`",
        f"SELECT count(*) FROM {CE} c LEFT JOIN observatorio.dim_country d USING (country_id) "
        "WHERE c.country_id IS NOT NULL AND d.country_id IS NULL",
    ),
    "ambiguous": ("Asignaciones de país ambiguas (frontera)", f"SELECT count(*) FROM {CE} WHERE geo_ambiguous"),
    # timeliness
    "lag_event_to_ingest_p50": (
        "Retraso evento → ingesta, mediana (s)",
        f"SELECT round(percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM ingested_at - time_utc))::numeric,0) FROM {CE}",
    ),
    "lag_event_to_ingest_p95": (
        "Retraso evento → ingesta, p95 (s)",
        f"SELECT round(percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM ingested_at - time_utc))::numeric,0) FROM {CE}",
    ),
    "lag_ingest_to_store_p95": (
        "Retraso ingesta → PostgreSQL, p95 (s)",
        "SELECT round(percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM received_at - ingested_at))::numeric,2) "
        "FROM observatorio.event_versions",
    ),
    "poll_latency_p50": (
        "Latencia del sondeo USGS, mediana (ms)",
        "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) FROM observatorio.poll_log WHERE status='ok'",
    ),
    "poll_latency_p95": (
        "Latencia del sondeo USGS, p95 (ms)",
        "SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) FROM observatorio.poll_log WHERE status='ok'",
    ),
    "poll_failures": ("Sondeos fallidos", "SELECT count(*) FROM observatorio.poll_log WHERE status <> 'ok'"),
}


def run_queries(conn) -> dict[str, tuple[str, str, object]]:
    out = {}
    for key, (label, sql) in QUERIES.items():
        value = conn.execute(sql).fetchone()[0]
        if value is not None and not isinstance(value, (int, float, str)):
            value = float(value)
        out[key] = (label, sql, value)
    return out


def exclusion_reasons(conn):
    return conn.execute(
        "SELECT reason, count(*) FROM observatorio.poll_exclusions GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()


def quarantine_reasons(conn):
    return conn.execute(
        "SELECT rejection_reason, count(*) FROM observatorio.quarantine_records GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()


def country_accuracy(conn) -> dict[str, object]:
    """Accuracy proxy: USGS `place` usually ends with the country/region name. When that suffix
    equals a catalog country name, the polygon assignment should agree with it."""
    catalog = get_catalog()
    by_name = {}
    import json as _json

    raw = _json.load(open(Path(__file__).resolve().parents[1] / "observatorio" / "data" / "paises.geojson", encoding="utf-8"))
    for f in raw["features"]:
        for key in ("NAME", "ADMIN", "NAME_LONG"):
            n = f["properties"].get(key)
            if n:
                by_name[n.lower()] = f["properties"]["ADM0_A3"]
    rows = conn.execute(
        "SELECT event_id, place, country_id FROM observatorio.historical_events WHERE place LIKE '%, %'"
    ).fetchall()
    checked = agree = 0
    disagreements = []
    import re

    far = 0
    for event_id, place, assigned in rows:
        expected = by_name.get(place.rsplit(", ", 1)[1].strip().lower())
        if expected is None:
            continue
        m = re.match(r"^(\d+(?:\.\d+)?) km ", place)
        if m is None or float(m.group(1)) > MAX_REFERENCE_KM:
            far += 1  # epicentre far from the reference town: it is legitimately offshore, not comparable
            continue
        checked += 1
        if assigned == expected:
            agree += 1
        elif len(disagreements) < 5:
            disagreements.append((event_id, place, assigned, expected))
    return {
        "far": far,
        "catalog_countries": len(catalog.countries),
        "checked": checked,
        "agree": agree,
        "rate": (agree / checked) if checked else None,
        "disagreements": disagreements,
    }


def samples(conn):
    return {
        "excluded": conn.execute(
            "SELECT event_id, reason, place FROM observatorio.poll_exclusions ORDER BY id DESC LIMIT 3"
        ).fetchall(),
        "quarantine": conn.execute(
            "SELECT kafka_topic, kafka_offset, rejection_reason, left(convert_from(raw_payload,'UTF8'), 80) "
            "FROM observatorio.quarantine_records ORDER BY id DESC LIMIT 3"
        ).fetchall(),
        "revised": conn.execute(
            "SELECT event_id, count(*) versions, min(mag), max(mag) FROM observatorio.event_versions "
            "GROUP BY 1 HAVING count(*)>1 ORDER BY 2 DESC LIMIT 3"
        ).fetchall(),
        "null_mag": conn.execute(
            f"SELECT event_id, place, mag FROM {CE} WHERE mag IS NULL LIMIT 3"
        ).fetchall(),
    }


def render(q, reasons, qreasons, acc, smp) -> str:
    v = lambda k: q[k][2]
    pct = lambda a, b: f"{(100 * a / b):.1f} %" if b else "ND"
    lines = ["# Calidad de datos", "", "_Generado por `backend/tools/quality.py`; cada cifra procede de la consulta indicada._", ""]
    lines += ["## Antes y después", "", "| Etapa | Medida | Valor |", "|---|---|---:|"]
    lines += [f"| Antes (feed bruto) | {q[k][0]} | {v(k)} |" for k in ("raw_polls", "raw_features", "raw_non_quake", "raw_distinct_versions", "raw_distinct_ids", "raw_null_mag")]
    lines += [f"| Después (PostgreSQL) | {q[k][0]} | {v(k)} |" for k in ("versions", "current_events", "quarantine")]
    lines += ["", f"Decisión: el feed repite cada evento en cada sondeo (≈{v('raw_features')} features para {v('raw_distinct_ids')} eventos distintos). "
              "Solo se publica la primera aparición de cada versión `(id, updated)`; solo `current_events` alimenta agregaciones.", ""]
    if reasons:
        lines += ["Descartes del productor por motivo (`poll_exclusions`):", ""] + [f"- `{r}`: {n}" for r, n in reasons] + [""]
    if qreasons:
        lines += ["Cuarentena por motivo:", ""] + [f"- `{r}`: {n}" for r, n in qreasons] + [""]

    def table(title, keys, note=""):
        out = [f"## {title}", "", "| Medida | Valor | Consulta |", "|---|---:|---|"]
        for k in keys:
            out.append(f"| {q[k][0]} | {v(k)} | `{q[k][1]}` |")
        return out + ([""] + [note] if note else []) + [""]

    ce = v("current_events")
    lines += table("1. Completitud", ["null_mag", "null_place", "null_depth", "null_country", "hist_total", "hist_null_mag", "hist_null_depth", "hist_null_country"],
                   f"Tiempo real: magnitud nula {pct(v('null_mag'), ce)}, sin país {pct(v('null_country'), ce)}. Histórico: magnitud nula {pct(v('hist_null_mag'), v('hist_total'))}, sin país {pct(v('hist_null_country'), v('hist_total'))}. "
                   "Una magnitud nula se conserva y se muestra «ND»; nunca se imputa 0.")
    lines += table("2. Unicidad", ["dup_versions", "dup_current", "multi_version"],
                   "La clave `(event_id, updated)` y el `ON CONFLICT` hacen imposibles los duplicados; los reenvíos idénticos se ignoran y los conflictos de carga distinta van a cuarentena.")
    lines += table("3. Validez", ["invalid_coords", "invalid_mag", "invalid_depth", "future_time", "non_quake_current"],
                   "La validación del consumidor rechaza lo inválido antes de persistir (cuarentena); aquí se comprueba que nada inválido llegó al estado actual.")
    lines += table("4. Consistencia", ["stale_current", "updated_before_time", "orphan_country", "ambiguous"],
                   "Una versión más antigua nunca sustituye a la actual (`WHERE EXCLUDED.updated > current.updated`).")
    lines += table("5. Oportunidad (timeliness)", ["lag_event_to_ingest_p50", "lag_event_to_ingest_p95", "lag_ingest_to_store_p95", "poll_latency_p50", "poll_latency_p95", "poll_failures"],
                   "El retraso evento → ingesta depende de cuándo USGS publica o revisa el evento (el feed es una ventana rodante de 24 h y la ingesta de un evento ocurre al aparecer su versión). El tramo ingesta → PostgreSQL incluye la espera en Kafka cuando el consumidor estuvo parado o reiniciándose, por eso su p95 es mayor que la mediana.")
    lines += ["## 6. Exactitud", "",
              f"Sin verdad terreno oficial, se usa un contraste independiente: el texto `place` de USGS termina casi siempre en el nombre del país. "
              f"`place` nombra el país del pueblo de referencia, que puede estar a cientos de km del epicentro; por eso solo se contrastan los eventos a ≤ {MAX_REFERENCE_KM} km del pueblo "
              f"(los {acc['far']} restantes con sufijo reconocible están lejos de la costa y no son comparables). "
              f"Sobre el histórico 2025, de los {acc['checked']} eventos comparables la asignación por polígono coincide en **{acc['agree']}** ({pct(acc['agree'], acc['checked'])}).", ""]
    if acc["disagreements"]:
        lines += ["Ejemplos de discrepancia (id, lugar, asignado, esperado):", ""] + [f"- `{a}` · {b} · {c} · {d}" for a, b, c, d in acc["disagreements"]] + [""]
    lines += ["La causa típica es la simplificación de costas del catálogo de baja resolución (ver `diccionario-datos.md`).", "", "## Registros de ejemplo", ""]
    for name, rows in smp.items():
        lines += [f"**{name}**", ""] + ([f"- `{r}`" for r in rows] or ["- (sin registros)"]) + [""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    with psycopg.connect(**postgres_connection_parameters(), connect_timeout=5) as conn:
        q = run_queries(conn)
        data = (q, exclusion_reasons(conn), quarantine_reasons(conn), country_accuracy(conn), samples(conn))
    if args.json:
        print(json.dumps({k: v[2] for k, v in q.items()}, indent=2, default=str))
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(render(*data))


if __name__ == "__main__":
    main()
