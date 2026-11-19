import io

import pytest

from invscan.bom import BomError, build_status, create_build, match_lines, parse_bom

KICAD = (b'"Refs","Value","Footprint","Qty","DNP"\n'
         b'"C1, C2, C3","100nF","C_0603","3",""\n'
         b'"R1","10k","R_0603","1",""\n'
         b'"U1","MSP430F2012TN","DIP-14","1",""\n'
         b'"TP1","TestPoint","TP","1","DNP"\n')


def test_kicad_csv_is_read_and_do_not_populate_rows_are_left_out():
    r = parse_bom(KICAD, "little_foot_rev_f.csv")
    assert [l["value"] for l in r["lines"]] == ["100nF", "10k", "MSP430F2012TN"] and r["skipped"] == 1
    assert r["lines"][0]["qty"] == 3 and r["lines"][0]["refs"] == ["C1", "C2", "C3"]


def test_columns_are_found_by_name_with_title_rows_above_and_semicolons():
    sheet = (b"Little Foot rev F;;;;\nExported 2026-11-18;;;;\nDesignator;Quantity;Manufacturer;Manufacturer Part Number;Digi-Key Part Number\n"
             b"R1;2;Panasonic;ERA-8AHD150V;P15BQCT-ND\nU1;1;NXP;MC9S08PA60AVLF;\nU2;1;NXP;MC9S08PA60AVLF;\n")
    r = parse_bom(sheet, "bom.csv")
    a, b = r["lines"]
    assert (a["qty"], a["dk_pn"], a["mpn"], a["maker"]) == (2, "P15BQCT-ND", "ERA-8AHD150V", "Panasonic")
    assert b["mpn"] == "MC9S08PA60AVLF" and b["qty"] == 2 and b["refs"] == ["U1", "U2"]  # the same part on two rows: one line


def test_a_digikey_number_in_the_part_number_column_or_any_column_is_noticed():
    r = parse_bom(b"Qty,Part Number,Notes\n5,296-19733-5-ND,\n2,LM358DR,order 1528-4939-ND\n", "b.csv")
    assert r["lines"][0]["dk_pn"] == "296-19733-5-ND" and r["lines"][0]["mpn"] == ""
    assert r["lines"][1]["dk_pn"] == "1528-4939-ND" and r["lines"][1]["mpn"] == "LM358DR"


def test_quantity_is_counted_from_the_references_when_missing():
    r = parse_bom(b"Reference,Value,Qty\n\"R1,R2,R3\",10k,\n", "b.csv")
    assert r["lines"][0]["qty"] == 3


def test_xlsx_workbooks_are_read():
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    ws.append(["Project", "Little Foot"]); ws.append([])
    ws.append(["Reference", "Qty", "MPN"]); ws.append(["U1", 1, "MSP430F2012TN"]); ws.append(["R1, R2", 2.0, "ERA-8AHD150V"])
    buf = io.BytesIO(); wb.save(buf)
    r = parse_bom(buf.getvalue(), "bom.xlsx")
    assert [(l["mpn"], l["qty"]) for l in r["lines"]] == [("MSP430F2012TN", 1), ("ERA-8AHD150V", 2)]


def test_bad_sheets_say_what_to_do():
    with pytest.raises(BomError, match="xlsx or .csv"):
        parse_bom(b"x", "bom.xls")
    with pytest.raises(BomError, match="find the columns"):
        parse_bom(b"hello,world\n1,2\n", "bom.csv")
    with pytest.raises(BomError, match="No parts"):
        parse_bom(b"Qty,MPN\n", "bom.csv")


class Inv:
    """Parts, supplier parts, manufacturer parts and a BOM, shaped like InvenTree's answers."""

    def __init__(self):
        self.parts = {1: {"pk": 1, "name": "MSP430F2012TN", "IPN": "", "thumbnail": None, "description": "MCU"},
                      2: {"pk": 2, "name": "ERA-8AHD150V", "IPN": "", "thumbnail": "t.png", "description": "res"},
                      3: {"pk": 3, "name": "100nF 0603 cap", "IPN": "", "thumbnail": None, "description": "cap 100nF"}}
        self.posted, self.bom = [], []

    def list(self, path, **q):
        if path == "company/part/":
            return [{"part": 2}] if q.get("SKU") == "P15BQCT-ND" else []
        if path == "company/part/manufacturer/":
            return [{"part": 1}] if q.get("MPN") == "MSP430F2012TN" else []
        if path == "part/":
            if q.get("assembly"):
                return []
            s = q.get("search", "").lower()
            return [p for p in self.parts.values() if s in p["name"].lower() or s in p["description"].lower()]
        if path == "bom/":
            return self.bom
        return []

    def get(self, path, **_):
        return self.parts[int(path.strip("/").split("/")[1])] if path.startswith("part/") else {}

    def post(self, path, **b):
        self.posted.append((path, b))
        return {"pk": 100 + len(self.posted)}


def test_lines_are_matched_by_digikey_number_then_part_number_and_the_rest_get_suggestions():
    lines = parse_bom(b"Qty,MPN,Digi-Key Part Number,Value\n2,,P15BQCT-ND,15\n1,MSP430F2012TN,,\n3,,,100nF\n", "b.csv")["lines"]
    a, b, c = match_lines(Inv(), lines)
    assert (a["part_id"], a["how"]) == (2, "Digi-Key number") and a["part_name"] == "ERA-8AHD150V"
    assert (b["part_id"], b["how"]) == (1, "manufacturer part number")
    assert c["part_id"] is None and [x["name"] for x in c["candidates"]] == ["100nF 0603 cap"]  # a person picks it


def test_kicad_puts_the_part_number_in_the_value_column_and_that_still_matches():
    lines = parse_bom(b"Refs,Value,Footprint,Qty\nU1,MSP430F2012TN,DIP-14,1\n", "b.csv")["lines"]
    (a,) = match_lines(Inv(), lines)
    assert a["part_id"] == 1 and a["how"] == "value" and a["part_name"] == "MSP430F2012TN"


def test_creating_a_build_makes_an_assembly_with_one_bom_line_per_part():
    inv = Inv()
    r = create_build(inv, None, "Little Foot rev F", [
        {"part_id": 1, "qty": 1, "refs": ["U1"], "value": "MSP430"}, {"part_id": 3, "qty": 2, "refs": ["C1", "C2"]},
        {"part_id": 3, "qty": 1, "refs": ["C3"]}, {"skip": True, "qty": 1}, {"qty": 4}])
    assert r["lines"] == 2 and r["skipped"] == 2
    asm = next(b for p, b in inv.posted if p == "part/" and b.get("assembly"))
    assert asm["name"] == "Little Foot rev F" and asm["assembly"] is True
    boms = [b for p, b in inv.posted if p == "bom/"]
    assert {(b["sub_part"], b["quantity"], b["reference"]) for b in boms} == {(1, 1.0, "U1"), (3, 3.0, "C1, C2, C3")}


def test_a_build_name_cannot_be_reused_and_needs_at_least_one_part():
    inv = Inv()
    inv.parts[9] = {"pk": 9, "name": "Little Foot rev F", "IPN": "", "thumbnail": None, "description": ""}
    with pytest.raises(BomError, match="already exists"):
        create_build(inv, None, "little foot rev f", [{"part_id": 1, "qty": 1}])
    with pytest.raises(BomError, match="None of the lines"):
        create_build(Inv(), None, "New", [{"skip": True, "qty": 1}])
    with pytest.raises(BomError, match="name"):
        create_build(Inv(), None, "  ", [{"part_id": 1, "qty": 1}])


def bom_row(pk, sub, name, per, have, on_order=0, optional=False):
    return {"pk": pk, "sub_part": sub, "quantity": per, "available_stock": have, "available_substitute_stock": 0, "available_variant_stock": 0,
            "on_order": on_order, "optional": optional, "reference": "R1", "note": "", "sub_part_detail": {"name": name, "description": "", "thumbnail": None}}


def test_build_status_says_how_many_boards_the_parts_on_hand_make_and_what_is_missing():
    inv = Inv()
    inv.parts[50] = {"pk": 50, "name": "Little Foot", "description": ""}
    inv.bom = [bom_row(1, 1, "MCU", 1, 3), bom_row(2, 2, "Resistor", 4, 9), bom_row(3, 3, "Cap", 2, 1, on_order=10), bom_row(4, 4, "Spare", 1, 0, optional=True)]
    s = build_status(inv, 50, 1)
    assert s["can_build"] == 0 and s["complete"] is False  # one cap on hand, two needed
    assert [(l["name"], l["status"]) for l in s["lines"]] == [("Cap", "ordered"), ("MCU", "ok"), ("Resistor", "ok"), ("Spare", "optional")]
    assert s["missing"] == 1 and s["short"] == 0  # the cap is already on an order
    s3 = build_status(inv, 50, 3)  # three boards: 12 resistors, 6 caps, 3 MCUs
    assert {l["name"]: l["short"] for l in s3["lines"]} == {"MCU": 0, "Resistor": 3, "Cap": 5, "Spare": 3}
    assert next(l for l in s3["lines"] if l["name"] == "Resistor")["status"] == "short" and s3["short"] == 1
    inv.bom = [bom_row(1, 1, "MCU", 1, 3), bom_row(2, 2, "Resistor", 4, 9)]
    ok = build_status(inv, 50, 2)
    assert ok["can_build"] == 2 and ok["complete"] and ok["missing"] == 0  # floor(9/4) = 2 boards
