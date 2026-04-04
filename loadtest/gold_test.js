import http from "k6/http";
import { check, sleep } from "k6";
import { Counter, Rate, Trend } from "k6/metrics";

const errorCount   = new Counter("errors");
const errorRate    = new Rate("error_rate");
const cacheHitRate = new Rate("cache_hit_rate");
const listLatency  = new Trend("list_products_duration", true);
const detailLatency = new Trend("get_product_duration", true);

export const options = {
  stages: [
    { duration: "15s", target: 500 },  // ramp up
    { duration: "120s", target: 500 }, // sustained load
    { duration: "15s", target: 0 },    // ramp down
  ],
  thresholds: {
    // Gold SLO: error rate under 5%
    http_req_failed: ["rate<0.05"],
    // Cache must be doing its job: >50% hits at steady state
    cache_hit_rate:  ["rate>0.5"],
  },
};

const BASE_URL = "http://127.0.0.1:80";
const PRODUCT_IDS = Array.from({ length: 100 }, (_, i) => i + 1);

export default function () {
  if (Math.random() < 0.6) {
    // ── GET /products ──────────────────────────────────────────────────────
    const res = http.get(`${BASE_URL}/products`, {
      tags: { endpoint: "list_products" },
    });

    listLatency.add(res.timings.duration);

    const hit = res.headers["X-Cache"] === "HIT";
    cacheHitRate.add(hit ? 1 : 0);

    const ok = check(res, {
      "GET /products → 200":         (r) => r.status === 200,
      "GET /products → has records":  (r) => {
        try { return JSON.parse(r.body).length > 0; } catch { return false; }
      },
      "GET /products → X-Cache set": (r) =>
        r.headers["X-Cache"] === "HIT" || r.headers["X-Cache"] === "MISS",
    });

    errorRate.add(ok ? 0 : 1);
    if (!ok) errorCount.add(1);
  } else {
    // ── GET /products/:id ──────────────────────────────────────────────────
    const id = PRODUCT_IDS[Math.floor(Math.random() * PRODUCT_IDS.length)];
    const res = http.get(`${BASE_URL}/products/${id}`, {
      tags: { endpoint: "get_product" },
    });

    detailLatency.add(res.timings.duration);

    const hit = res.headers["X-Cache"] === "HIT";
    cacheHitRate.add(hit ? 1 : 0);

    const ok = check(res, {
      "GET /products/:id → 200":        (r) => r.status === 200,
      "GET /products/:id → correct id": (r) => {
        try { return JSON.parse(r.body).id === id; } catch { return false; }
      },
      "GET /products/:id → X-Cache set": (r) =>
        r.headers["X-Cache"] === "HIT" || r.headers["X-Cache"] === "MISS",
    });

    errorRate.add(ok ? 0 : 1);
    if (!ok) errorCount.add(1);
  }

  sleep(0.2);
}

export function handleSummary(data) {
  return { stdout: textSummary(data) };
}

function textSummary(data) {
  const m = data.metrics;

  const dur  = (k) => m.http_req_duration?.values?.[k]?.toFixed(2) ?? "N/A";
  const pct  = (v) => ((v ?? 0) * 100).toFixed(2);

  const avg  = dur("avg");
  const p50  = dur("med");
  const p95  = dur("p(95)");
  const p99  = dur("p(99)");
  const max  = dur("max");
  const rps  = m.http_reqs?.values?.rate?.toFixed(2) ?? "N/A";
  const tot  = m.http_reqs?.values?.count ?? 0;
  const fail = pct(m.http_req_failed?.values?.rate);
  const hitR = pct(m.cache_hit_rate?.values?.rate);

  const lP95 = m.list_products_duration?.values?.["p(95)"]?.toFixed(2) ?? "N/A";
  const lAvg = m.list_products_duration?.values?.avg?.toFixed(2) ?? "N/A";
  const dP95 = m.get_product_duration?.values?.["p(95)"]?.toFixed(2) ?? "N/A";
  const dAvg = m.get_product_duration?.values?.avg?.toFixed(2) ?? "N/A";

  const sloLatency = parseFloat(p95) < 2000 ? "✓ PASS" : "✗ FAIL";
  const sloErrors  = parseFloat(fail) < 5 ? "✓ PASS" : "✗ FAIL";
  const sloCacheHit = parseFloat(hitR) > 50 ? "✓ PASS" : "✗ FAIL";

  return `
================================================================================
  GOLD TIER LOAD TEST — RESULTS
  500 VUs × 120s sustained | Nginx → 3× Flask+Redis cache → PostgreSQL
================================================================================

  OVERALL HTTP DURATION
  ─────────────────────────────────────
  avg         : ${avg} ms
  p50 (median): ${p50} ms
  p95         : ${p95} ms   ← Gold SLO (<2000 ms)  ${sloLatency}
  p99         : ${p99} ms
  max         : ${max} ms

  THROUGHPUT & ERRORS
  ─────────────────────────────────────
  total reqs  : ${tot}
  req/s (RPS) : ${rps}
  error rate  : ${fail}%  ${sloErrors}

  CACHE PERFORMANCE
  ─────────────────────────────────────
  cache hit rate : ${hitR}%  ${sloCacheHit}

  PER-ENDPOINT BREAKDOWN
  ─────────────────────────────────────
  GET /products      avg=${lAvg} ms   p95=${lP95} ms
  GET /products/:id  avg=${dAvg} ms   p95=${dP95} ms

================================================================================
`;
}
