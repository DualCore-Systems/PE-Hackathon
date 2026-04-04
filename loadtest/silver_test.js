import http from "k6/http";
import { check, sleep } from "k6";
import { Counter, Rate, Trend } from "k6/metrics";

const errorCount = new Counter("errors");
const errorRate = new Rate("error_rate");
const listLatency = new Trend("list_products_duration", true);
const detailLatency = new Trend("get_product_duration", true);

export const options = {
  // Ramp up to 200 VUs, hold for 1 min, then ramp down
  stages: [
    { duration: "10s", target: 200 },
    { duration: "60s", target: 200 },
    { duration: "10s", target: 0 },
  ],
  thresholds: {
    http_req_failed:   ["rate<0.05"],    // <5% errors
    http_req_duration: ["p(95)<3000"],   // p95 under 3 s (Silver SLO)
  },
};

const BASE_URL = "http://127.0.0.1:80";
const PRODUCT_IDS = Array.from({ length: 100 }, (_, i) => i + 1);

export default function () {
  if (Math.random() < 0.6) {
    const res = http.get(`${BASE_URL}/products`, {
      tags: { endpoint: "list_products" },
    });

    listLatency.add(res.timings.duration);

    const ok = check(res, {
      "GET /products → 200":        (r) => r.status === 200,
      "GET /products → has records": (r) => {
        try { return JSON.parse(r.body).length > 0; } catch { return false; }
      },
    });
    errorRate.add(ok ? 0 : 1);
    if (!ok) errorCount.add(1);
  } else {
    const id = PRODUCT_IDS[Math.floor(Math.random() * PRODUCT_IDS.length)];
    const res = http.get(`${BASE_URL}/products/${id}`, {
      tags: { endpoint: "get_product" },
    });

    detailLatency.add(res.timings.duration);

    const ok = check(res, {
      "GET /products/:id → 200":       (r) => r.status === 200,
      "GET /products/:id → correct id": (r) => {
        try { return JSON.parse(r.body).id === id; } catch { return false; }
      },
    });
    errorRate.add(ok ? 0 : 1);
    if (!ok) errorCount.add(1);
  }

  sleep(0.3);
}

export function handleSummary(data) {
  return { stdout: textSummary(data) };
}

function textSummary(data) {
  const m = data.metrics;

  const dur  = (k) => m.http_req_duration?.values?.[k]?.toFixed(2) ?? "N/A";
  const pct  = (v) => ((v ?? 0) * 100).toFixed(2);

  const p50  = dur("med");
  const p95  = dur("p(95)");
  const p99  = dur("p(99)");
  const avg  = dur("avg");
  const max  = dur("max");
  const rps  = m.http_reqs?.values?.rate?.toFixed(2) ?? "N/A";
  const tot  = m.http_reqs?.values?.count ?? 0;
  const fail = pct(m.http_req_failed?.values?.rate);

  const lP95 = m.list_products_duration?.values?.["p(95)"]?.toFixed(2) ?? "N/A";
  const lAvg = m.list_products_duration?.values?.avg?.toFixed(2) ?? "N/A";
  const dP95 = m.get_product_duration?.values?.["p(95)"]?.toFixed(2) ?? "N/A";
  const dAvg = m.get_product_duration?.values?.avg?.toFixed(2) ?? "N/A";

  const slo  = parseFloat(p95) < 3000 ? "✓ PASS" : "✗ FAIL";

  return `
================================================================================
  SILVER TIER LOAD TEST — RESULTS
  200 VUs × 60s sustained | Nginx → 3× Flask (gunicorn) → PostgreSQL
================================================================================

  OVERALL HTTP DURATION
  ─────────────────────────────────────
  avg         : ${avg} ms
  p50 (median): ${p50} ms
  p95         : ${p95} ms   ← Silver SLO target (<3000 ms)  ${slo}
  p99         : ${p99} ms
  max         : ${max} ms

  THROUGHPUT & ERRORS
  ─────────────────────────────────────
  total reqs  : ${tot}
  req/s (RPS) : ${rps}
  error rate  : ${fail}%

  PER-ENDPOINT BREAKDOWN
  ─────────────────────────────────────
  GET /products      avg=${lAvg} ms   p95=${lP95} ms
  GET /products/:id  avg=${dAvg} ms   p95=${dP95} ms

================================================================================
`;
}
