/**
 * Issue 31 — Test de Spike (k6)
 * ------------------------------
 * Escenario: 0 -> 100 VUs en 10 s, sostener 100 VUs por 20 s, bajar a 0 en 10 s.
 * Mide el comportamiento del extractor bajo una subida abrupta de carga a
 * traves del reverse proxy (Traefik) que balancea las 5 replicas.
 *
 * Decisiones de disenio:
 * - SharedArray: los bytes de los PDFs se cargan UNA SOLA VEZ en el init
 *   context y se comparten entre los 100 VUs. Cargarlos por VU/iteracion
 *   meteria un cuello de botella en el cliente (FS+I/O) e invalidaria la
 *   medicion.
 * - formParams con http.file(payload, name): k6 genera el boundary del
 *   multipart y setea Content-Type. Payloads pre-armados romperian si el
 *   boundary choca con el contenido binario.
 * - http.setResponseCallback(http.expectedStatuses(200)): TODO status != 200
 *   (incluidos 429/503 de admision) cuenta como fallo en http_req_failed y
 *   dispara el threshold rate==0. Es la forma estricta pedida por la issue.
 * - discardResponseBodies: false — necesitamos el body para validar el
 *   contrato JSON (content no vacio, page_count > 0).
 *
 * Ejecucion:
 *   k6 run tests/stress/spike.js
 *   k6 run -e BASE_URL=http://localhost:8080 -e MAX_P95=9000 tests/stress/spike.js
 */

import http from 'k6/http';
import { check } from 'k6';

// --- Escenario y opciones ---------------------------------------------------
const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080'; // proxy, NO una replica
const EXTRACT_PATH = __ENV.EXTRACT_PATH || '/extract';

export const options = {
  stages: [
    { duration: '10s', target: 100 }, // ramp-up abrupto al pico de 100 VUs
    { duration: '20s', target: 100 }, // meseta en el pico
    { duration: '10s', target: 0 },   // ramp-down
  ],
  discardResponseBodies: false,
  // p50/p90/p95/max de tendencia + rate (throughput) en el resumen
  summaryTrendStats: ['min', 'avg', 'p(50)', 'p(90)', 'p(95)', 'max', 'count'],
  thresholds: {
    // Con expectedStatuses(200), cualquier 429/503/no-200 suma a este rate
    http_req_failed: ['rate==0'],
    checks: ['rate>0.99'],
    http_req_duration: [
      `p(50)<${__ENV.MAX_P50 || 1880}`,
      `p(90)<${__ENV.MAX_P90 || 7830}`,
      `p(95)<${__ENV.MAX_P95 || 8800}`,
      `max<${__ENV.MAX_MAX || 13940}`,
    ],
  },
};

// Validacion estricta: solo 200 pasa; 429/503/5xx cuentan como fallo
http.setResponseCallback(http.expectedStatuses(200));

// --- Dataset (init context: memoria compartida automáticamente por k6) -----------
const PDF_FILES = (__ENV.PDF_FILES || 'prueba.pdf')
  .split(',')
  .map((name) => name.trim())
  .filter((name) => name.length > 0);

const documents = PDF_FILES.map((name) => {
  // open() en el init context asegura que los bytes se carguen en RAM una sola vez
  const bytes = open(`pdfs/${name}`, 'b'); 
  return { name, bytes };
});

// --- Iteracion por VU -------------------------------------------------------
export default function () {
  // Rotacion aleatoria del dataset para distribuir el tipo de carga
  const doc = documents[Math.floor(Math.random() * documents.length)];

  const res = http.post(
    `${BASE_URL}${EXTRACT_PATH}`,
    {
      // k6 calcula el boundary y setea el Content-Type multipart correcto
      file: http.file(doc.bytes, doc.name, 'application/pdf'),
    },
    { tags: { name: 'spike-extract' } }
  );

  // Checksum de contrato sobre el JSON de respuesta
  check(res, {
    'status es 200': (r) => r.status === 200,
    'content no vacio': (r) => {
      try {
        const content = r.json('content');
        return typeof content === 'string' && content.length > 0;
      } catch (e) {
        return false;
      }
    },
    'page_count > 0': (r) => {
      try {
        return Number(r.json('page_count')) > 0;
      } catch (e) {
        return false;
      }
    },
  });
}
