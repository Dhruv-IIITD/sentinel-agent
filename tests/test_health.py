from fastapi.testclient import TestClient

from app.main import app


def test_healthz_reports_ok_in_memory_mode():
    with TestClient(app) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["checkpoint_backend"] == "memory"
        assert body["database"] == "not-configured"
        assert body["model"] == "claude-opus-4-8"


def test_lifespan_wires_a_checkpointer():
    from langgraph.checkpoint.memory import MemorySaver

    with TestClient(app):
        assert isinstance(app.state.checkpointer, MemorySaver)
