from flask import Blueprint, jsonify, redirect, request
from peewee import IntegrityError

from app.models.event import Event
from app.models.url import Url, _gen_short_code
from app.models.user import User

urls_bp = Blueprint("urls", __name__)

_MAX_SHORT_CODE_RETRIES = 10


def _unique_short_code() -> str:
    for _ in range(_MAX_SHORT_CODE_RETRIES):
        code = _gen_short_code()
        if not Url.select().where(Url.short_code == code).exists():
            return code
    raise RuntimeError("Could not generate a unique short_code after retries")


@urls_bp.route("/urls", methods=["GET"])
def list_urls():
    query = Url.select().order_by(Url.id)

    user_id = request.args.get("user_id")
    if user_id is not None:
        query = query.where(Url.user == int(user_id))

    is_active = request.args.get("is_active")
    if is_active is not None:
        query = query.where(Url.is_active == (is_active.lower() == "true"))

    return jsonify([u.to_dict() for u in query])


@urls_bp.route("/urls/<int:url_id>", methods=["GET"])
def get_url(url_id):
    try:
        url = Url.get_by_id(url_id)
    except Url.DoesNotExist:
        return jsonify({"error": "not found"}), 404
    return jsonify(url.to_dict())


@urls_bp.route("/urls", methods=["POST"])
def create_url():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "invalid or missing JSON body"}), 400

    errors = []
    for field in ("original_url", "user_id"):
        if field not in data:
            errors.append(f"'{field}' is required")
    if errors:
        return jsonify({"error": "validation failed", "details": errors}), 400

    # Verify user exists
    try:
        user = User.get_by_id(int(data["user_id"]))
    except User.DoesNotExist:
        return jsonify({"error": "user not found"}), 404
    except (TypeError, ValueError):
        return jsonify({"error": "validation failed", "details": ["'user_id' must be an integer"]}), 400

    short_code = data.get("short_code") or _unique_short_code()

    try:
        url = Url.create(
            original_url=str(data["original_url"]).strip(),
            short_code=short_code,
            title=data.get("title"),
            user=user,
            is_active=data.get("is_active", True),
        )
    except IntegrityError:
        return jsonify({"error": "short_code already exists"}), 409

    return jsonify(url.to_dict()), 201


@urls_bp.route("/urls/<int:url_id>", methods=["PUT"])
def update_url(url_id):
    try:
        url = Url.get_by_id(url_id)
    except Url.DoesNotExist:
        return jsonify({"error": "not found"}), 404

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "invalid or missing JSON body"}), 400

    if "title" in data:
        url.title = data["title"]
    if "is_active" in data:
        url.is_active = bool(data["is_active"])
    if "original_url" in data:
        url.original_url = str(data["original_url"]).strip()

    url.save()
    return jsonify(url.to_dict())


@urls_bp.route("/urls/<int:url_id>", methods=["DELETE"])
def delete_url(url_id):
    try:
        url = Url.get_by_id(url_id)
        url.delete_instance()
    except Url.DoesNotExist:
        pass  # idempotent — already gone is still success
    return jsonify({"deleted": url_id})


@urls_bp.route("/urls/<int:url_id>/events", methods=["GET"])
def get_url_events(url_id):
    try:
        url = Url.get_by_id(url_id)
    except Url.DoesNotExist:
        return jsonify({"error": "url not found"}), 404
    events = Event.select().where(Event.url == url).order_by(Event.id)
    return jsonify([e.to_dict() for e in events])


@urls_bp.route("/urls/<int:url_id>/stats", methods=["GET"])
def get_url_stats(url_id):
    try:
        url = Url.get_by_id(url_id)
    except Url.DoesNotExist:
        return jsonify({"error": "url not found"}), 404
    total_events = Event.select().where(Event.url == url).count()
    clicks = Event.select().where(Event.url == url, Event.event_type == "click").count()
    return jsonify({
        "url_id": url_id,
        "total_events": total_events,
        "clicks": clicks,
    })


@urls_bp.route("/<short_code>", methods=["GET"])
def redirect_short_code(short_code):
    try:
        url = Url.get(Url.short_code == short_code, Url.is_active == True)  # noqa: E712
    except Url.DoesNotExist:
        return jsonify({"error": "not found"}), 404

    # Track the click event
    try:
        Event.create(
            event_type="click",
            url=url,
            user=None,
            details=None,
        )
    except Exception:
        pass  # don't let tracking failures break redirects

    return redirect(url.original_url, code=302)
