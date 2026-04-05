def register_routes(app):
    from app.routes.products import products_bp
    from app.routes.cache_stats import cache_bp
    from app.routes.users import users_bp
    from app.routes.urls import urls_bp
    from app.routes.events import events_bp

    app.register_blueprint(products_bp)
    app.register_blueprint(cache_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(events_bp)
    # urls_bp last — contains a catch-all /<short_code> route
    app.register_blueprint(urls_bp)
