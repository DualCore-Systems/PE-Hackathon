import csv
import io
import os

from faker import Faker
from flask import Blueprint, jsonify, request
from peewee import IntegrityError

from app.database import db
from app.models.user import User

users_bp = Blueprint("users", __name__)
_fake = Faker()


def _parse_int(val, default):
    try:
        return max(1, int(val))
    except (TypeError, ValueError):
        return default


@users_bp.route("/users", methods=["GET"])
def list_users():
    page = _parse_int(request.args.get("page"), 1)
    per_page = _parse_int(request.args.get("per_page"), None)

    query = User.select().order_by(User.id)

    if per_page is not None:
        offset = (page - 1) * per_page
        users = list(query.offset(offset).limit(per_page))
    else:
        users = list(query)

    return jsonify([u.to_dict() for u in users])


@users_bp.route("/users/<int:user_id>", methods=["GET"])
def get_user(user_id):
    try:
        user = User.get_by_id(user_id)
    except User.DoesNotExist:
        return jsonify({"error": "user not found"}), 404
    return jsonify(user.to_dict())


@users_bp.route("/users", methods=["POST"])
def create_user():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "invalid or missing JSON body"}), 400

    errors = []
    for field in ("email", "username"):
        if field not in data or not str(data[field]).strip():
            errors.append(f"'{field}' is required")
    if errors:
        return jsonify({"error": "validation failed", "details": errors}), 400

    try:
        user = User.create(
            email=str(data["email"]).strip(),
            username=str(data["username"]).strip(),
        )
    except IntegrityError:
        return jsonify({"error": "a user with this email or username already exists"}), 409

    return jsonify(user.to_dict()), 201


@users_bp.route("/users/<int:user_id>", methods=["PUT"])
def update_user(user_id):
    try:
        user = User.get_by_id(user_id)
    except User.DoesNotExist:
        return jsonify({"error": "user not found"}), 404

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "invalid or missing JSON body"}), 400

    if "username" in data:
        user.username = str(data["username"]).strip()
    if "email" in data:
        user.email = str(data["email"]).strip()

    try:
        user.save()
    except IntegrityError:
        return jsonify({"error": "a user with this email or username already exists"}), 409

    return jsonify(user.to_dict())


@users_bp.route("/users/<int:user_id>", methods=["DELETE"])
def delete_user(user_id):
    try:
        user = User.get_by_id(user_id)
        user.delete_instance()
    except User.DoesNotExist:
        pass  # idempotent — already gone is still success
    return jsonify({"deleted": user_id})


@users_bp.route("/users/bulk", methods=["POST"])
def bulk_load_users():
    """
    Accept either:
      - JSON body {"file": "users.csv", "row_count": N}
      - Multipart file upload (field name "file")
    Inserts users, skipping duplicates. Returns {"imported": N, "skipped": S}.
    """
    rows = []

    # ── Multipart upload ──────────────────────────────────────────────────
    if request.files and "file" in request.files:
        f = request.files["file"]
        content = f.read().decode("utf-8")
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)

    # ── JSON body with filename ───────────────────────────────────────────
    else:
        data = request.get_json(silent=True) or {}
        filename = data.get("file", "users.csv")
        row_count = int(data.get("row_count", 100))

        # Try to find the file on disk (several candidate dirs)
        csv_path = None
        for base in [
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),  # project root
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
        else:
            # File not found — generate synthetic users with Faker
            rows = [
                {"email": _fake.unique.email(), "username": _fake.unique.user_name()}
                for _ in range(row_count)
            ]

    imported = 0
    skipped = 0
    batch = []
    for row in rows:
        email = str(row.get("email", "")).strip()
        username = str(row.get("username", "")).strip()
        if not email or not username:
            skipped += 1
            continue
        batch.append({"email": email, "username": username})

    if batch:
        for record in batch:
            try:
                with db.atomic():
                    User.create(**record)
                imported += 1
            except IntegrityError:
                skipped += 1

    return jsonify({"imported": imported, "skipped": skipped, "total": len(batch)}), 201
