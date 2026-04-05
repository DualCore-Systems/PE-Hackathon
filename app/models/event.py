import json
from datetime import datetime, timezone

from peewee import CharField, DateTimeField, ForeignKeyField, TextField

from app.database import BaseModel
from app.models.url import Url
from app.models.user import User


class Event(BaseModel):
    event_type = CharField()
    url = ForeignKeyField(Url, backref="events", on_delete="CASCADE")
    user = ForeignKeyField(User, backref="events", null=True, on_delete="SET NULL")
    details = TextField(null=True)  # stored as JSON string
    created_at = DateTimeField(default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        details = None
        if self.details:
            try:
                details = json.loads(self.details)
            except (ValueError, TypeError):
                details = self.details
        return {
            "id": self.id,
            "event_type": self.event_type,
            "url_id": self.url_id,
            "user_id": self.user_id,
            "details": details,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
