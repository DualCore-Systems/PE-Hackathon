from peewee import CharField, DecimalField, IntegerField, TextField

from app.database import BaseModel


class Product(BaseModel):
    name = CharField()
    category = CharField()
    description = TextField(null=True)
    price = DecimalField(decimal_places=2)
    stock = IntegerField()
