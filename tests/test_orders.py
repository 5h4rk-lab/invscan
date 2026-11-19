import io

import pytest

from invscan.orders import DESC, OrderError, add_items, export_file, mark_ordered, open_order


class Inv:
    def __init__(self, suppliers=None):
        self.pos, self.lines, self.sps = [], [], suppliers if suppliers is not None else {7: [{"pk": 70, "SKU": "P15BQTR-ND"}, {"pk": 71, "SKU": "P15BQCT-ND"}]}
        self.posted, self.patched = [], []

    def list(self, path, **q):
        if path == "company/":
            return [{"pk": 1, "name": "Digi-Key"}]
        if path == "order/po/":
            return [p for p in self.pos if p["status"] == q.get("status", p["status"])]
        if path == "order/po-line/":
            return [{**l, "sku": "SKU" + str(l["part"]), "mpn": "MPN", "internal_part": 7, "internal_part_name": "ERA-8AHD150V"} for l in self.lines]
        if path == "company/part/":
            return self.sps.get(q.get("part"), [])
        return []

    def get(self, path, **_):
        return {"name": "ERA-8AHD150V", "description": "RES 15 OHM"}

    def post(self, path, **b):
        self.posted.append((path, b))
        if path == "order/po/":
            po = {"pk": 5, "reference": "PO-0005", "status": 10, "supplier": 1, **b}
            self.pos.append(po)
            return po
        if path == "order/po-line/":
            ln = {"pk": 40 + len(self.lines), "notes": b.get("notes", ""), **b}
            self.lines.append(ln)
            return ln
        return {}

    def patch(self, path, **b):
        self.patched.append((path, b))
        for l in self.lines:
            if path == f"order/po-line/{l['pk']}/":
                l.update(b)


def test_first_add_starts_the_list_and_picks_cut_tape():
    inv = Inv()
    r = add_items(inv, None, [{"part_id": 7, "qty": 25}], "Little Foot rev F")
    assert r["reference"] == "PO-0005" and r["added"] == [{"part_id": 7, "qty": 25.0, "increased": False}]
    assert inv.pos[0]["description"] == DESC
    assert inv.lines[0]["part"] == 71 and inv.lines[0]["notes"] == "Little Foot rev F"  # CT-ND, not the reel


def test_a_part_already_listed_gets_more_quantity_and_both_reasons():
    inv = Inv()
    add_items(inv, None, [{"part_id": 7, "qty": 25}], "Little Foot rev F")
    r = add_items(inv, None, [{"part_id": 7, "qty": 10}], "Hover Toy")
    assert r["added"][0] == {"part_id": 7, "qty": 35.0, "increased": True} and len(inv.lines) == 1
    assert inv.lines[0]["notes"] == "Little Foot rev F, Hover Toy"
    add_items(inv, None, [{"part_id": 7, "qty": 1}], "hover toy")  # the same reason again is not repeated
    assert inv.lines[0]["notes"] == "Little Foot rev F, Hover Toy"


def test_a_part_with_no_digikey_number_is_reported_not_silently_dropped():
    inv = Inv(suppliers={})
    r = add_items(inv, None, [{"part_id": 7, "qty": 5}, {"part_id": 7, "qty": 0}])
    assert r["added"] == [] and "no Digi-Key number" in r["failed"][0]["reason"] and inv.lines == []


def test_export_is_the_sheet_digikey_takes():
    inv = Inv()
    add_items(inv, None, [{"part_id": 7, "qty": 25}], "Little Foot rev F")
    data, mime, name = export_file(inv, "csv")
    assert name == "digikey-order.csv" and data.startswith(b"\xef\xbb\xbfQuantity,Digi-Key Part Number")
    assert b"25,SKU71,MPN,RES 15 OHM,Little Foot rev F" in data
    xdata, xmime, xname = export_file(inv, "xlsx")
    from openpyxl import load_workbook
    rows = list(load_workbook(io.BytesIO(xdata)).active.iter_rows(values_only=True))
    assert xname == "digikey-order.xlsx" and rows[0][:2] == ("Quantity", "Digi-Key Part Number") and rows[1][:2] == (25, "SKU71")


def test_marking_the_list_ordered_closes_it_and_needs_an_open_list():
    inv = Inv()
    with pytest.raises(OrderError):
        mark_ordered(inv)
    assert open_order(inv) is None
    add_items(inv, None, [{"part_id": 7, "qty": 1}])
    assert mark_ordered(inv) == {"reference": "PO-0005"} and ("order/po/5/issue/", {}) in inv.posted
