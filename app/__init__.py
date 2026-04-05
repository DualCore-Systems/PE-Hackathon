from dotenv import load_dotenv
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from app.cache import init_cache
from app.database import init_db
from app.logging_config import setup_logging
from app.metrics import setup_metrics
from app.routes import register_routes


def create_app():
    load_dotenv()

    app = Flask(__name__)

    setup_logging(app)
    init_db(app)
    init_cache()

    from app import models  # noqa: F401 - registers models with Peewee
    from app.database import db
    from app.models.product import Product
    from app.models.user import User
    from app.models.url import Url
    from app.models.event import Event

    with db:
        db.create_tables([Product, User, Url, Event], safe=True)

    register_routes(app)
    setup_metrics(app)

    @app.route("/health")
    def health():
        """Liveness check — always returns 200 if the process is running."""
        return jsonify(status="ok")

    @app.route("/health/ready")
    def readiness():
        """Readiness check — verifies DB and Redis are reachable."""
        checks = {}
        healthy = True

        # Check PostgreSQL
        try:
            from app.database import db
            db.execute_sql("SELECT 1")
            checks["database"] = "ok"
        except Exception as e:
            checks["database"] = f"error: {e}"
            healthy = False

        # Check Redis
        try:
            from app.cache import _client_or_raise
            _client_or_raise().ping()
            checks["cache"] = "ok"
        except Exception as e:
            checks["cache"] = f"error: {e}"
            healthy = False

        status_code = 200 if healthy else 503
        return jsonify(status="ok" if healthy else "degraded", checks=checks), status_code

    # ── JSON error handlers ──────────────────────────────────────────────
    @app.errorhandler(400)
    def bad_request(e):
        return jsonify(error="bad request", message=str(e.description)), 400

    @app.errorhandler(404)
    def not_found(e):
        return jsonify(error="not found", message=f"{request.path} does not exist"), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify(error="method not allowed", message=f"{request.method} is not allowed on {request.path}"), 405

    @app.errorhandler(500)
    def internal_error(e):
        return jsonify(error="internal server error", message="an unexpected error occurred"), 500

    @app.errorhandler(Exception)
    def unhandled_exception(e):
        if isinstance(e, HTTPException):
            return jsonify(error=e.name.lower(), message=str(e.description)), e.code
        return jsonify(error="internal server error", message="an unexpected error occurred"), 500

    return app
