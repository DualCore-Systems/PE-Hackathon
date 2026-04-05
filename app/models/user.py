from datetime import datetime, timezone

from peewee import CharField, DateTimeField

from app.database import BaseModel


class User(BaseModel):
    email = CharField(unique=True)
    username = CharField(unique=True)
    created_at = DateTimeField(default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "username": self.username,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
