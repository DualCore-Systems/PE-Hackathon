import http from "k6/http";
import { check, sleep } from "k6";
import { Counter, Rate, Trend } from "k6/metrics";

// Custom metrics
const errorCount = new Counter("errors");
const errorRate = new Rate("error_rate");
const listLatency = new Trend("list_products_duration", true);
const detailLatency = new Trend("get_product_duration", true);

export const options = {
  vus: 50,
  duration: "30s",
  thresholds: {
    http_req_failed: ["rate<0.05"],      // error rate under 5%
    http_req_duration: ["p(95)<2000"],   // p95 under 2s
  },
};

const BASE_URL = "http://127.0.0.1:5000";

// Product IDs to randomly fetch (seeded range)
const PRODUCT_IDS = Array.from({ length: 100 }, (_, i) => i + 1);

export default function () {
  // 60% of traffic: list all products
  if (Math.random() < 0.6) {
    const res = http.get(`${BASE_URL}/products`, {
      tags: { endpoint: "list_products" },
    });

    listLatency.add(res.timings.duration);

    const ok = check(res, {
      "GET /products status 200": (r) => r.status === 200,
      "GET /products has body": (r) => r.body && r.body.length > 0,
    });

    if (!ok) {
      errorCount.add(1);
      errorRate.add(1);
    } else {
      errorRate.add(0);
    }
  } else {
    // 40% of traffic: fetch a single product by random ID
    const id = PRODUCT_IDS[Math.floor(Math.random() * PRODUCT_IDS.length)];
    const res = http.get(`${BASE_URL}/products/${id}`, {
      tags: { endpoint: "get_product" },
    });

    detailLatency.add(res.timings.duration);

    const ok = check(res, {
      "GET /products/:id status 200": (r) => r.status === 200,
      "GET /products/:id has id field": (r) => {
        try {
          return JSON.parse(r.body).id === id;
        } catch {
          return false;
        }
      },
    });

    if (!ok) {
      errorCount.add(1);
      errorRate.add(1);
    } else {
      errorRate.add(0);
    }
  }

  sleep(0.5); // think time between requests
}

export function handleSummary(data) {
  return {
    stdout: textSummary(data),
  };
}

function textSummary(data) {
  const m = data.metrics;

  const p95 = m.http_req_duration?.values?.["p(95)"]?.toFixed(2) ?? "N/A";
  const avg = m.http_req_duration?.values?.avg?.toFixed(2) ?? "N/A";
  const med = m.http_req_duration?.values?.med?.toFixed(2) ?? "N/A";
  const p99 = m.http_req_duration?.values?.["p(99)"]?.toFixed(2) ?? "N/A";
  const maxD = m.http_req_duration?.values?.max?.toFixed(2) ?? "N/A";
  const failRate = ((m.http_req_failed?.values?.rate ?? 0) * 100).toFixed(2);
  const totalReqs = m.http_reqs?.values?.count ?? 0;
  const rps = m.http_reqs?.values?.rate?.toFixed(2) ?? "N/A";

  const listP95 = m.list_products_duration?.values?.["p(95)"]?.toFixed(2) ?? "N/A";
  const listAvg = m.list_products_duration?.values?.avg?.toFixed(2) ?? "N/A";
  const detailP95 = m.get_product_duration?.values?.["p(95)"]?.toFixed(2) ?? "N/A";
  const detailAvg = m.get_product_duration?.values?.avg?.toFixed(2) ?? "N/A";

  const vus = data.state?.testRunDurationMs
    ? (data.state.testRunDurationMs / 1000).toFixed(1)
    : "N/A";

  return `
================================================================================
  BRONZE TIER LOAD TEST — BASELINE METRICS
  50 VUs × 30s | Flask + Peewee + PostgreSQL
================================================================================

  OVERALL HTTP DURATION (all endpoints)
  ─────────────────────────────────────
  avg         : ${avg} ms
  median      : ${med} ms
  p95         : ${p95} ms   ← primary SLO target
  p99         : ${p99} ms
  max         : ${maxD} ms

  THROUGHPUT & ERRORS
  ─────────────────────────────────────
  total reqs  : ${totalReqs}
  req/s (RPS) : ${rps}
  error rate  : ${failRate}%

  PER-ENDPOINT BREAKDOWN
  ─────────────────────────────────────
  GET /products      avg=${listAvg} ms   p95=${listP95} ms
  GET /products/:id  avg=${detailAvg} ms   p95=${detailP95} ms

  TEST DURATION       : ${vus}s

================================================================================
`;
}
