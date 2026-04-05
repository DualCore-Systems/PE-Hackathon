import secrets
import string
from datetime import datetime, timezone

from peewee import BooleanField, CharField, DateTimeField, ForeignKeyField, TextField

from app.database import BaseModel
from app.models.user import User


def _gen_short_code(length: int = 6) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


class Url(BaseModel):
    original_url = TextField()
    short_code = CharField(unique=True, max_length=20)
    title = CharField(null=True)
    user = ForeignKeyField(User, backref="urls", on_delete="CASCADE")
    is_active = BooleanField(default=True)
    created_at = DateTimeField(default=lambda: datetime.now(timezone.utc))

    class Meta:
        table_name = "url"

    def to_dict(self):
        return {
            "id": self.id,
            "original_url": self.original_url,
            "short_code": self.short_code,
            "title": self.title,
            "user_id": self.user_id,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
