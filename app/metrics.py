"""Prometheus metrics for the Flask app + structured request logging."""
import logging
import time

from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST

logger = logging.getLogger("app.requests")

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
)

ERROR_COUNT = Counter(
    "http_errors_total",
    "Total HTTP error responses (4xx and 5xx)",
    ["method", "endpoint", "status"],
)

APP_UP = Gauge(
    "app_up",
    "Whether the app is up (1) or down (0)",
)
APP_UP.set(1)

APP_START_TIME = Gauge(
    "app_start_time_seconds",
    "Unix timestamp when the app started",
)
APP_START_TIME.set_to_current_time()


def setup_metrics(app):
    """Register before/after request hooks to track metrics."""

    @app.before_request
    def _start_timer():
        from flask import request, g
        g.start_time = time.time()

    @app.after_request
    def _record_metrics(response):
        from flask import request, g
        latency = time.time() - getattr(g, "start_time", time.time())
        endpoint = request.endpoint or "unknown"

        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=endpoint,
            status=response.status_code,
        ).inc()

        REQUEST_LATENCY.labels(
            method=request.method,
            endpoint=endpoint,
        ).observe(latency)

        if response.status_code >= 400:
            ERROR_COUNT.labels(
                method=request.method,
                endpoint=endpoint,
                status=response.status_code,
            ).inc()

        # Structured request log (skip /metrics to avoid noise)
        if endpoint != "metrics":
            log_level = logging.WARNING if response.status_code >= 400 else logging.INFO
            logger.log(log_level, "request", extra={
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "latency_ms": round(latency * 1000, 2),
                "remote_addr": request.remote_addr,
            })

        return response

    @app.route("/metrics")
    def metrics():
        from flask import Response
        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)
