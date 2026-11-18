from invscan.browse import compute_facets, natural_key
from invscan.categories import digikey_path, ensure_category_path
from tests.test_ingest import Fake

DK_CAP = {"Category": {"Name": "Capacitors", "ChildCategories": [{"Name": "Aluminum - Polymer Capacitors", "ChildCategories": []}]}}
DK_ZENER = {"Category": {"Name": "Discrete Semiconductor Products", "ChildCategories": [{"Name": "Diodes", "ChildCategories": [
    {"Name": "Zener", "ChildCategories": [{"Name": "Single Zener Diodes", "ChildCategories": []}]}]}]}}


def test_digikey_category_path():
    assert digikey_path(DK_CAP) == ["Capacitors", "Aluminum - Polymer Capacitors"]
    assert digikey_path(DK_ZENER) == ["Discrete Semiconductor Products", "Diodes", "Zener", "Single Zener Diodes"]
    assert digikey_path({"Category": {"Name": "Resistors"}}) == ["Resistors"]       # Mouser results are flat
    assert digikey_path({}) == [] and digikey_path(None) == []


def test_ensure_category_path_builds_the_tree_once():
    inv = Fake()
    leaf = ensure_category_path(inv, ["Capacitors", "Aluminum - Polymer Capacitors"])
    assert [c["name"] for c in inv.cats] == ["Capacitors", "Aluminum - Polymer Capacitors"]
    assert inv.cats[1]["parent"] == inv.cats[0]["pk"] and leaf == inv.cats[1]["pk"]
    assert ensure_category_path(inv, ["capacitors", "ALUMINUM - POLYMER CAPACITORS"]) == leaf      # same place, no duplicates
    assert len(inv.cats) == 2
    leaf2 = ensure_category_path(inv, ["Capacitors", "Ceramic Capacitors"])
    assert len(inv.cats) == 3 and leaf2 != leaf and inv.cats[2]["parent"] == inv.cats[0]["pk"]
    assert ensure_category_path(inv, ["Bad/Name"]) and "/" not in inv.cats[-1]["name"]              # '/' is the path separator
    assert ensure_category_path(inv, []) is None


def test_natural_sort_orders_numbers_like_a_person():
    assert sorted(["100 uF", "22 uF", "4.7 uF", "220 uF"], key=natural_key) == ["4.7 uF", "22 uF", "100 uF", "220 uF"]


ITEMS = [
    {"id": 1, "params": {"Capacitance": "220 µF", "Voltage": "16 V", "Package": "TH"}},
    {"id": 2, "params": {"Capacitance": "220 µF", "Voltage": "25 V", "Package": "SMD"}},
    {"id": 3, "params": {"Capacitance": "100 µF", "Voltage": "16 V", "Package": "SMD"}},
    {"id": 4, "params": {"Capacitance": "100 µF", "Voltage": "16 V", "Package": "SMD"}},
    {"id": 5, "params": {"Only": "on one part"}},
]


def test_facets_list_values_with_counts_and_skip_useless_ones():
    ids, facets = compute_facets(ITEMS, {})
    assert ids == [1, 2, 3, 4, 5]
    names = [f["name"] for f in facets]
    assert "Capacitance" in names and "Voltage" in names and "Only" not in names     # one value / rare: not useful
    cap = next(f for f in facets if f["name"] == "Capacitance")
    assert {v["value"]: v["count"] for v in cap["values"]} == {"220 µF": 2, "100 µF": 2}


def test_selecting_values_filters_and_keeps_other_options_visible():
    ids, facets = compute_facets(ITEMS, {"Voltage": ["16 V"]})
    assert ids == [1, 3, 4]
    volt = next(f for f in facets if f["name"] == "Voltage")
    # the facet you are filtering still shows the other voltages (so you can switch), counted without its own filter
    assert {v["value"]: v["count"] for v in volt["values"]} == {"16 V": 3, "25 V": 1}
    assert [v["value"] for v in volt["values"] if v["selected"]] == ["16 V"]
    pkg = next(f for f in facets if f["name"] == "Package")
    assert {v["value"]: v["count"] for v in pkg["values"]} == {"TH": 1, "SMD": 2}              # counted within the 16 V result
    ids2, _ = compute_facets(ITEMS, {"Voltage": ["16 V"], "Package": ["SMD"]})
    assert ids2 == [3, 4]
    ids3, _ = compute_facets(ITEMS, {"Voltage": ["16 V", "25 V"], "Package": ["SMD"]})        # values within a facet are OR
    assert ids3 == [2, 3, 4]


def test_natural_sort_handles_names_that_start_with_a_digit_or_a_letter():
    # numbers sort before words, numbers by value; mixing the two must not raise
    got = sorted(["Equipment", "4939", "LM317T", "3SMAJ5939B-TP", "100 uF"], key=natural_key)
    assert got == ["3SMAJ5939B-TP", "100 uF", "4939", "Equipment", "LM317T"]


def test_a_new_part_is_filed_in_its_digikey_category_not_unsorted():
    from invscan.ingest import ingest
    from invscan.parser import Scan

    class DK:
        ambiguous = []
        def lookup(self, mpn, sku=None, manufacturer=None):
            return {"ManufacturerProductNumber": mpn, "Manufacturer": {"Name": "Acme"}, "Description": {"ProductDescription": "x"},
                    "ProductVariations": [], "Parameters": [], **DK_CAP}

    inv = Fake()
    r = ingest(inv, Scan(mpn="C1", qty=1), 7, dk=DK(), description="cap")
    assert r.status == "created"
    assert [c["name"] for c in inv.cats] == ["Capacitors", "Aluminum - Polymer Capacitors"]     # no "Unsorted" created
    assert inv.parts[0]["category"] == inv.cats[1]["pk"]


def test_hand_added_part_with_no_supplier_match_goes_to_miscellaneous():
    from invscan.ingest import add_manual
    inv = Fake()
    r = add_manual(inv, None, "ThinkPad T60", "IBM laptop", 1, 7, None)
    assert r.status == "created"
    assert [c["name"] for c in inv.cats] == ["Miscellaneous"]            # not Unsorted
    assert inv.parts[0]["category"] == inv.cats[0]["pk"]


def test_hand_added_part_can_be_filed_where_you_choose():
    from invscan.ingest import add_manual
    inv = Fake()
    cat = ensure_category_path(inv, ["Equipment", "Laptops"])
    r = add_manual(inv, None, "ThinkPad T60", "IBM laptop", 1, 7, None, category=cat)
    assert r.status == "created" and inv.parts[0]["category"] == cat
    assert "Miscellaneous" not in [c["name"] for c in inv.cats]          # no needless category


def test_scanned_bags_that_cannot_be_sorted_yet_stay_in_unsorted_for_a_retry():
    from invscan.ingest import ingest
    from invscan.parser import Scan
    inv = Fake()
    ingest(inv, Scan(mpn="X1", vendor="digikey", sales_order="1", load_id="2", qty=1), 7)   # DigiKey gave no data
    assert [c["name"] for c in inv.cats] == ["Unsorted"]


def test_new_part_request_accepts_a_category():
    from invscan.server import NewPartIn
    assert NewPartIn(name="x", qty=1, category=5).category == 5
    assert NewPartIn(name="x", qty=1).category is None


def _scan(order):
    from invscan.parser import Scan
    return Scan(mpn="WIDGET-1", vendor="digikey", sales_order=order, load_id=order + "1", qty=5)


def test_a_second_bag_of_the_same_part_reports_where_you_already_keep_it():
    from invscan.ingest import ingest
    inv = Fake()
    first = ingest(inv, _scan("100"), 5)
    assert first.status == "created" and first.others == []                    # nothing elsewhere yet
    inv.stock[0]["location_detail"] = {"pathstring": "Cabinet A/Drawer 3/Bin 2"}
    second = ingest(inv, _scan("200"), 9)
    assert second.status == "created" and not second.new_part
    assert len(second.others) == 1
    o = second.others[0]
    assert o["path"] == "Cabinet A/Drawer 3/Bin 2" and o["qty"] == 5 and o["stock_id"] == inv.stock[0]["pk"]


def test_other_parts_are_not_reported():
    from invscan.ingest import ingest
    from invscan.parser import Scan
    inv = Fake()
    ingest(inv, _scan("100"), 5)
    r = ingest(inv, Scan(mpn="OTHER-9", vendor="digikey", sales_order="300", load_id="301", qty=1), 9)
    assert r.others == []


def test_damaged_label_entry_keeps_lot_and_date_code_in_the_notes():
    from invscan.ingest import add_manual
    inv = Fake()
    r = add_manual(inv, None, "WIDGET-9", "", 1, 7, None, lot_code="2408_REV5", date_code="2408")
    assert r.status == "created"
    n = inv.stock[0]["notes"]
    assert "lot 2408_REV5" in n and "date code 2408" in n


def test_new_part_request_takes_lot_and_date_code():
    from invscan.server import NewPartIn
    m = NewPartIn(name="x", qty=1, lot_code="L1", date_code="2408")
    assert (m.lot_code, m.date_code) == ("L1", "2408")


def test_enrichment_replaces_the_placeholder_description_but_keeps_one_you_typed():
    from invscan.enrich import enrich_part

    class Inv(Fake):
        def __init__(self, desc):
            super().__init__(); self.desc, self.patches = desc, []
        def get(self, path, **_):
            return {"description": self.desc, "keywords": "x", "link": "http://l", "image": "i", "category_name": "Equipment"}
        def patch(self, path, **b):
            self.patches.append(b)
    prod = {"ManufacturerProductNumber": "M1", "Manufacturer": {"Name": "Acme"}, "Description": {"ProductDescription": "EVAL BOARD"},
            "ProductVariations": [], "Parameters": []}
    for placeholder in ("Added by hand", "Imported from DigiKey scan", "Imported from Mouser scan", ""):
        inv = Inv(placeholder)
        enrich_part(inv, 1, prod)
        assert any(b.get("description") == "EVAL BOARD" for b in inv.patches), placeholder
    inv = Inv("My own words")
    enrich_part(inv, 1, prod)
    assert not any("description" in b for b in inv.patches)


class BrowseInv:
    """A few parts with specs, shaped like InvenTree's answers."""

    def __init__(self, n=14):
        self.parts = [{"pk": i, "name": f"R{i}", "description": "res", "thumbnail": None, "total_in_stock": i, "category_name": "Resistors",
                       "category": 5, "creation_date": "2026-11-01"} for i in range(1, n + 1)]
        self.params = []
        for i in range(1, n + 1):  # 14 distinct resistances, 2 tolerances, one spec only some parts have
            self.params += [{"template": 1, "model_id": i, "data": f"{i * 10} Ohms"}, {"template": 2, "model_id": i, "data": "1%" if i % 2 else "5%"}]
            if i < 3:
                self.params.append({"template": 3, "model_id": i, "data": "AEC-Q200"})

    def list(self, path, **q):
        return [{"pk": 1, "name": "Resistance"}, {"pk": 2, "name": "Tolerance"}, {"pk": 3, "name": "Qualification"}]

    def get(self, path, **q):
        if path == "parameter/":
            return {"results": self.params, "next": None}
        return {"results": self.parts}


def test_wide_browse_lists_every_value_and_gives_the_table_its_columns():
    from invscan.browse import browse, invalidate
    invalidate()
    narrow = browse(BrowseInv(), 5, "", "", {})
    assert len(next(f for f in narrow["facets"] if f["name"] == "Resistance")["values"]) == 12  # a phone sheet shows 12
    invalidate()
    wide = browse(BrowseInv(), 5, "", "", {}, wide=True)
    assert len(next(f for f in wide["facets"] if f["name"] == "Resistance")["values"]) == 14  # the panel scrolls, so it gets them all
    assert wide["columns"][:2] == ["Resistance", "Tolerance"]  # the specs most parts have come first
    row = next(p for p in wide["parts"] if p["id"] == 1)
    assert row["cols"]["Resistance"] == "10 Ohms" and row["cols"]["Tolerance"] == "1%"
    assert next(p for p in wide["parts"] if p["id"] == 9)["cols"].get("Qualification", "") == ""  # missing spec: empty cell
