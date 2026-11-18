from invscan.supplies import ROOT, add_power_supply, models


class Inv:
    """Just enough of InvenTree for categories, parts, stock and parameters."""

    def __init__(self):
        self.cats, self.parts, self.stock, self.params, self.companies, self.mparts = [], [], [], [], [], []

    def _next(self, rows):
        return len(rows) + 1

    def list(self, path, **q):
        if path == "part/category/":
            return [{**c, "pathstring": self._path(c)} for c in self.cats]
        if path == "part/":
            rows = self.parts
            if "search" in q:
                rows = [p for p in rows if q["search"].lower() in p["name"].lower()]
            if q.get("is_template"):
                rows = [p for p in rows if p.get("is_template")]
            if "variant_of" in q:
                rows = [p for p in rows if p.get("variant_of") == q["variant_of"]]
            if "category" in q:
                rows = [p for p in rows if p["category"] == q["category"] or self._under(p["category"], q["category"])]
            return [{**p, "total_in_stock": sum(s["quantity"] for s in self.stock if s["part"] == p["pk"])} for p in rows]
        if path == "company/":
            return [c for c in self.companies if q.get("search", "").lower() in c["name"].lower()]
        if path == "company/part/manufacturer/":
            return [m for m in self.mparts if m["part"] == q.get("part")]
        if path == "stock/":
            return [s for s in self.stock if s["part"] == q.get("part")]
        if path == "location/" or path.startswith("stock/location"):
            return []
        return []  # parameters and templates

    def _path(self, c):
        return (self._path(next(x for x in self.cats if x["pk"] == c["parent"])) + "/" if c["parent"] else "") + c["name"]

    def _under(self, cat, root):
        c = next(x for x in self.cats if x["pk"] == cat)
        return c["parent"] == root or (c["parent"] is not None and self._under(c["parent"], root))

    def post(self, path, **b):
        rows = {"part/category/": self.cats, "part/": self.parts, "stock/": self.stock, "company/": self.companies,
                "company/part/manufacturer/": self.mparts}.get(path)
        if rows is None:
            return {"pk": 1}
        row = {"parent": None, **b, "pk": self._next(rows)}
        rows.append(row)
        return row

    def get(self, path, **_):
        return {}

    def patch(self, *a, **k):
        return {}


def add(inv, model="LRS-350", voltage="24", current="14.6", **kw):
    return add_power_supply(inv, model, voltage, current, kw.pop("qty", 2), kw.pop("location", 5), kw.pop("note", None), **kw)


def test_first_supply_builds_categories_template_and_variant():
    inv = Inv()
    r = add(inv, kind="AC-DC Enclosed", maker="Mean Well")
    assert r.status == "created" and r.new_part
    assert {c["name"] for c in inv.cats} >= {"Supplies", "Power Supplies", "AC-DC Enclosed"}
    template, variant = inv.parts
    assert template["is_template"] and template["name"] == "LRS-350"
    assert variant["variant_of"] == template["pk"] and variant["name"] == "LRS-350 24V"
    assert inv.stock[0]["part"] == variant["pk"] and inv.stock[0]["quantity"] == 2  # stock sits on the variant


def test_second_voltage_is_a_new_variant_of_the_same_model():
    inv = Inv()
    add(inv)
    r = add(inv, voltage="12V", current="29")
    assert r.new_part and [p["name"] for p in inv.parts] == ["LRS-350", "LRS-350 24V", "LRS-350 12V"]
    assert sum(1 for p in inv.parts if p.get("is_template")) == 1


def test_same_configuration_adds_stock_and_reports_where_else():
    inv = Inv()
    add(inv, location=5)
    r = add(inv, voltage="24 V", location=9)
    assert not r.new_part and len(inv.parts) == 2
    assert [o["location_id"] for o in r.others] == [5]  # the first line is reported as already on hand
    assert len(inv.stock) == 2


def test_models_lists_variants_with_stock():
    inv = Inv()
    add(inv, qty=3)
    add(inv, voltage="12", qty=1)
    (m,) = models(inv)
    assert m["name"] == "LRS-350" and {v["name"]: v["stock"] for v in m["variants"]} == {"LRS-350 24V": 3, "LRS-350 12V": 1}


def test_models_before_anything_is_added_is_empty():
    assert models(Inv()) == []


def test_validation():
    inv = Inv()
    assert add(inv, model=" ").status == "error"
    assert add(inv, voltage="").status == "error"
    assert add(inv, voltage="abc").status == "error"
    assert add(inv, qty=0).status == "error"
    assert add(inv, location=None, note="").status == "error"
    assert inv.parts == []  # nothing half-created


def test_watts_default_to_volts_times_amps():
    inv = Inv()
    posted = []
    orig = inv.post
    inv.post = lambda path, **b: (posted.append((path, b)), orig(path, **b))[1]
    import invscan.supplies as sup
    seen = {}
    real = sup.set_param
    sup.set_param = lambda i, pid, k, v, d="": seen.__setitem__(k, v)
    try:
        add(inv, voltage="24", current="14.6")
    finally:
        sup.set_param = real
    assert seen["Power (Watts)"] == "350W" and seen["Voltage - Output 1"] == "24V" and seen["Current - Output (Max)"] == "14.6A"
