import csv
import io
import json

from flask import Blueprint, jsonify, request
from peewee import fn

from app.database import db
from app.models.event import Event
from app.models.url import Url
from app.models.user import User

events_bp = Blueprint("events", __name__)


@events_bp.route("/events", methods=["GET"])
def list_events():
    query = Event.select().order_by(Event.id)

    url_id = request.args.get("url_id")
    if url_id is not None:
        query = query.where(Event.url == int(url_id))

    user_id = request.args.get("user_id")
    if user_id is not None:
        query = query.where(Event.user == int(user_id))

    event_type = request.args.get("event_type")
    if event_type is not None:
        query = query.where(Event.event_type == event_type)

    return jsonify([e.to_dict() for e in query])


@events_bp.route("/events/<int:event_id>", methods=["GET"])
def get_event(event_id):
    try:
        event = Event.get_by_id(event_id)
    except Event.DoesNotExist:
        return jsonify({"error": "event not found"}), 404
    return jsonify(event.to_dict())


@events_bp.route("/events/<int:event_id>", methods=["DELETE"])
def delete_event(event_id):
    try:
        event = Event.get_by_id(event_id)
        event.delete_instance()
    except Event.DoesNotExist:
        pass
    return jsonify({"deleted": event_id})


@events_bp.route("/events", methods=["POST"])
def create_event():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "invalid or missing JSON body"}), 400

    errors = []
    for field in ("event_type", "url_id"):
        if field not in data:
            errors.append(f"'{field}' is required")
    if errors:
        return jsonify({"error": "validation failed", "details": errors}), 400

    # Verify URL exists
    try:
        url = Url.get_by_id(int(data["url_id"]))
    except (Url.DoesNotExist, TypeError, ValueError):
        return jsonify({"error": "url not found"}), 404

    # Optional user
    user = None
    if data.get("user_id") is not None:
        try:
            user = User.get_by_id(int(data["user_id"]))
        except (User.DoesNotExist, TypeError, ValueError):
            return jsonify({"error": "user not found"}), 404

    details = data.get("details")
    if details is not None and not isinstance(details, str):
        details = json.dumps(details)

    event = Event.create(
        event_type=str(data["event_type"]).strip(),
        url=url,
        user=user,
        details=details,
    )

    return jsonify(event.to_dict()), 201


@events_bp.route("/events/bulk", methods=["POST"])
def bulk_load_events():
    """Accept multipart CSV upload or JSON body with filename."""
    rows = []

    if request.files and "file" in request.files:
        f = request.files["file"]
        content = f.read().decode("utf-8")
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)
    else:
        data = request.get_json(silent=True) or {}
        import os
        filename = data.get("file", "events.csv")
        csv_path = None
        for base in [
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "/app",
            "/data",
            "/app/data",
        ]:
            candidate = os.path.join(base, filename)
            if os.path.isfile(candidate):
                csv_path = candidate
                break
        if csv_path:
            with open(csv_path, newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                rows = list(reader)

    imported = 0
    skipped = 0
    for row in rows:
        event_type = str(row.get("event_type", "")).strip()
        url_id = row.get("url_id")
        if not event_type or not url_id:
            skipped += 1
            continue
        try:
            with db.atomic():
                Event.create(
                    event_type=event_type,
                    url=int(url_id),
                    user=int(row["user_id"]) if row.get("user_id") else None,
                    details=row.get("details"),
                    created_at=row.get("timestamp") or row.get("created_at"),
                )
            imported += 1
        except Exception:
            skipped += 1

    return jsonify({"imported": imported, "skipped": skipped, "total": imported + skipped}), 201


@events_bp.route("/events/stats", methods=["GET"])
def event_stats():
    """Return aggregate event statistics."""
    total = Event.select().count()
    by_type = (
        Event.select(Event.event_type, fn.COUNT(Event.id).alias("count"))
        .group_by(Event.event_type)
        .dicts()
    )
    return jsonify({
        "total": total,
        "by_type": {row["event_type"]: row["count"] for row in by_type},
    })
