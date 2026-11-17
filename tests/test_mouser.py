from invscan.digikey import choose_product
from invscan.ingest import batch_key, ingest
from invscan.mouser import MOUSER_PN, mpn_from_pn, to_product
from invscan.parser import parse_scan
from tests.test_ingest import Fake
from tests.test_parser import MOUSER


def test_mouser_part_number_shape():
    assert MOUSER_PN.match("647-RL81C221MDN1KX")
    assert MOUSER_PN.match("652-CR0603-FX-1001ELF")
    assert not MOUSER_PN.match("011") and not MOUSER_PN.match("C29") and not MOUSER_PN.match("20631605")
    assert mpn_from_pn("647-RL81C221MDN1KX") == "RL81C221MDN1KX"
    assert mpn_from_pn("652-CR0603-FX-1001ELF") == "CR0603-FX-1001ELF"      # only the maker prefix is dropped


def test_mouser_api_result_is_normalised_like_a_digikey_product():
    part = {"MouserPartNumber": "647-RL81C221MDN1KX", "ManufacturerPartNumber": "RL81C221MDN1KX", "Manufacturer": "Nichicon",
            "Description": "Polymer Aluminum Capacitors 220uF 16V 20%", "ImagePath": "https://img.example/x.jpg",
            "DataSheetUrl": "https://ds.example/x.pdf", "ProductDetailUrl": "https://www.mouser.com/ProductDetail/x",
            "Category": "Polymer Aluminum Capacitors", "ProductAttributes": [{"AttributeName": "Capacitance", "AttributeValue": "220 uF"}]}
    p = to_product(part)
    assert p["ManufacturerProductNumber"] == "RL81C221MDN1KX" and p["Manufacturer"]["Name"] == "Nichicon"
    assert p["Description"]["ProductDescription"].startswith("Polymer")
    assert p["PhotoUrl"] and p["DatasheetUrl"] and p["ProductUrl"]
    assert p["Parameters"] == [{"ParameterText": "Capacitance", "ValueText": "220 uF"}]
    assert p["ProductVariations"][0]["DigiKeyProductNumber"] == "647-RL81C221MDN1KX"   # same key enrich_part reads


def test_manufacturer_hint_breaks_a_tie_between_makers():
    prods = [{"ManufacturerProductNumber": "4939", "Manufacturer": {"Name": "Keystone Electronics"}, "ProductVariations": []},
             {"ManufacturerProductNumber": "4939", "Manufacturer": {"Name": "Adafruit Industries LLC"}, "ProductVariations": []}]
    assert choose_product(prods, "4939", None, None) is None                      # ambiguous without a hint
    assert choose_product(prods, "4939", None, "Adafruit")["Manufacturer"]["Name"].startswith("Adafruit")
    assert choose_product(prods, "4939", None, "Nichicon") is None                # hint matches nobody


def _mouser_scan():
    s = parse_scan(MOUSER)
    s.supplier_sku = "647-RL81C221MDN1KX"
    s.mpn = mpn_from_pn(s.supplier_sku)
    return s


def test_mouser_batch_key_is_per_invoice_line():
    k = batch_key(_mouser_scan())
    assert k == "MO-88888888-011-77777777"
    s2 = _mouser_scan(); s2.line_item = "012"
    assert batch_key(s2) != k


def test_mouser_scan_creates_part_supplier_part_and_refuses_a_rescan():
    inv, s = Fake(), _mouser_scan()
    r = ingest(inv, s, 7)                       # no DigiKey/Mouser details available at all
    assert r.status == "created" and r.new_part
    assert inv.parts[0]["name"] == "RL81C221MDN1KX"
    st = inv.stock[0]
    assert st["quantity"] == 10 and st["batch"] == "MO-88888888-011-77777777"
    assert "Mouser" in st["notes"] and "ref C29" in st["notes"] and "DigiKey" not in st["notes"]
    sup = inv.stores["company/part/"][0]
    assert sup["SKU"] == "647-RL81C221MDN1KX"
    assert inv.stores["company/part/manufacturer/"][0]["MPN"] == "RL81C221MDN1KX"
    assert ingest(inv, _mouser_scan(), 7).status == "duplicate"


def test_server_asks_for_the_part_number_when_a_mouser_scan_has_none(monkeypatch):
    from fastapi.testclient import TestClient
    from invscan import server
    monkeypatch.setenv("INVSCAN_ALLOW_NO_PIN", "1"); monkeypatch.delenv("SCAN_PIN", raising=False)
    r = TestClient(server.app).post("/api/scan", json={"raw": MOUSER, "location_id": 5})
    assert r.status_code == 200 and r.json()["kind"] == "need_pn" and r.json()["manufacturer"] == "Nichicon"
