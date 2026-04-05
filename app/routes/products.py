from flask import Blueprint, jsonify, make_response, request
from playhouse.shortcuts import model_to_dict

from app.cache import PRODUCT_KEY, PRODUCTS_ALL_KEY, cache_delete, cache_get, cache_set
from app.models.product import Product

products_bp = Blueprint("products", __name__)


def _product_cache_key(product_id: int) -> str:
    return PRODUCT_KEY.format(id=product_id)


@products_bp.route("/products")
def list_products():
    cached = cache_get(PRODUCTS_ALL_KEY)
    if cached is not None:
        resp = make_response(jsonify(cached))
        resp.headers["X-Cache"] = "HIT"
        return resp

    products = [model_to_dict(p) for p in Product.select().order_by(Product.id)]
    cache_set(PRODUCTS_ALL_KEY, products)

    resp = make_response(jsonify(products))
    resp.headers["X-Cache"] = "MISS"
    return resp


@products_bp.route("/products", methods=["POST"])
def create_product():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "invalid or missing JSON body"}), 400

    errors = []
    # Required fields
    for field in ("name", "category", "price", "stock"):
        if field not in data:
            errors.append(f"'{field}' is required")

    if errors:
        return jsonify({"error": "validation failed", "details": errors}), 400

    # Type / value validation
    price = None
    stock = None

    if not isinstance(data["name"], str) or not data["name"].strip():
        errors.append("'name' must be a non-empty string")
    elif len(data["name"].strip()) > 255:
        errors.append("'name' must be 255 characters or fewer")
    if not isinstance(data["category"], str) or not data["category"].strip():
        errors.append("'category' must be a non-empty string")
    elif len(data["category"].strip()) > 255:
        errors.append("'category' must be 255 characters or fewer")
    try:
        price = float(data["price"])
        if price < 0:
            errors.append("'price' must be >= 0")
    except (TypeError, ValueError):
        errors.append("'price' must be a number")
    try:
        stock = int(data["stock"])
        if stock < 0:
            errors.append("'stock' must be >= 0")
    except (TypeError, ValueError):
        errors.append("'stock' must be an integer")

    if errors:
        return jsonify({"error": "validation failed", "details": errors}), 400

    product = Product.create(
        name=data["name"].strip(),
        category=data["category"].strip(),
        description=data.get("description"),
        price=price,
        stock=stock,
    )
    # Invalidate the list cache so next GET /products is fresh
    cache_delete(PRODUCTS_ALL_KEY)
    return jsonify(model_to_dict(product)), 201


@products_bp.route("/products/<int:product_id>")
def get_product(product_id):
    key = _product_cache_key(product_id)
    cached = cache_get(key)
    if cached is not None:
        resp = make_response(jsonify(cached))
        resp.headers["X-Cache"] = "HIT"
        return resp

    try:
        product = Product.get_by_id(product_id)
    except Product.DoesNotExist:
        return jsonify({"error": "not found"}), 404

    data = model_to_dict(product)
    cache_set(key, data)

    resp = make_response(jsonify(data))
    resp.headers["X-Cache"] = "MISS"
    return resp
