import json

from flask import Blueprint, jsonify, request

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
