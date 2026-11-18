from fastapi.testclient import TestClient

from scripts.demo_server import app

c = TestClient(app)


def test_demo_serves_the_page_and_the_shapes_the_screens_read():
    assert "invscan" in c.get("/").text
    h = c.get("/api/home").json()
    assert set(h) >= {"counts", "recent", "unplaced", "unsorted"} and h["recent"][0]["path"]
    b = c.get("/api/browse", params={"category": 5}).json()
    assert b["total"] == len(b["parts"]) == 2 and {"id", "name", "thumbnail", "total", "specs"} <= set(b["parts"][0])
    p = c.get("/api/part/8").json()  # a power supply model lists its configurations
    assert [v["name"] for v in p["variants"]] == ["LRS-350 24V", "LRS-350 12V"] and p["total"] == 3
    assert c.get("/api/part/9").json()["template"]["name"] == "LRS-350"
    assert c.get("/api/find", params={"q": "15 ohm"}).json()[0]["where"]


def test_demo_never_saves_anything():
    r = c.post("/api/part/new", json={"name": "x"})
    assert r.status_code == 422 and "demo" in r.json()["detail"]
