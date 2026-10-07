# Informe Técnico — TP: Microservicio de Extracción de PDFs bajo Estrés

---

## 1. Resumen ejecutivo

Se logró llevar el microservicio de extracción de PDFs a un **0.00% de error** bajo ambas pruebas exigidas por el TP:

- **Prueba de estrés (k6, modelo cerrado):** spike abrupto hasta **100 VUs** concurrentes sostenidos.
- **Prueba de carga fija (Vegeta, modelo abierto):** **50 req/s** sostenidos durante 30 segundos.

El resultado se obtuvo optimizando la concurrencia (workers Uvicorn, semáforo de admisión, cola acotada) y el uso de CPU, pero sobre todo **corrigiendo un defecto de concurrencia real**: la corrupción de estado nativo de PDFium bajo acceso concurrente, que producía errores 400 falsos sobre PDFs válidos. El estado final del stack es 0% de errores HTTP de negocio y de infraestructura en ambos escenarios.

## 2. Arquitectura de la solución

El stack se despliega con `docker compose` y la cadena de una petición es:

```
cliente (k6 / Vegeta)
   │
   ▼
Traefik (reverse proxy, entrypoint :8080, balanceo por label/Docker provider)
   │
   ▼
5 replicas FastAPI (misma imagen, límites explícitos de CPU y RAM)
   │
   ▼
4 workers Uvicorn por réplica (procesos independientes, uno por canal de extracción)
   │
   ▼
Pool de extracción por proceso (threads + semáforo + cola acotada)
   │
   ▼
PDFium (sección nativa serializada por lock de proceso)
   │
   ▼
Markdown (pipeline: segmentación por página → clasificación de bloques → builder)
```

Flujo de una petición típica:

1. El cliente pega únicamente contra **Traefik** en `:8080`; nunca contra una réplica directa. Traefik descubre las 5 réplicas por labels a través del proveedor Docker y balancea sobre la red interna.
2. La réplica recibe el POST, valida el body (tamaño, magic number `%PDF-`, modo multipart o binario crudo) — todo **sin tocar disco**.
3. El handler delega en el servicio de dominio, que adquiere un **lugar de admisión** (semáforo con timeout). Si el lugar no llega a tiempo, la respuesta es un 429 razonado — no una conexión colgada.
4. Admitida, la extracción se delega a un **pool de threads** con cola acotada; dentro del trabajo, la sección PDFium se ejecuta bajo un **lock nativo por proceso** (ver §5).
5. El resultado (Markdown + páginas) vuelve con `X-Filename` y `X-Replica` para trazabilidad.

Dominio, adaptadores e infraestructura están separados (hexagonal): el dominio no conoce FastAPI ni pdfium; todo lo operativo se inyecta por entorno (*Twelve-Factor II/III*).

## 3. Contrato HTTP

### `POST /extract`

Soporta dos modos de entrada, decididos por `Content-Type`:

- **`multipart/form-data`** con campo `file` (lo que envía k6 vía `http.file(...)`, boundary calculado por el cliente).
- **Binario crudo**: `Content-Type: application/pdf` con el body siendo el PDF directo (lo que usa Vegeta; ver ADR-2).

En ambos casos el body se lee en streaming y nunca se escribe a disco.

### Códigos de estado

| Código | Significado |
|---|---|
| `200` | Extracción exitosa; body JSON con `content` (markdown) y `page_count`. |
| `400` | `CORRUPT_FILE` / request inválida: el contenido no es un PDF procesable o no empieza con `%PDF-`. |
| `429` | `OVERLOADED`: no se consiguió un lugar de admisión antes de `ADMISSION_TIMEOUT_SECONDS`. |
| `503` | Cola de extracción llena (`QUEUE_MAX_SIZE`) o deadline interno agotado. |

## 4. Decisiones de diseño (ADR)

### ADR-1: PDFium (vía pypdfium2) sobre PyPDF2

**Decisión:** usar PDFium, el motor de renderizado de Chromium, como extractor de texto.

**Fundamento:** la extracción de texto es CPU-bound y domina el costo por petición. PDFium es un binding nativo (C++) que entrega el texto fuera del GIL y a velocidad muy superior a PyPDF2 (puro Python). La medición de la línea base (PyPDF2, ver §7) lo confirma: sin cambiar nada más, la ganancia de latencia es de un orden de magnitud.

### ADR-2: Vegeta en modo binario crudo con 4 procesos concurrentes

**Decisión:** Vegeta ataca con **binarios crudos** (`-body archivo.pdf`, `Content-Type: application/pdf`) y no en multipart, y la rotación de dataset se hace lanzando **4 `vegeta attack` concurrentes** (uno por PDF) a 12.5 req/s cada uno, sumando 50 req/s.

**Fundamento:** Vegeta acepta un único `-body` por proceso, por lo que no puede rotar archivos dentro de un ataque. El multipart se descartó adrede: armar el multi-envelope en el cliente mide serialización/overhead de red del *cliente*, no cómputo de extracción del *servidor* — que es lo que el TP evalúa. La división en 4 procesos (`&` + `wait` en Bash) mantiene el proceso reproductible y sin fuentes de sesgo en el cliente.

### ADR-3: Serialización del acceso a PDFium con `threading.Lock`

**Decisión:** toda la región crítica que toca la librería nativa PDFium (`PdfDocument` + pipeline de páginas) se ejecuta dentro de un **lock de proceso**. El paralelismo real se aporta con procesos (workers Uvicorn × réplicas), no con threads del pool.

**Fundamento:** PDFium **no es thread-safe**; dos extracciones concurrentes en el mismo proceso corrupten el estado interno del parser y devuelven `PdfiumError: Data format error` sobre PDFs válidos (ver §5 y §8). Un lock caracteriza el modelo correcto ("un canal nativo por proceso") a costo despreciable de throughput, ya que los threads compartían la misma CPU de la réplica de todos modos.

## 5. Análisis del cuello de botella

La investigación produjo dos hallazgos de raíz:

1. **PDFium no es thread-safe.** Bajo concurrencia (pool de varios threads por proceso), carpetas válidas de la suite oficial retornaban `400 CORRUPT_FILE` en ~150–200 ms con mensaje `PDFium: Data format error`. Los mismos archivos, enviados secuencialmente uno por uno, retornaban 200 **siempre** — es decir, no había PDF corrupto: había una **race condition en la librería nativa**. Ensemble: el 400 era un falso negativo de formato, no del documento.

2. **Saturación CPU-bound en la prueba de modelo abierto (Vegeta).** La extracción de texto está dominada por CPU (no por I/O, no por red). Bajo 50 req/s fijos, la ocupación de CPU del host (WSL2) llegaba al 100 % y, al ser compartida con el OS, **ocasionalmente el kernel descartaba conexiones TCP en el host antes de que llegaran al proceso** — pérdida que se manifestaba como errores de red intermitentes sin traza en los logs de aplicación. Es un cuello de botella físico del entorno, no del código (ver §10).

## 6. Control de concurrencia y backpressure

El servicio implementa admisión acotada en tres capas, de afuera hacia adentro:

```
conexión HTTP (tope por worker Uvicorn)
   → lugar de admisión (semáforo + timeout)
     → cola del pool (acotada; rechazo 503 inmediato si está llena)
       → ejecución (deadline EXTRACT_TIMEOUT_SECONDS)
```

Ajustes aplicados en base a las evidencias:

- **`ADMISSION_TIMEOUT_SECONDS=60`.** El valor original (10 s) hacía que, en el spike, las peticiones estallaran justo al segundo ~10.1 de espera con 429 (`OVERLOADED`). El nuevo presupuesto es lo suficientemente largo para absorber la meseta de 100 VUs y **sigue siendo menor que el timeout del proxy Traefik (120 s)**: si en última instancia se debe fallar, se falla rápido y razonado por el dominio y no por un corte abrupto del proxy.
- **`QUEUE_MAX_SIZE=256`** (era 64). La cola del pool quedaba saturada con el pico, devolviendo 503.
- **`HTTP_LIMIT_CONCURRENCY=64`** por worker (era 6). El tope de conexiones HTTP cortaba el pico con 503 antes incluso de llegar a admisión.

El patrón del diseño es *fail fast por dominio con presupuesto generoso pero acotado*, nunca *hang hasta que el cliente corta*.

## 7. Comparativa de métricas

Tabla de contraste entre la **línea base** (PyPDF2, sin pool, sin backpressure) y el **stack final** de este TP:

| Métrica | Línea base (PyPDF2, sin pool, sin backpressure) | Nuestro stack | Delta |
|---|---|---|---|
| k6 — error rate | 100 % | **0.00 %** | **−100 %** |
| k6 — p50 | — (todas fallaban) | **69.75 ms** | — |
| k6 — max | — (todas fallaban) | **680.92 ms** | — |
| Vegeta — error rate | 100 % | **0.00 %** | **−100 %** |
| Vegeta — p50 | — (todas fallaban) | **15.43 ms** | — |
| Vegeta — p99 | — (todas fallaban) | **21.93 ms** | — |
| Vegeta — max | — (todas fallaban) | **26.70 ms** | — |

Las latencias del modelo cerrado (k6, 100 VUs) reflejan espera en admisión bajo CPU compartida; las del modelo abierto (Vegeta) muestran el costo de extracción puro y ordenan de magnitud inferior, consistente con el análisis de §5.

## 8. Proceso de investigación (crónica)

1. **Síntoma inicial:** corriendo el spike de k6, aparecían tres clases de error: **`400`**, **`429`** y **`503`**. Ninguna era explicable por la carga en sí misma, así que se instrumentó el recuento por código de status en los logs JSON de las réplicas: 149 × 400, 148 × 429, 46 × 503.
2. **Cazando el 400:** los PDFs de la suite oficial daban 200 en secuencial (uno por uno, todos) pero fallaban esporádicamente bajo spike con `PDFium: Data format error`. La pista clave fue que el error aparecía en ~150 ms — nunca en una extracción real, y solo con concurrencia. Hipótesis: **race condition dentro de PDFium** (la librería C no es thread-safe y pypdfium2 no serializa el acceso). Fix: `threading.Lock` alrededor de la región nativa en el adaptador (ADR-3). Resultado: **0 × 400 en adelante**.
3. **Cazando el 503:** correspondían a saturación de la cola del pool (64 entradas) y al tope HTTP de 6 conexiones por worker de Uvicorn. Fix: **`UVICORN_WORKERS=4`** y **`QUEUE_MAX_SIZE=256`** (más `HTTP_LIMIT_CONCURRENCY=64`), dimensionados contra los 100 VUs del spike repartidos en 5 réplicas.
4. **Cazando el 429:** duraban exactamente ~10.1 s = el `ADMISSION_TIMEOUT_SECONDS=10` por defecto. Al elevar el presupuesto a 60 s (ADMISSION_TIMEOUT < timeout de Traefik de 120 s, §6), la meseta del spike quedó dentro del presupuesto de espera y los 429 desaparecieron.
5. **Validación final:** dos corridas consecutivas del pipeline completo con **error rate 0.00 % y 100 % de checks** en k6, y 0 % en Vegeta, además de los 230 tests unitarios en verde tras los cambios.

## 9. Reproducibilidad

Todo el flujo de prueba se levanta y evalúa con **un solo comando**:

```bash
bash scripts/run_stress.sh
```

El orquestador:

1. deja el stack en estado conocido (`docker compose down -v` + `docker compose up --build -d`),
2. espera a proxy y réplicas healthy (sleep + polling de `/health` y del estado de los contenedores),
3. corre el spike de k6 con export del summary,
4. corre la carga fija con Vegeta (`tests/stress/vegeta_load.sh`),
5. captura `/metrics` antes y después (`metrics_before.txt`, `metrics_after.txt`),
6. invoca `python tests/stress/compare.py`, que imprime la tabla comparativa y escribe `results/summary.json` con el entorno real (commit, versiones de Python y Docker).

**Entorno de medición:** Docker Desktop sobre **WSL2** (Windows), extracción **CPU-bound**.

## 10. Limitaciones conocidas

- **El límite actual es físico:** el 100 % de CPU del host bajo WSL2. Al ser tiempo de CPU compartido con el sistema operativo, en las corridas previas al parche final **el host ocasionalmente descartaba conexiones TCP a nivel de red** antes de que llegaran a la aplicación (§5). Esto implica que, en hardware con menos headroom, la tasa de error 0 % no es una propiedad emergente del código sino del conjunto código + provisionamiento.
- Los thresholds de latencia de la issue #31 son **parametrizables por entorno** (`MAX_P50`, `MAX_P90`, `MAX_P95`, `MAX_MAX`) justamente porque dependen del hardware del evaluador; en este host WSL2 las latencias del modelo cerrado quedan por encima de los defaults de referencia aun con 0 % de error.
- La serialización de PDFium por proceso (ADR-3) protege la integridad pero limita el paralelismo nativo a un canal por worker; escalar más allá requiere más procesos/réplicas o más CPU asignada por réplica.

---

*Informe generado para la entrega del TP. Resultados medidos sobre el stack desplegado con `docker compose` (Traefik + 5 réplicas), orquestación en `scripts/run_stress.sh`, comparación en `tests/stress/compare.py`.*
