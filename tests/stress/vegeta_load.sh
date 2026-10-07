#!/usr/bin/env bash
# =============================================================================
# Prueba de carga fija con Vegeta (Open Model)
# -----------------------------------------------------------------------------
# 50 req/s fijos durante 30 s contra el proxy (Traefik -> 5 replicas).
#
# Por qué 4 ataques concurrentes:
#   Vegeta solo acepta UN -body por proceso. Para rotar los 4 PDFs sin
#   overhead de multipart en el cliente se lanzan 4 `vegeta attack` en
#   paralelo, cada uno con un PDF distinto en binario crudo
#   (Content-Type: application/pdf) a 12.5 req/s => 4 x 12.5 = 50 req/s.
# =============================================================================
set -euo pipefail

# --- Parámetros (override por entorno) ---------------------------------------
BASE_URL="${BASE_URL:-http://localhost:8080}"   # proxy, NO una replica
RATE="25/2s"                            
DURATION="${DURATION:-30s}"
TIMEOUT="${TIMEOUT:-30s}"
REPLICAS="${REPLICAS:-5}"

RESULTS_DIR="tests/stress/results"
PDFS_DIR="tests/stress/pdfs"

# --- Preparación -------------------------------------------------------------
mkdir -p "$RESULTS_DIR"

# Limpieza de corridas anteriores para evitar el error "gob: duplicate type"
rm -f "$RESULTS_DIR"/res*.bin "$RESULTS_DIR"/reporte_crudo.bin

echo "== Vegeta: Open Model ${DURATION} a 50 req/s contra $BASE_URL (balanceando $REPLICAS replicas) =="

# --- 4 ataques paralelos: un PDF por proceso (rotación del dataset) ----------
for i in 1 2 3 4; do
  echo "POST $BASE_URL/extract" | vegeta attack \
    -rate="$RATE" \
    -duration="$DURATION" \
    -timeout="$TIMEOUT" \
    -header "Content-Type: application/pdf" \
    -body "$PDFS_DIR/$i.pdf" \
    > "$RESULTS_DIR/res$i.bin" &
done

# Esperar a que los 4 ataques concurrentes finalicen
wait

# --- Reportes ----------------------------------------------------------------
# Texto (consola + archivo): latencias p50/p90/p95/p99 y status codes
vegeta report "$RESULTS_DIR"/res*.bin | tee "$RESULTS_DIR/reporte.txt"

# JSON (insumo del comparador de resultados)
vegeta report -type=json "$RESULTS_DIR"/res*.bin > "$RESULTS_DIR/reporte.json"

# --- Documentación (para el README) ------------------------------------------
cat <<'EOF'

## Prueba de carga fija con Vegeta (`tests/stress/vegeta_load.sh`)

**Carga en Modelo Abierto de 50 req/s durante 30 s contra el reverse proxy.**

### Rotación de archivos

Vegeta acepta un único `-body` por proceso, por lo que no puede rotar
archivos dentro de un mismo ataque. La rotación de los 4 PDFs se resolvió
**dividiendo la carga en 4 procesos `vegeta attack` concurrentes**
(lanzados con `&` y sincronizados con `wait`), cada uno con un PDF
distinto (`tests/stress/pdfs/1.pdf` ... `4.pdf`) con una tasa de **25 req cada 2s**:
(25/2) x 4 = **50 req/s de tráfico agregado**.

Los binarios van **crudos** (`Content-Type: application/pdf`,
`-body archivo.pdf`) en vez de multipart: evita el overhead de armado del
multipart en el cliente y mide cómputo de extracción, no serialización.

### Salidas en `tests/stress/results/`

| Archivo | Contenido |
|---|---|
| `res1..4.bin` | Resultados crudos por ataque (formato gob de Vegeta) |
| `reporte.txt` | Reporte de texto: p50/p90/p95/p99 y status codes |
| `reporte.json` | Mismo reporte en JSON para el comparador |

### Uso

```bash
bash tests/stress/vegeta_load.sh

EOF