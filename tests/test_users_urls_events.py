"""Tests for /users, /urls, and /events endpoints."""
import json


class TestUsers:
    def test_list_users_empty(self, client):
        resp = client.get("/users")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_list_users_returns_data(self, client, sample_user):
        resp = client.get("/users")
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["email"] == "user@example.com"

    def test_list_users_pagination(self, client):
        from app.models.user import User
        for i in range(15):
            User.create(email=f"u{i}@example.com", username=f"user{i}")
        resp = client.get("/users?page=1&per_page=10")
        assert resp.status_code == 200
        assert len(resp.get_json()) == 10

    def test_get_user_by_id(self, client, sample_user):
        resp = client.get(f"/users/{sample_user.id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == sample_user.id
        assert data["email"] == "user@example.com"

    def test_get_user_not_found(self, client):
        resp = client.get("/users/99999")
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "user not found"

    def test_create_user(self, client):
        resp = client.post("/users", json={"email": "new@example.com", "username": "newuser"})
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["email"] == "new@example.com"
        assert data["username"] == "newuser"
        assert data["id"] is not None

    def test_create_user_missing_fields(self, client):
        resp = client.post("/users", json={"email": "only@example.com"})
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "validation failed"

    def test_create_user_no_body(self, client):
        resp = client.post("/users", data="bad", content_type="text/plain")
        assert resp.status_code == 400

    def test_create_user_duplicate(self, client, sample_user):
        resp = client.post("/users", json={"email": "user@example.com", "username": "other"})
        assert resp.status_code == 409

    def test_update_user(self, client, sample_user):
        resp = client.put(f"/users/{sample_user.id}", json={"username": "updated"})
        assert resp.status_code == 200
        assert resp.get_json()["username"] == "updated"

    def test_update_user_not_found(self, client):
        resp = client.put("/users/99999", json={"username": "x"})
        assert resp.status_code == 404

    def test_update_user_no_body(self, client, sample_user):
        resp = client.put(f"/users/{sample_user.id}", data="bad", content_type="text/plain")
        assert resp.status_code == 400

    def test_delete_user(self, client, sample_user):
        resp = client.delete(f"/users/{sample_user.id}")
        assert resp.status_code == 200
        assert resp.get_json()["deleted"] == sample_user.id

    def test_delete_user_idempotent(self, client):
        resp = client.delete("/users/99999")
        assert resp.status_code == 200

    def test_bulk_load_users(self, client):
        resp = client.post("/users/bulk", json={"file": "nonexistent.csv", "row_count": 5})
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["imported"] == 5
        assert "skipped" in data


class TestUrls:
    def test_list_urls_empty(self, client):
        resp = client.get("/urls")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_list_urls(self, client, sample_url):
        resp = client.get("/urls")
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["short_code"] == "abc123"

    def test_filter_urls_by_user(self, client, sample_url):
        resp = client.get(f"/urls?user_id={sample_url.user_id}")
        data = resp.get_json()
        assert len(data) == 1

    def test_filter_urls_by_active(self, client, sample_url):
        resp = client.get("/urls?is_active=true")
        data = resp.get_json()
        assert len(data) == 1

    def test_filter_urls_by_inactive(self, client, sample_url):
        resp = client.get("/urls?is_active=false")
        assert resp.get_json() == []

    def test_get_url_by_id(self, client, sample_url):
        resp = client.get(f"/urls/{sample_url.id}")
        assert resp.status_code == 200
        assert resp.get_json()["short_code"] == "abc123"

    def test_get_url_not_found(self, client):
        resp = client.get("/urls/99999")
        assert resp.status_code == 404

    def test_create_url(self, client, sample_user):
        resp = client.post("/urls", json={
            "original_url": "https://example.com/page",
            "title": "My Page",
            "user_id": sample_user.id,
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert "short_code" in data
        assert data["original_url"] == "https://example.com/page"

    def test_create_url_missing_fields(self, client):
        resp = client.post("/urls", json={"title": "No URL"})
        assert resp.status_code == 400

    def test_create_url_invalid_user(self, client):
        resp = client.post("/urls", json={"original_url": "https://x.com", "user_id": 99999})
        assert resp.status_code == 404

    def test_create_url_no_body(self, client):
        resp = client.post("/urls", data="bad", content_type="text/plain")
        assert resp.status_code == 400

    def test_update_url_title(self, client, sample_url):
        resp = client.put(f"/urls/{sample_url.id}", json={"title": "New Title"})
        assert resp.status_code == 200
        assert resp.get_json()["title"] == "New Title"

    def test_deactivate_url(self, client, sample_url):
        resp = client.put(f"/urls/{sample_url.id}", json={"is_active": False})
        assert resp.status_code == 200
        assert resp.get_json()["is_active"] is False

    def test_update_url_not_found(self, client):
        resp = client.put("/urls/99999", json={"title": "x"})
        assert resp.status_code == 404

    def test_update_url_no_body(self, client, sample_url):
        resp = client.put(f"/urls/{sample_url.id}", data="bad", content_type="text/plain")
        assert resp.status_code == 400

    def test_delete_url(self, client, sample_url):
        resp = client.delete(f"/urls/{sample_url.id}")
        assert resp.status_code == 200

    def test_delete_url_idempotent(self, client):
        resp = client.delete("/urls/99999")
        assert resp.status_code == 200

    def test_redirect_short_code(self, client, sample_url):
        resp = client.get(f"/{sample_url.short_code}")
        assert resp.status_code == 302
        assert "example.com" in resp.headers["Location"]

    def test_redirect_not_found(self, client):
        resp = client.get("/nonexistent_code_xyz")
        assert resp.status_code == 404

    def test_redirect_inactive_url(self, client, sample_url):
        sample_url.is_active = False
        sample_url.save()
        resp = client.get(f"/{sample_url.short_code}")
        assert resp.status_code == 404


class TestEvents:
    def test_list_events_empty(self, client):
        resp = client.get("/events")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_list_events(self, client, sample_event):
        resp = client.get("/events")
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["event_type"] == "click"

    def test_filter_events_by_url(self, client, sample_event):
        resp = client.get(f"/events?url_id={sample_event.url_id}")
        assert len(resp.get_json()) == 1

    def test_filter_events_by_user(self, client, sample_event):
        resp = client.get(f"/events?user_id={sample_event.user_id}")
        assert len(resp.get_json()) == 1

    def test_filter_events_by_type(self, client, sample_event):
        resp = client.get("/events?event_type=click")
        assert len(resp.get_json()) == 1

    def test_filter_events_by_type_no_match(self, client, sample_event):
        resp = client.get("/events?event_type=view")
        assert resp.get_json() == []

    def test_create_event(self, client, sample_url, sample_user):
        resp = client.post("/events", json={
            "event_type": "click",
            "url_id": sample_url.id,
            "user_id": sample_user.id,
            "details": {"referrer": "https://google.com"},
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["event_type"] == "click"
        assert data["details"]["referrer"] == "https://google.com"

    def test_create_event_no_user(self, client, sample_url):
        resp = client.post("/events", json={
            "event_type": "view",
            "url_id": sample_url.id,
        })
        assert resp.status_code == 201
        assert resp.get_json()["user_id"] is None

    def test_create_event_missing_fields(self, client):
        resp = client.post("/events", json={"event_type": "click"})
        assert resp.status_code == 400

    def test_create_event_invalid_url(self, client):
        resp = client.post("/events", json={"event_type": "click", "url_id": 99999})
        assert resp.status_code == 404

    def test_create_event_invalid_user(self, client, sample_url):
        resp = client.post("/events", json={
            "event_type": "click",
            "url_id": sample_url.id,
            "user_id": 99999,
        })
        assert resp.status_code == 404

    def test_create_event_no_body(self, client):
        resp = client.post("/events", data="bad", content_type="text/plain")
        assert resp.status_code == 400
