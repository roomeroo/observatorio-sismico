"""Complexity benchmark: dictionary vs sequential scan, with/without index, 3 input sizes.

    docker compose run --rm producer python tools/benchmark.py > docs/complejidad-resultados.md

Real rows come from `historical_events` (2025). Larger sizes REPLICATE them with ids
prefixed `synthetic-` and a `synthetic = TRUE` flag. Everything lives in the temporary
schema `bench` (dropped at the end), so synthetic rows never reach the analytic tables
used by the API, the dashboard or docs/analisis.md.
"""

import bisect
import io
import random
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from observatorio.database import postgres_connection_parameters  # noqa: E402

SIZES = [1, 10, 100]  # multiples of the real 2025 data set
SEED = 7


def timed(fn, reps=5):
    samples = []
    for _ in range(reps):
        t = time.perf_counter()
        result = fn()
        samples.append(time.perf_counter() - t)
    return statistics.median(samples), result


def load_real(conn):
    return conn.execute(
        "SELECT event_id, extract(epoch FROM time_utc)::bigint, mag, depth, country_id "
        "FROM observatorio.historical_events ORDER BY event_id"
    ).fetchall()


def build_rows(real, factor):
    rows = []
    for k in range(factor):
        for (eid, t, mag, depth, cid) in real:
            rows.append((eid if k == 0 else f"synthetic-{k}-{eid}", t, mag, depth, cid, k > 0))
    return rows


def py_structures(rows):
    tracemalloc.start()
    index = {r[0]: r for r in rows}
    _, peak_dict = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    tracemalloc.start()
    by_time = sorted(rows, key=lambda r: r[1])
    times = [r[1] for r in by_time]
    _, peak_sorted = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return index, by_time, times, peak_dict, peak_sorted


def sql_load(conn, table, rows, with_index):
    conn.execute(f"DROP TABLE IF EXISTS bench.{table}")
    conn.execute(
        f"CREATE TABLE bench.{table} (event_id TEXT, t BIGINT, mag DOUBLE PRECISION, depth DOUBLE PRECISION, "
        "country_id TEXT, synthetic BOOLEAN NOT NULL)"
    )
    buf = io.StringIO()
    for r in rows:
        buf.write("\t".join("\\N" if v is None else str(v) for v in (r[0], r[1], r[2], r[3], r[4], "t" if r[5] else "f")) + "\n")
    buf.seek(0)
    with conn.cursor().copy(f"COPY bench.{table} FROM STDIN") as cp:
        while chunk := buf.read(1 << 20):
            cp.write(chunk)
    if with_index:
        conn.execute(f"CREATE UNIQUE INDEX {table}_pk ON bench.{table}(event_id)")
        conn.execute(f"CREATE INDEX {table}_t ON bench.{table}(t)")
        conn.execute(f"CREATE INDEX {table}_c ON bench.{table}(country_id)")
    conn.execute(f"ANALYZE bench.{table}")


def sizes(conn, table):
    t, i = conn.execute(
        f"SELECT pg_relation_size('bench.{table}'), pg_indexes_size('bench.{table}')"
    ).fetchone()
    return t, i


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rnd = random.Random(SEED)
    with psycopg.connect(**postgres_connection_parameters(), autocommit=True) as conn:
        real = load_real(conn)
        if not real:
            raise SystemExit("historical_events is empty: run observatorio.historical first")
        conn.execute("DROP SCHEMA IF EXISTS bench CASCADE")
        conn.execute("CREATE SCHEMA bench")
        t_min, t_max = min(r[1] for r in real), max(r[1] for r in real)
        out = []
        for factor in SIZES:
            rows = build_rows(real, factor)
            n = len(rows)
            ids = [r[0] for r in rnd.sample(rows, 50)]
            day_start = t_min + (t_max - t_min) // 2
            day_end = day_start + 86400

            index, by_time, times, peak_dict, peak_sorted = py_structures(rows)

            # 1. point lookup
            dict_t, _ = timed(lambda: [index[i] for i in ids], reps=7)
            def scan_lookup():
                found = []
                for i in ids:
                    for r in rows:
                        if r[0] == i:
                            found.append(r)
                            break
                return found
            scan_t, _ = timed(scan_lookup, reps=3)

            # 2. range (one day) + country count
            def py_range_scan():
                return sum(1 for r in rows if day_start <= r[1] < day_end)
            def py_range_bisect():
                return bisect.bisect_left(times, day_end) - bisect.bisect_left(times, day_start)
            rs_t, rs_n = timed(py_range_scan)
            rb_t, rb_n = timed(py_range_bisect, reps=50)

            sql_load(conn, "plain", rows, with_index=False)
            sql_load(conn, "idx", rows, with_index=True)
            pt, pi = sizes(conn, "plain")
            it, ii = sizes(conn, "idx")

            def sql_lookup(table):
                def run():
                    for i in ids:
                        conn.execute(f"SELECT * FROM bench.{table} WHERE event_id = %s", (i,)).fetchone()
                return run
            sql_idx_t, _ = timed(sql_lookup("idx"), reps=5)
            sql_seq_t, _ = timed(sql_lookup("plain"), reps=2)

            def sql_range(table):
                return lambda: conn.execute(
                    f"SELECT count(*) FROM bench.{table} WHERE t >= %s AND t < %s", (day_start, day_end)
                ).fetchone()[0]
            rng_idx_t, rng_n = timed(sql_range("idx"))
            rng_seq_t, _ = timed(sql_range("plain"))

            def sql_group(table):
                return lambda: conn.execute(
                    f"SELECT country_id, count(*) FROM bench.{table} WHERE NOT synthetic OR synthetic GROUP BY 1"
                ).fetchall()
            grp_t, _ = timed(sql_group("idx"), reps=3)
            plan = conn.execute(f"EXPLAIN SELECT * FROM bench.idx WHERE event_id = %s", (ids[0],)).fetchall()
            plan_seq = conn.execute(f"EXPLAIN SELECT * FROM bench.plain WHERE event_id = %s", (ids[0],)).fetchall()
            real_rows = sum(1 for r in rows if not r[5])
            out.append(dict(
                n=n, real=real_rows, synthetic=n - real_rows,
                dict_us=dict_t / len(ids) * 1e6, scan_us=scan_t / len(ids) * 1e6,
                sql_idx_us=sql_idx_t / len(ids) * 1e6, sql_seq_us=sql_seq_t / len(ids) * 1e6,
                range_scan_ms=rs_t * 1e3, range_bisect_us=rb_t * 1e6, rng_idx_ms=rng_idx_t * 1e3, rng_seq_ms=rng_seq_t * 1e3,
                group_ms=grp_t * 1e3, range_n=rng_n, peak_dict_mb=peak_dict / 1e6, peak_sorted_mb=peak_sorted / 1e6,
                table_mb=pt / 1e6, index_mb=ii / 1e6, plan=plan[0][0], plan_seq=" / ".join(r[0].strip() for r in plan_seq[:3]),
            ))
            conn.execute("DROP TABLE bench.plain")
            conn.execute("DROP TABLE bench.idx")
            assert rs_n == rb_n == rng_n, (rs_n, rb_n, rng_n)  # all strategies agree
        conn.execute("DROP SCHEMA bench CASCADE")

    print("# Resultados del benchmark (generado por `tools/benchmark.py`)\n")
    print("Filas **sintéticas** (réplicas de los datos reales de 2025 con id `synthetic-k-…`) solo existen en el esquema temporal `bench`, "
          "que se elimina al terminar; no están en las tablas analíticas.\n")
    print("| n filas | reales | sintéticas |\n|---:|---:|---:|")
    for r in out:
        print(f"| {r['n']:,} | {r['real']:,} | {r['synthetic']:,} |")
    print("\n## Búsqueda por id (µs por consulta, mediana)\n")
    print("| n | dict Python O(1) | recorrido lista O(n) | PostgreSQL con índice | PostgreSQL sin índice (seq scan) |\n|---:|---:|---:|---:|---:|")
    for r in out:
        print(f"| {r['n']:,} | {r['dict_us']:.2f} | {r['scan_us']:,.0f} | {r['sql_idx_us']:,.0f} | {r['sql_seq_us']:,.0f} |")
    print("\n## Rango de un día (mismo resultado en las 4 estrategias)\n")
    print("| n | filas en el rango | lista O(n) (ms) | lista ordenada + bisect (µs) | PostgreSQL con índice (ms) | PostgreSQL sin índice (ms) | GROUP BY país (ms) |\n|---:|---:|---:|---:|---:|---:|---:|")
    for r in out:
        print(f"| {r['n']:,} | {r['range_n']} | {r['range_scan_ms']:.1f} | {r['range_bisect_us']:.1f} | {r['rng_idx_ms']:.2f} | {r['rng_seq_ms']:.1f} | {r['group_ms']:.1f} |")
    print("\n## Memoria y tamaño\n")
    print("| n | pico Python dict (MB) | pico Python lista ordenada (MB) | tabla PG (MB) | índices PG (MB) |\n|---:|---:|---:|---:|---:|")
    for r in out:
        print(f"| {r['n']:,} | {r['peak_dict_mb']:.1f} | {r['peak_sorted_mb']:.1f} | {r['table_mb']:.1f} | {r['index_mb']:.1f} |")
    print("\n## Planes de ejecución (último tamaño)\n")
    print(f"- con índice: `{out[-1]['plan']}`\n- sin índice: `{out[-1]['plan_seq']}`")


if __name__ == "__main__":
    main()
