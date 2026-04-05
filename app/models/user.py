from datetime import datetime, timezone

from peewee import CharField, DateTimeField

from app.database import BaseModel


class User(BaseModel):
    email = CharField(unique=True)
    username = CharField(unique=True)
    created_at = DateTimeField(default=lambda: datetime.now(timezone.utc))

    def to_dict(self, include_counts=False):
        d = {
            "id": self.id,
            "email": self.email,
            "username": self.username,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_counts:
            from app.models.url import Url
            from app.models.event import Event
            d["url_count"] = Url.select().where(Url.user == self.id).count()
            d["event_count"] = Event.select().where(Event.user == self.id).count()
        return d
