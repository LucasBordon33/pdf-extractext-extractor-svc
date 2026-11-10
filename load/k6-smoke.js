// Smoke de carga para CI (NO es la prueba de stress del TP):
// 10 VUs durante 10 s contra POST /api/v1/extract. Verifica que el contrato
// {content, page_count} se sostiene bajo concurrencia sin costar
// minutos en cada PR. La prueba completa corre aparte.
//
// Uso local:  k6 run -e BASE_URL=https://localhost:443 load/k6-smoke.js
// Con cert autofirmado:  K6_INSECURE_SKIP_TLS_VERIFY=true k6 run load/k6-smoke.js

import http from "k6/http";
import { check } from "k6";

export const options = {
  vus: 10,
  duration: "10s",
  thresholds: {
    // El contrato no se degrada bajo concurrencia ni hay timeouts.
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<30000"],
  },
  // Traefik en websecure usa TLS (posiblemente cert autofirmado en dev);
  // saltarse validación de certificado para que k6 no falle el handshake.
  // Forzar también con: K6_INSECURE_SKIP_TLS_VERIFY=true k6 run ...
  tls: {
    insecureSkipTLSVerify: true,
  },
};

// Mismo PDF que el test de contrato (tests/contract/test_tp_contract.py).
const pdf = open("../tests/fixtures/official_sample.pdf", "b");

const BASE_URL = __ENV.BASE_URL || "https://localhost:443";

export default function () {
  const response = http.post(`${BASE_URL}/api/v1/extract`, pdf, {
    headers: { "Content-Type": "application/pdf" },
    timeout: "30s",
  });

  check(response, {
    "status 200": (r) => r.status === 200,
    "contrato exacto {content, page_count}": (r) => {
      if (r.status !== 200) return false;
      const body = r.json();
      return (
        Object.keys(body).length === 2 &&
        typeof body.content === "string" &&
        body.content.length > 0 &&
        typeof body.page_count === "number"
      );
    },
  });
}
