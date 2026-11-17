from invscan.ingest import ingest
from invscan.parser import parse_scan
from tests.test_parser import REAL


class Fake:
    def __init__(self):
        self.parts, self.stock, self.cats = [], [], []

    def list(self, path, **q):
        if path == "stock/":
            return [s for s in self.stock if s["batch"] == q["batch"]]
        if path == "part/":
            return [p for p in self.parts if q["search"].lower() in p["name"].lower()]
        if path in ("parameter/", "parameter/template/"):
            return []
        if path == "part/category/":
            return self.cats
        return []

    def post(self, path, **b):
        store = {"parameter/": [], "parameter/template/": [], "part/": self.parts, "stock/": self.stock, "part/category/": self.cats}[path]
        row = {**b, "pk": len(store) + 1, "parent": None}
        store.append(row)
        return row


def test_new_part_then_duplicate_then_existing_part():
    inv, s = Fake(), parse_scan(REAL)
    r = ingest(inv, s, location_id=7)
    assert (r.status, r.new_part) == ("created", True)
    assert inv.stock[0]["quantity"] == 10 and inv.stock[0]["location"] == 7
    assert inv.parts[0]["name"] == "MSP430F2012TN"
    assert ingest(inv, s, 7).status == "duplicate"
    assert len(inv.stock) == 1
    # different bag, same part -> reuse part
    s2 = parse_scan(REAL.replace("13Z333333", "13Z111"))
    r2 = ingest(inv, s2, 8)
    assert (r2.status, r2.new_part) == ("created", False) and len(inv.parts) == 1


def test_missing_qty_is_error():
    s = parse_scan(REAL.replace("Q10", "Q"))
    assert ingest(Fake(), s, 1).status == "error"


def test_dk_lookup_failure_does_not_block_ingest():
    class Down:
        def lookup(self, mpn, sku=None):
            return None
    assert ingest(Fake(), parse_scan(REAL), 1, dk=Down()).status == "created"


def test_placeholder_load_id_does_not_collide():
    from invscan.ingest import batch_key
    from tests.test_parser import NEW
    a = parse_scan(NEW)
    b = parse_scan(NEW.replace("12Z1793316", "12Z5555555").replace("1P3SMAJ5939B-TP", "1POTHER"))
    assert a.load_id == "999999"
    assert batch_key(a) != batch_key(b)  # two different parts, same SO, placeholder load id


def test_real_load_id_key_is_unchanged():
    from invscan.ingest import batch_key
    from tests.test_parser import REAL
    assert batch_key(parse_scan(REAL)) == "DK-11111111-333333"  # keeps existing stock #10 matching


def test_note_roundtrip():
    from invscan.notes import get_note, set_note
    n = set_note("DigiKey SO 1", "blue box under desk")
    assert get_note(n) == "blue box under desk" and "DigiKey SO 1" in n
    n2 = set_note(n, "moved to shelf")
    assert get_note(n2) == "moved to shelf" and n2.count("NOTE:") == 1
    assert get_note(set_note(n2, "")) == ""


class FakeDK:
    def __init__(self, product=None, ambiguous=None):
        self.product, self.ambiguous = product, ambiguous or []
        self.asked = []

    def lookup(self, mpn, sku=None):
        self.asked.append((mpn, sku))
        return self.product


def test_sku_is_passed_to_digikey_lookup():
    from tests.test_parser import ADA
    dk = FakeDK()
    ingest(Fake(), parse_scan(ADA), 1, dk=dk)
    assert dk.asked == [("4939", "1528-4939-ND")]


def test_truncated_digikey_description_falls_back_to_detailed():
    from invscan.enrich import pick_description
    cut = {"Description": {"ProductDescription": "2.54MM 0.1 PITCH 8-PIN JUMPER CA", "DetailedDescription": "8 Position Cable Assembly Rectangular Socket to Socket 0.656' (200.00mm, 7.87\")"}}
    assert pick_description(cut).startswith("8 Position Cable Assembly")
    short = {"Description": {"ProductDescription": "IC MCU 16BIT 2KB FLASH 14DIP", "DetailedDescription": "long text"}}
    assert pick_description(short) == "IC MCU 16BIT 2KB FLASH 14DIP"
    assert pick_description({"Description": {"ProductDescription": "X" * 32}}) == "X" * 32


def test_pin_gate_and_rate_limit(monkeypatch):
    from fastapi.testclient import TestClient
    from invscan import server
    monkeypatch.setenv("SCAN_PIN", "4321")
    monkeypatch.delenv("INVSCAN_ALLOW_NO_PIN", raising=False)
    server._fails.clear()
    c = TestClient(server.app)
    assert c.get("/api/home").status_code == 401                      # no PIN: asked, not counted
    for _ in range(server.MAX_BAD_PINS):
        assert c.get("/api/home", headers={"X-Pin": "0000"}).status_code == 401
    assert c.get("/api/home", headers={"X-Pin": "0000"}).status_code == 429   # locked out
    assert c.get("/api/home", headers={"X-Pin": "4321"}).status_code == 429   # even the right one, for a minute
    server._fails.clear()


def test_no_pin_configured_refuses_to_run(monkeypatch):
    from fastapi.testclient import TestClient
    from invscan import server
    monkeypatch.delenv("SCAN_PIN", raising=False)
    monkeypatch.delenv("INVSCAN_ALLOW_NO_PIN", raising=False)
    assert TestClient(server.app).get("/api/home").status_code == 503


def test_bin_label_formats():
    from invscan.locations import parse_label
    assert parse_label("INVSCAN:LOC:5") == 5          # invscan's own label
    assert parse_label("INV-SL12") == 12              # label printed by InvenTree itself
    assert parse_label(" INV-SL7\n") == 7
    assert parse_label("INV-SI5") is None             # a stock item, not a bin
    assert parse_label("hello") is None


def test_print_plan():
    from invscan.printing import plan_print
    tpls = {"stocklocation": [{"id": 5, "name": "Location (QR)"}, {"id": 4, "name": "Location (QR + Text)"}]}
    ok = [{"id": "m1", "name": "Brother", "ok": True}]
    down = [{"id": "m1", "name": "Brother", "ok": False, "error": "Driver 'brother' not found"}]
    p = plan_print("stocklocation", tpls, ok, None, None)
    assert (p["plugin"], p["machine"], p["template"]) == ("inventreelabelmachine", "m1", 4)   # prefers the QR + Text label
    p = plan_print("stocklocation", tpls, down, "m1", 5)
    assert (p["plugin"], p["machine"], p["template"]) == ("inventreelabel", None, 5)         # falls back to PDF
    assert "Driver" in p["fallback"]
    assert plan_print("stocklocation", tpls, [], None, None)["plugin"] == "inventreelabel"


def test_print_plan_prefers_invscan_design():
    from invscan.printing import plan_print
    tpls = {"stocklocation": [{"id": 4, "name": "InvenTree Stock Location Label (QR + Text)"},
                              {"id": 20, "name": "invscan Bin Label (62x30)"}]}
    assert plan_print("stocklocation", tpls, [], None, None)["template"] == 20


def test_place_path_and_room_number():
    from invscan.locations import normalize_room, place_path
    assert normalize_room("204") == "Room 204"
    assert normalize_room(" 12B ") == "Room 12B"
    assert normalize_room("Room 204") == "Room 204"
    assert normalize_room("room 7") == "room 7"
    assert normalize_room("Lab") == "Lab"
    assert normalize_room("") == ""
    assert place_path("204", "Cabinet A", "Drawer 3", "Bin 2") == "Room 204 / Cabinet A / Drawer 3 / Bin 2"
    assert place_path("", "Cabinet A", "", "Bin 2") == "Cabinet A / Bin 2"
    assert place_path("", "", "", "") == ""


def test_manual_part_without_digikey_code():
    from invscan.ingest import add_manual
    inv = Fake()
    r = add_manual(inv, None, "WIDGET-9", "Handmade widget", 3, 7, None)
    assert r.status == "created" and r.new_part
    assert inv.parts[0]["name"] == "WIDGET-9" and inv.parts[0]["description"] == "Handmade widget"
    assert inv.stock[0]["quantity"] == 3 and inv.stock[0]["location"] == 7
    assert inv.stock[0]["batch"] == ""                                  # no digikey order, so no duplicate key
    assert "DigiKey SO" not in inv.stock[0]["notes"]
    # adding it again is allowed (a second handful) and reuses the part
    r2 = add_manual(inv, None, "WIDGET-9", "", 2, 7, None)
    assert r2.status == "created" and not r2.new_part and len(inv.parts) == 1 and len(inv.stock) == 2


def test_manual_digikey_pn_is_resolved_to_the_mpn():
    from invscan.ingest import add_manual
    class DK:
        ambiguous = []
        calls = 0
        def lookup(self, mpn, sku=None):
            self.calls += 1
            # first call resolves the DigiKey PN; later calls (enrichment) find nothing so the fake store is enough
            return {"ManufacturerProductNumber": "REAL-MPN"} if self.calls == 1 else None
    inv = Fake()
    r = add_manual(inv, DK(), "296-19733-5-ND", "", 1, 7, None)
    assert r.status == "created" and inv.parts[0]["name"] == "REAL-MPN"


def test_manual_needs_a_place():
    from invscan.ingest import add_manual
    assert add_manual(Fake(), None, "X", "", 1, None, None).status == "error"
    assert add_manual(Fake(), None, "", "", 1, 7, None).status == "error"
    assert add_manual(Fake(), None, "X", "", 0, 7, None).status == "error"


class FakeTree:
    """Minimal stand-in for InvenTree's location API, enough for add_room."""
    def __init__(self, rows):
        self.rows = {r["pk"]: dict(r) for r in rows}
        self.next = max(self.rows) + 1
        self.deleted = []

    def _path(self, pk):
        r = self.rows[pk]
        return r["name"] if not r["parent"] else self._path(r["parent"]) + "/" + r["name"]

    def get(self, path, **_):
        pk = int(path.strip("/").split("/")[-1])
        r = dict(self.rows[pk]); r["pathstring"] = self._path(pk); return r

    def list(self, path, **q):
        rows = [dict(r, pathstring=self._path(r["pk"])) for r in self.rows.values()]
        if "parent" in q:
            rows = [r for r in rows if r["parent"] == q["parent"]]
        if "search" in q:
            rows = [r for r in rows if q["search"].lower() in r["name"].lower()]
        return rows

    def post(self, path, **b):
        r = {"pk": self.next, "name": b["name"], "parent": b.get("parent")}; self.rows[self.next] = r; self.next += 1; return r

    def patch(self, path, **b):
        self.rows[int(path.strip("/").split("/")[-1])].update(b)

    def _req(self, method, path, **kw):
        assert method == "DELETE"; self.deleted.append(int(path.strip("/").split("/")[-1])); del self.rows[self.deleted[-1]]


def test_add_room_nests_a_cabinet_under_a_new_room():
    from invscan.locations import add_room
    t = FakeTree([{"pk": 1, "name": "Cabinet A", "parent": None}, {"pk": 2, "name": "Drawer 3", "parent": 1}])
    assert add_room(t, 2, "204")["path"] == "Room 204/Cabinet A/Drawer 3"


def test_add_room_does_not_duplicate_a_place_already_named_after_the_room():
    from invscan.locations import add_room
    # '127' was the top level; adding Room 127 must turn it into the room, not nest 127 inside Room 127
    t = FakeTree([{"pk": 1, "name": "127", "parent": None}, {"pk": 2, "name": "Cabinet #3", "parent": 1}, {"pk": 3, "name": "Drawer 1", "parent": 2}])
    assert add_room(t, 3, "127")["path"] == "Room 127/Cabinet #3/Drawer 1"
    assert len([r for r in t.rows.values() if r["parent"] is None]) == 1
