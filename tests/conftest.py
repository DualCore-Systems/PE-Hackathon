"""Shared fixtures: in-memory SQLite app + client for fast, isolated tests."""
import os
from unittest.mock import patch

import pytest
from peewee import SqliteDatabase

from app.database import db
from app.models.product import Product
from app.models.user import User
from app.models.url import Url
from app.models.event import Event


TEST_DB = SqliteDatabase(":memory:")
MODELS = [Product, User, Url, Event]


def _test_init_db(app):
    """Replace the real Postgres init_db with one that uses our in-memory SQLite."""
    db.initialize(TEST_DB)

    @app.before_request
    def _db_connect():
        db.connect(reuse_if_open=True)

    @app.teardown_appcontext
    def _db_close(exc):
        if not db.is_closed():
            db.close()


@pytest.fixture(autouse=True)
def setup_test_db():
    """Bind all models to an in-memory SQLite DB, create tables, and clean up after each test."""
    TEST_DB.bind(MODELS)
    TEST_DB.connect()
    TEST_DB.create_tables(MODELS)
    yield
    TEST_DB.drop_tables(MODELS)
    TEST_DB.close()


@pytest.fixture()
def app():
    """Create a Flask app wired to the in-memory test DB."""
    with patch("app.init_db", _test_init_db), patch("app.init_cache"):
        from app import create_app
        application = create_app()
        application.config["TESTING"] = True
        return application


@pytest.fixture()
def client(app):
    """Flask test client for making HTTP requests."""
    return app.test_client()


@pytest.fixture()
def sample_product():
    """Insert and return a single product for tests that need existing data."""
    return Product.create(
        name="Test Widget",
        category="Electronics",
        description="A test product",
        price=29.99,
        stock=100,
    )


@pytest.fixture()
def sample_products():
    """Insert and return 5 products for list tests."""
    products = []
    for i in range(1, 6):
        products.append(
            Product.create(
                name=f"Product {i}",
                category="Books" if i % 2 else "Electronics",
                description=f"Description {i}",
                price=i * 10.0,
                stock=i * 5,
            )
        )
    return products


@pytest.fixture()
def sample_user():
    return User.create(email="user@example.com", username="testuser")


@pytest.fixture()
def sample_url(sample_user):
    return Url.create(
        original_url="https://example.com",
        short_code="abc123",
        title="Example",
        user=sample_user,
        is_active=True,
    )


@pytest.fixture()
def sample_event(sample_url, sample_user):
    import json
    return Event.create(
        event_type="click",
        url=sample_url,
        user=sample_user,
        details=json.dumps({"referrer": "https://google.com"}),
    )
