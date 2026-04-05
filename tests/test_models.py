"""Unit tests for the Product model — test CRUD in isolation."""
from decimal import Decimal

import pytest

from app.models.product import Product


class TestProductCreate:
    def test_create_product(self):
        p = Product.create(name="Widget", category="Electronics", price=9.99, stock=10)
        assert p.id is not None
        assert p.name == "Widget"
        assert p.category == "Electronics"
        assert float(p.price) == 9.99
        assert p.stock == 10

    def test_create_product_with_description(self):
        p = Product.create(
            name="Gadget", category="Tools", description="Handy tool", price=5.00, stock=3
        )
        assert p.description == "Handy tool"

    def test_create_product_null_description(self):
        p = Product.create(name="Gadget", category="Tools", price=5.00, stock=3)
        assert p.description is None

    def test_create_product_zero_stock(self):
        p = Product.create(name="Sold Out", category="Misc", price=1.00, stock=0)
        assert p.stock == 0

    def test_create_product_zero_price(self):
        p = Product.create(name="Freebie", category="Promo", price=0.00, stock=50)
        assert float(p.price) == 0.00


class TestProductRead:
    def test_get_by_id(self, sample_product):
        fetched = Product.get_by_id(sample_product.id)
        assert fetched.name == "Test Widget"

    def test_get_by_id_not_found(self):
        with pytest.raises(Product.DoesNotExist):
            Product.get_by_id(99999)

    def test_select_all(self, sample_products):
        products = list(Product.select())
        assert len(products) == 5

    def test_select_ordered(self, sample_products):
        products = list(Product.select().order_by(Product.id))
        names = [p.name for p in products]
        assert names == [f"Product {i}" for i in range(1, 6)]


class TestProductUpdate:
    def test_update_name(self, sample_product):
        sample_product.name = "Updated Widget"
        sample_product.save()
        fetched = Product.get_by_id(sample_product.id)
        assert fetched.name == "Updated Widget"

    def test_update_stock(self, sample_product):
        sample_product.stock = 0
        sample_product.save()
        fetched = Product.get_by_id(sample_product.id)
        assert fetched.stock == 0


class TestProductDelete:
    def test_delete_product(self, sample_product):
        pid = sample_product.id
        sample_product.delete_instance()
        with pytest.raises(Product.DoesNotExist):
            Product.get_by_id(pid)

    def test_delete_nonexistent(self):
        # Deleting something that doesn't exist should not raise
        deleted = Product.delete().where(Product.id == 99999).execute()
        assert deleted == 0
