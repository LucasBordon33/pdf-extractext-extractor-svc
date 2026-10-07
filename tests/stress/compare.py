#!/usr/bin/env python3
"""Comparador de resultados de carga (Issue 33, Parte 2)."""

import datetime
import json
import os
import subprocess
import sys

RESULTS_DIR = os.path.join("tests", "stress", "results")
K6_SUMMARY = os.path.join(RESULTS_DIR, "k6_summary.json")
VEGETA_REPORT = os.path.join(RESULTS_DIR, "reporte.json")
SUMMARY_OUT = os.path.join(RESULTS_DIR, "summary.json")

# --- Umbrales del profesor (latencias en ms; la tasa de error es EL criterio) -
PROF_MAX_P50_MS = 1880.0
PROF_MAX_P90_MS = 7830.0
PROF_MAX_P95_MS = 8800.0
PROF_MAX_P99_MS = 10000.0
PROF_MAX_MAX_MS = 13940.0
PROF_MAX_ERROR_RATE = 0.0
NS_PER_MS = 1_000_000.0


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def load_json(path):
    if not os.path.exists(path):
        fail(f"no existe {path}; correr bash scripts/run_stress.sh primero")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# --- Extraccion de metricas ---------------------------------------------------

def k6_values(summary, metric):
    metrics = summary.get("metrics")
    if not isinstance(metrics, dict) or metric not in metrics:
        return {} # Evitar que crashee si la metrica esta vacia
    entry = metrics[metric]
    values = entry.get("values") if isinstance(entry, dict) else None
    return values if isinstance(values, dict) else entry


def extract_k6(summary):
    values = k6_values(summary, "http_req_duration")
    failed = k6_values(summary, "http_req_failed")
    reqs = k6_values(summary, "http_reqs")
    
    # Correccion 1: En tu k6 la mediana se llama "p(50)", no "med".
    p50 = values.get("p(50)", values.get("med", 0.0))
    
    # Correccion 2: Si el error es 0, a veces se usa "value" en vez de "rate", nunca fallback a 1.0.
    error_rate = failed.get("rate", failed.get("value", 0.0))
    
    # Correccion 3: El count de requests esta en http_reqs
    count = reqs.get("count", 0)

    return {
        "p50_ms": float(p50),
        "p90_ms": float(values.get("p(90)", 0.0)),
        "p95_ms": float(values.get("p(95)", 0.0)),
        "max_ms": float(values.get("max", 0.0)),
        "error_rate": float(error_rate),
        "requests": int(float(count)),
    }


def extract_vegeta(reporte):
    latencies = reporte.get("latencies") or {}
    status_codes = reporte.get("status_codes") or {}
    total = sum(int(v) for v in status_codes.values())
    ok = int(status_codes.get("200", 0))
    if total > 0:
        error_rate = 1.0 - (ok / total)
    else:
        error_rate = 1.0 - float(reporte.get("ratio", 0.0))
    return {
        "p50_ms": float(latencies.get("50th", 0.0)) / NS_PER_MS,
        "p90_ms": float(latencies.get("90th", 0.0)) / NS_PER_MS,
        "p95_ms": float(latencies.get("95th", 0.0)) / NS_PER_MS,
        "p99_ms": float(latencies.get("99th", 0.0)) / NS_PER_MS,
        "max_ms": float(latencies.get("max", 0.0)) / NS_PER_MS,
        "error_rate": error_rate,
        "requests": total,
        "throughput_rps": float(reporte.get("throughput", 0.0)),
    }


# --- Tabla Markdown -----------------------------------------------------------

def row(metrica, profesor, nuestro):
    delta = nuestro - profesor
    signo = "+" if delta > 0 else ""
    return f"| {metrica} | {profesor:.2f} | {nuestro:.2f} | {signo}{delta:.2f} |"


def print_table(k6, vegeta):
    print("\n| Metrica | Profesor | Nuestro | Delta |")
    print("|---|---|---|---|")
    for tool, m in (("k6", k6), ("vegeta", vegeta)):
        print(row(f"{tool} error rate (%)", PROF_MAX_ERROR_RATE, m["error_rate"] * 100))
        print(row(f"{tool} p50 (ms)", PROF_MAX_P50_MS, m["p50_ms"]))
        print(row(f"{tool} p90 (ms)", PROF_MAX_P90_MS, m["p90_ms"]))
        print(row(f"{tool} p95 (ms)", PROF_MAX_P95_MS, m["p95_ms"]))
        if "p99_ms" in m:
            print(row(f"{tool} p99 (ms)", PROF_MAX_P99_MS, m["p99_ms"]))
        print(row(f"{tool} max (ms)", PROF_MAX_MAX_MS, m["max_ms"]))


# --- summary.json con el entorno real ----------------------------------------

def run_cmd(cmd):
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15, check=False
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def build_summary(k6, vegeta, passed):
    return {
        "fecha": datetime.datetime.now().isoformat(timespec="seconds"),
        "git_commit": run_cmd(["git", "rev-parse", "HEAD"]),
        "python_version": sys.version.split()[0],
        "docker_version": run_cmd(["docker", "--version"]),
        "entorno": {
            "UVICORN_WORKERS": os.environ.get("UVICORN_WORKERS"),
            "REPLICAS": os.environ.get("REPLICAS"),
        },
        "criterio_correccion": "0% de error en k6 y Vegeta",
        "veredito": "PASS" if passed else "FAIL",
        "k6": k6,
        "vegeta": vegeta,
        "umbrales_profesor": {
            "error_rate": PROF_MAX_ERROR_RATE,
            "p50_ms": PROF_MAX_P50_MS,
            "p90_ms": PROF_MAX_P90_MS,
            "p95_ms": PROF_MAX_P95_MS,
            "p99_ms": PROF_MAX_P99_MS,
            "max_ms": PROF_MAX_MAX_MS,
        },
    }


def main():
    k6 = extract_k6(load_json(K6_SUMMARY))
    vegeta = extract_vegeta(load_json(VEGETA_REPORT))

    print_table(k6, vegeta)

    k6_ok = k6["error_rate"] == PROF_MAX_ERROR_RATE
    vegeta_ok = vegeta["error_rate"] == PROF_MAX_ERROR_RATE
    passed = k6_ok and vegeta_ok

    print()
    print(f"k6:     error rate {k6['error_rate'] * 100:.2f}% "
          f"{'OK' if k6_ok else 'FAIL'} ({k6['requests']} requests)")
    print(f"vegeta: error rate {vegeta['error_rate'] * 100:.2f}% "
          f"{'OK' if vegeta_ok else 'FAIL'} ({vegeta['requests']} requests)")

    summary = build_summary(k6, vegeta, passed)
    with open(SUMMARY_OUT, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
    print(f"\nsummary escrito en {SUMMARY_OUT}")
    print(f"VEREDICTO: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())