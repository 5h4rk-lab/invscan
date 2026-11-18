from fastapi.testclient import TestClient

from scripts.demo_server import app

c = TestClient(app)


def test_demo_serves_the_page_and_the_shapes_the_screens_read():
    assert "invscan" in c.get("/").text
    h = c.get("/api/home").json()
    assert set(h) >= {"counts", "recent", "unplaced", "unsorted"} and h["recent"][0]["path"]
    b = c.get("/api/browse", params={"category": 5}).json()
    assert b["total"] == len(b["parts"]) == 6 and {"id", "name", "thumbnail", "total", "specs", "cols"} <= set(b["parts"][0])
    assert b["columns"][:2] == ["Power (Watts)", "Resistance"] or "Resistance" in b["columns"]
    p = c.get("/api/part/8").json()  # a power supply model lists its configurations
    assert [v["name"] for v in p["variants"]] == ["LRS-350 24V", "LRS-350 12V"] and p["total"] == 3
    assert c.get("/api/part/9").json()["template"]["name"] == "LRS-350"
    assert c.get("/api/find", params={"q": "15 ohm"}).json()[0]["where"]


def test_demo_never_saves_anything():
    r = c.post("/api/part/new", json={"name": "x"})
    assert r.status_code == 422 and "demo" in r.json()["detail"]


def test_demo_place_page_lists_what_is_inside_and_below():
    cab = next(i for i in range(1, 30) if c.get(f"/api/location/{i}").json()["name"] == "Cabinet #3")
    d = c.get(f"/api/location/{cab}").json()
    assert {p["name"] for p in d["parts"]} >= {"MC9S08PA60AVLF", "S9S12G192F0VLH", "ERA-8AHD150V"}  # parts in its drawers count
    assert [a["name"] for a in d["ancestors"]] == ["Room 127"] and {k["name"] for k in d["children"]} == {"Drawer 1", "Drawer 2"}
