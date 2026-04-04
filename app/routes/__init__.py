def register_routes(app):
    from app.routes.products import products_bp
    from app.routes.cache_stats import cache_bp
    app.register_blueprint(products_bp)
    app.register_blueprint(cache_bp)
