from flask import Blueprint, jsonify

from app.cache import cache_stats

cache_bp = Blueprint("cache", __name__)


@cache_bp.route("/cache/stats")
def stats():
    return jsonify(cache_stats())
