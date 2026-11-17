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
