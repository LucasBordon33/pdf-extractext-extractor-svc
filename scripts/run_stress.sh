#!/usr/bin/env bash
# =============================================================================
# Orquestador de pruebas de carga (Issue 33)
#
# Pipeline:
#   1. Estado conocido: `docker compose down -v` + `up --build -d`
#   2. Espera ejecutiva hasta que el proxy y las replicas esten healthy
#   3. Snapshot de /metrics (before)
#   4. Test de spike (k6) con export del resumen a JSON
#   5. Carga fija (Vegeta) via tests/stress/vegeta_load.sh
#   6. Snapshot de /metrics (after)
#   7. Comparador: python tests/stress/compare.py (define el exit code)
#
# Uso:  bash scripts/run_stress.sh
# =============================================================================
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
RESULTS_DIR="tests/stress/results"
PDF_FILES="${PDF_FILES:-prueba.pdf}"
READY_ATTEMPTS="${READY_ATTEMPTS:-60}"   # ~1 max esperando arranque (1s x intento)

mkdir -p "$RESULTS_DIR"

# --- 1) Estado conocido del stack --------------------------------------------
echo "== Reset del stack: down -v =="
docker compose down -v
echo "== Rebuild y levantado: up --build -d =="
docker compose up --build -d

# --- 2) Espera hasta healthy --------------------------------------------------
# sleep inicial: cubre el start_period de los healthchecks
echo "== Warm-up inicial (sleep 10) =="
sleep 10
echo "== Esperando proxy y replicas healthy (max ${READY_ATTEMPTS}s) =="
ready=0
for i in $(seq 1 "$READY_ATTEMPTS"); do
  health_ok=$(curl -fs -o /dev/null -w "%{http_code}" "$BASE_URL/health" || true)
  containers=$(docker compose ps --all --format "{{.Status}}" 2>/dev/null \
    | grep -c "(healthy)" || true)
  total=$(docker compose ps --all --format "{{.Status}}" 2>/dev/null | wc -l)
  if [ "$health_ok" = "200" ] && [ "$containers" -eq "$total" ] && [ "$total" -ge 6 ]; then
    ready=1
    echo "   listo tras ${i}s extra: $containers/$total healthy, proxy 200"
    break
  fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  echo "ERROR: el stack no quedo healthy a tiempo" >&2
  docker compose ps
  exit 1
fi

# --- 3) Snapshot de metricas (before) ----------------------------------------
if curl -fs -o "$RESULTS_DIR/metrics_before.txt" "$BASE_URL/metrics"; then
  echo "== /metrics guardado en $RESULTS_DIR/metrics_before.txt =="
else
  echo "WARN: /metrics no expuesto; se omite el snapshot before" >&2
fi

# --- 4) Test de spike (k6) ----------------------------------------------------
echo "== k6: spike 100 VUs =="
k6_code=0
k6 run -e PDF_FILES="$PDF_FILES" \
  --summary-export="$RESULTS_DIR/k6_summary.json" \
  tests/stress/spike.js || k6_code=$?
echo "   k6 exit code: $k6_code"

# --- 5) Carga fija (Vegeta) ---------------------------------------------------
echo "== Vegeta: carga fija 50 req/s =="
bash tests/stress/vegeta_load.sh

# --- 6) Snapshot de metricas (after) -----------------------------------------
if curl -fs -o "$RESULTS_DIR/metrics_after.txt" "$BASE_URL/metrics"; then
  echo "== /metrics guardado en $RESULTS_DIR/metrics_after.txt =="
else
  echo "WARN: /metrics no expuesto; se omite el snapshot after" >&2
fi

# --- 7) Comparador (define el exit code del orquestador) ----------------------
echo "== Comparador de resultados =="
uv run python tests/stress/compare.py
exit_code=$?
echo "== Orquestador finalizado (exit $exit_code) =="
exit $exit_code
