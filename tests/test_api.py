import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

import api
import config
import db

OK = {"ok": True, "latency_ms": 150.0, "tokens": 4400, "model": "jev-1.14.0", "activity": "computer", "confidence": 0.9,
      "probabilities": {"computer": 0.9, "gaming": 0.03, "other": 0.04, "nobody": 0.03},
      "nouls": {"person_present": 0.97, "tablet_gaming": 0.02, "controllers_out": 0.02, "camera_ok": 0.98}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    thumbs = tmp_path / "thumbnails"
    thumbs.mkdir()
    monkeypatch.setenv("PERCH_DB", str(path))
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "THUMBS_DIR", thumbs)
    conn = db.connect(path)
    sid = db.start_session(conn)
    for i in range(3):
        (thumbs / f"{i}.jpg").write_bytes(b"\xff\xd8fake")
        obs = {"ts": f"2026-11-14T18:00:{i * 10:02d}.000+00:00", "trigger": "heartbeat", "score": 1.0, "app": "Cursor",
               "domain": None, "idle_s": 1.0, "thumb_path": f"thumbnails/{i}.jpg"}
        db.add_observation(conn, sid, obs, OK)
    db.end_session(conn, sid, "quit")
    conn.close()
    return TestClient(api.app)


def test_labeling_round_trip(client):
    first = client.get("/api/label/next").json()
    assert first["remaining"] == 3 and set(first["item"]) == {"id", "t"}
    oid = first["item"]["id"]
    assert client.get(f"/api/thumb/{oid}").status_code == 200
    assert client.post("/api/label", json={"observation_id": oid, "mode": "computer", "sampled": "random"}).status_code == 200
    assert client.get("/api/label/summary").json() == {"counts": {"computer": 1}, "labeled": 1, "remaining": 2}
    assert client.get("/api/label/next?strategy=balanced").json()["item"]["id"] != oid
    acc = client.get("/api/accuracy").json()
    assert acc["n"] == 1 and acc["fused"]["accuracy"] == 1.0
    assert client.get("/api/accuracy?sampled=balanced").json()["n"] == 0
    # Undo hands the same frame back.
    assert client.delete(f"/api/label/{oid}").json()["item"]["id"] == oid
    assert client.get("/api/label/summary").json()["remaining"] == 3


def test_label_rejects_bad_input(client):
    assert client.post("/api/label", json={"observation_id": 1, "mode": "sleeping"}).status_code == 400
    assert client.post("/api/label", json={"observation_id": 999, "mode": "away"}).status_code == 404
    assert client.get("/api/thumb/999").status_code == 404


def test_skipped_labels_are_left_out_of_accuracy(client):
    client.post("/api/label", json={"observation_id": 1, "mode": "skip"})
    assert client.get("/api/accuracy").json()["n"] == 0


def test_stats(client):
    s = client.get("/api/stats?n=1&until=2026-11-14").json()
    assert s["observations"] == 3 and s["failed"] == 0
    assert s["latency_ms"]["p50"] == 150.0 and s["tokens_per_call"] == 4400
    assert s["triggers"] == {"heartbeat": 3}


def test_live_lists_newest_first_with_the_engine_verdict(client):
    d = client.get("/api/live?n=2").json()
    assert d["session"]["observations"] == 3 and len(d["observations"]) == 2
    first, second = d["observations"]
    assert first["t"] > second["t"]
    assert first["mode"] == "computer" and first["coding"] and first["rule"] == "os" and first["has_thumb"]
