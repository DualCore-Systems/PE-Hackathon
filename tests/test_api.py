"""Integration tests — hit the API via Flask test client."""
import json


class TestHealth:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.get_json() == {"status": "ok"}


class TestListProducts:
    def test_empty_list(self, client):
        resp = client.get("/products")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_list_returns_products(self, client, sample_products):
        resp = client.get("/products")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 5

    def test_list_product_fields(self, client, sample_product):
        resp = client.get("/products")
        data = resp.get_json()
        product = data[0]
        assert "id" in product
        assert "name" in product
        assert "category" in product
        assert "price" in product
        assert "stock" in product


class TestGetProduct:
    def test_get_existing_product(self, client, sample_product):
        resp = client.get(f"/products/{sample_product.id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "Test Widget"
        assert data["category"] == "Electronics"

    def test_get_nonexistent_product(self, client):
        resp = client.get("/products/99999")
        assert resp.status_code == 404
        data = resp.get_json()
        assert "error" in data


class TestCreateProduct:
    def test_create_valid_product(self, client):
        payload = {
            "name": "New Widget",
            "category": "Electronics",
            "price": 19.99,
            "stock": 50,
        }
        resp = client.post("/products", json=payload)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "New Widget"
        assert data["id"] is not None

    def test_create_product_with_description(self, client):
        payload = {
            "name": "Described Widget",
            "category": "Tools",
            "description": "A great tool",
            "price": 9.99,
            "stock": 10,
        }
        resp = client.post("/products", json=payload)
        assert resp.status_code == 201
        assert resp.get_json()["description"] == "A great tool"

    def test_create_product_missing_name(self, client):
        payload = {"category": "Electronics", "price": 10, "stock": 5}
        resp = client.post("/products", json=payload)
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"] == "validation failed"
        assert any("name" in d for d in data["details"])

    def test_create_product_missing_multiple_fields(self, client):
        resp = client.post("/products", json={})
        assert resp.status_code == 400
        data = resp.get_json()
        assert len(data["details"]) >= 4

    def test_create_product_negative_price(self, client):
        payload = {"name": "Bad", "category": "X", "price": -5, "stock": 1}
        resp = client.post("/products", json=payload)
        assert resp.status_code == 400
        assert any("price" in d for d in resp.get_json()["details"])

    def test_create_product_negative_stock(self, client):
        payload = {"name": "Bad", "category": "X", "price": 5, "stock": -1}
        resp = client.post("/products", json=payload)
        assert resp.status_code == 400
        assert any("stock" in d for d in resp.get_json()["details"])

    def test_create_product_invalid_price_type(self, client):
        payload = {"name": "Bad", "category": "X", "price": "free", "stock": 1}
        resp = client.post("/products", json=payload)
        assert resp.status_code == 400

    def test_create_product_empty_name(self, client):
        payload = {"name": "  ", "category": "X", "price": 5, "stock": 1}
        resp = client.post("/products", json=payload)
        assert resp.status_code == 400

    def test_create_product_no_json_body(self, client):
        resp = client.post("/products", data="not json", content_type="text/plain")
        assert resp.status_code == 400

    def test_create_product_strips_whitespace(self, client):
        payload = {"name": "  Padded  ", "category": "  Books  ", "price": 5, "stock": 1}
        resp = client.post("/products", json=payload)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "Padded"
        assert data["category"] == "Books"


class TestErrorHandlers:
    def test_404_unknown_route(self, client):
        resp = client.get("/nonexistent")
        assert resp.status_code == 404
        data = resp.get_json()
        assert data["error"] == "not found"

    def test_405_wrong_method(self, client):
        resp = client.delete("/products")
        assert resp.status_code == 405
        data = resp.get_json()
        assert data["error"] == "method not allowed"

    def test_405_patch_on_product(self, client, sample_product):
        resp = client.patch(f"/products/{sample_product.id}")
        assert resp.status_code == 405
