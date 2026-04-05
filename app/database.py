import os

from peewee import DatabaseProxy, Model, PostgresqlDatabase

db = DatabaseProxy()


class BaseModel(Model):
    class Meta:
        database = db


def init_db(app):
    database = PostgresqlDatabase(
        os.environ.get("DATABASE_NAME", "hackathon_db"),
        host=os.environ.get("DATABASE_HOST", "localhost"),
        port=int(os.environ.get("DATABASE_PORT", 5432)),
        user=os.environ.get("DATABASE_USER", "postgres"),
        password=os.environ.get("DATABASE_PASSWORD", "postgres"),
    )
    db.initialize(database)

    # Ensure all tables exist at startup (safe=True means no-op if already present)
    from app.models.product import Product
    from app.models.user import User
    from app.models.url import Url
    from app.models.event import Event

    database.connect()
    database.create_tables([Product, User, Url, Event], safe=True)
    database.close()

    @app.before_request
    def _db_connect():
        db.connect(reuse_if_open=True)

    @app.teardown_appcontext
    def _db_close(exc):
        if not db.is_closed():
            db.close()
