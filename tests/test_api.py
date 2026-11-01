from app.main import app, get_service
from fastapi.testclient import TestClient


def test_http_flow(service):
    app.dependency_overrides[get_service] = lambda: service
    try:
        client = TestClient(app)
        sid = client.post("/api/v1/sessions").json()["session_id"]
        headers = {"x-session-id": sid}
        assert client.get("/api/v1/orders/o", headers=headers).status_code == 403
        assert (
            client.post(
                f"/api/v1/sessions/{sid}/verify", json={"email": "test@example.invalid"}
            ).status_code
            == 200
        )
        assert client.get("/api/v1/orders/o", headers=headers).json()["status"] == "pending"
        assert client.get("/api/v1/orders/missing", headers=headers).status_code == 404
        p = client.post(
            "/api/v1/operations",
            headers=headers,
            json={"kind": "cancel", "order_id": "o", "reason": "no longer needed"},
        ).json()
        assert (
            client.post(
                f"/api/v1/operations/{p['proposal_id']}/confirm",
                headers=headers,
                json={"confirmed": False},
            ).status_code
            == 400
        )
        assert client.get("/api/v1/orders/o", headers=headers).json()["status"] == "pending"
        assert (
            client.post(
                f"/api/v1/operations/{p['proposal_id']}/confirm",
                headers=headers,
                json={"confirmed": True},
            ).json()["order_status"]
            == "cancelled"
        )
    finally:
        app.dependency_overrides.clear()
