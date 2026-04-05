"""Structured JSON logging for all app components."""
import logging
import sys

from pythonjsonlogger.json import JsonFormatter


def setup_logging(app):
    """Configure structured JSON logging for the Flask app."""
    formatter = JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "component"},
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    # Root logger — catches everything
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Flask app logger
    app.logger.handlers.clear()
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)

    # Suppress noisy werkzeug request logs in favour of our own
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
