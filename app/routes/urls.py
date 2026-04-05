import csv
import io
import os

from flask import Blueprint, jsonify, redirect, request
from peewee import IntegrityError

from app.database import db
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


@urls_bp.route("/urls/<int:url_id>", methods=["PUT", "PATCH"])
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


@urls_bp.route("/urls/bulk", methods=["POST"])
def bulk_load_urls():
    """Accept multipart CSV or JSON body with filename."""
    rows = []

    if request.files and "file" in request.files:
        f = request.files["file"]
        content = f.read().decode("utf-8")
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)
    else:
        data = request.get_json(silent=True) or {}
        filename = data.get("file", "urls.csv")
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
        original_url = str(row.get("original_url", "")).strip()
        short_code = str(row.get("short_code", "")).strip()
        user_id = row.get("user_id")
        if not original_url or not short_code or not user_id:
            skipped += 1
            continue
        try:
            with db.atomic():
                Url.create(
                    original_url=original_url,
                    short_code=short_code,
                    title=row.get("title"),
                    user=int(user_id),
                    is_active=str(row.get("is_active", "True")).lower() == "true",
                    created_at=row.get("created_at"),
                )
            imported += 1
        except (IntegrityError, Exception):
            skipped += 1

    return jsonify({"imported": imported, "skipped": skipped, "total": imported + skipped}), 201


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
