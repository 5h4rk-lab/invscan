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
