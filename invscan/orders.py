"""The next DigiKey order: one draft purchase order in InvenTree that parts are added to as you notice you need them,
exported as a sheet DigiKey's "Upload a List" takes."""
import csv
import io

from .enrich import add_supplier_part

DESC = "Next DigiKey order"
PENDING, PLACED = 10, 20  # InvenTree purchase order states


class OrderError(ValueError):
    """The part cannot go on the list (no DigiKey number found); the message is safe to show."""


def digikey_id(inv) -> int:
    for c in inv.list("company/", search="digi", limit=20):
        if c["name"].lower().replace("-", "").replace(" ", "") == "digikey":
            return c["pk"]
    return inv.post("company/", name="Digi-Key", is_supplier=True)["pk"]


def open_order(inv, create: bool = False) -> dict | None:
    """The draft order that is collecting parts, or None (made on first use when create is true)."""
    dk = digikey_id(inv)
    for po in inv.list("order/po/", status=PENDING, limit=100):
        if po.get("description") == DESC and po.get("supplier") == dk:
            return po
    return inv.post("order/po/", supplier=dk, description=DESC) if create else None


def _rank(sku: str) -> int:
    s = sku.upper()  # small quantities: cut tape first; tape-and-reel and Digi-Reel last
    return 0 if s.endswith("CT-ND") else 2 if s.endswith(("TR-ND", "DKR-ND")) else 1


def supplier_part(inv, dk, part_id: int, supplier: int) -> int:
    """The Digi-Key supplier part to order for this part, found or made from DigiKey's record of its manufacturer part."""
    for attempt in (0, 1):
        sps = inv.list("company/part/", part=part_id, supplier=supplier, limit=50)
        if sps:
            return min(sps, key=lambda s: _rank(s["SKU"]))["pk"]
        if attempt:
            break
        mps = inv.list("company/part/manufacturer/", part=part_id, manufacturer_detail="true", limit=5)
        part = inv.get(f"part/{part_id}/")
        mpn = mps[0]["MPN"] if mps else part["name"]
        maker = ((mps[0].get("manufacturer_detail") or {}).get("name") if mps else None)
        product = dk.lookup(mpn, None, maker) if dk else None
        if not product:
            raise OrderError(f"{part['name']} has no Digi-Key number and DigiKey does not know it. Add a Digi-Key part number on its page first.")
        mp = mps[0]["pk"] if mps else None
        for v in product.get("ProductVariations", []):
            add_supplier_part(inv, part_id, "Digi-Key", v["DigiKeyProductNumber"], product.get("ProductUrl", ""),
                              v.get("PackageType", {}).get("Name", ""), mp)
    raise OrderError("No Digi-Key number could be set up for that part.")


def add_items(inv, dk, items: list[dict], note: str = "") -> dict:
    """items: [{part_id, qty}]. A part already on the list gets its quantity increased. Returns what happened to each."""
    po = open_order(inv, create=True)
    dkid = po["supplier"]
    lines = {l["part"]: l for l in inv.list("order/po-line/", order=po["pk"], limit=1000)}
    added, failed = [], []
    for it in items:
        qty = float(it.get("qty") or 0)
        if qty <= 0:
            continue
        try:
            spk = supplier_part(inv, dk, int(it["part_id"]), dkid)
        except OrderError as e:
            failed.append({"part_id": it["part_id"], "reason": str(e)})
            continue
        n = (note or it.get("note") or "").strip()
        if spk in lines:
            old = lines[spk]
            notes = old.get("notes") or ""
            if n and n.lower() not in notes.lower():
                notes = f"{notes}, {n}" if notes else n
            inv.patch(f"order/po-line/{old['pk']}/", quantity=float(old["quantity"]) + qty, notes=notes[:500])
            added.append({"part_id": it["part_id"], "qty": float(old["quantity"]) + qty, "increased": True})
        else:
            ln = inv.post("order/po-line/", order=po["pk"], part=spk, quantity=qty, notes=n[:500])
            lines[spk] = ln
            added.append({"part_id": it["part_id"], "qty": qty, "increased": False})
    return {"order": po["pk"], "reference": po.get("reference"), "added": added, "failed": failed}


def list_lines(inv) -> dict:
    po = open_order(inv)
    if not po:
        return {"id": None, "reference": None, "lines": []}
    rows = inv.list("order/po-line/", order=po["pk"], part_detail="true", limit=1000)
    lines = [{"id": r["pk"], "sku": r.get("sku") or (r.get("part_detail") or {}).get("SKU", ""), "mpn": r.get("mpn") or "",
              "part_id": r.get("internal_part"), "name": r.get("internal_part_name") or "", "qty": float(r["quantity"]),
              "note": r.get("notes") or ""} for r in rows]
    return {"id": po["pk"], "reference": po.get("reference"), "lines": sorted(lines, key=lambda l: l["name"].lower())}


def export_rows(inv) -> list[list]:
    """The sheet DigiKey's Upload a List takes: quantity and part number are what it needs; the rest helps you read it."""
    out = [["Quantity", "Digi-Key Part Number", "Manufacturer Part Number", "Description", "Customer Reference"]]
    for l in list_lines(inv)["lines"]:
        desc = ""
        if l["part_id"]:
            desc = (inv.get(f"part/{l['part_id']}/").get("description") or "")
        out.append([int(l["qty"]) if l["qty"] == int(l["qty"]) else l["qty"], l["sku"], l["mpn"], desc, l["note"]])
    return out


def export_file(inv, fmt: str = "xlsx") -> tuple[bytes, str, str]:
    rows = export_rows(inv)
    if fmt == "csv":
        buf = io.StringIO()
        csv.writer(buf).writerows(rows)
        return buf.getvalue().encode("utf-8-sig"), "text/csv", "digikey-order.csv"  # the BOM makes Excel read it as UTF-8
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "DigiKey order"
    for r in rows:
        ws.append(r)
    for c in ws[1]:
        c.font = Font(bold=True)
    for col, w in zip("ABCDE", (10, 26, 28, 50, 30)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "digikey-order.xlsx"


def set_quantity(inv, line_id: int, qty: float) -> None:
    inv.patch(f"order/po-line/{line_id}/", quantity=qty)


def remove_line(inv, line_id: int) -> None:
    inv.delete(f"order/po-line/{line_id}/")


def mark_ordered(inv) -> dict:
    """The order has been placed with DigiKey: close this list so the next part added starts a fresh one."""
    po = open_order(inv)
    if not po:
        raise OrderError("There is no open list.")
    inv.post(f"order/po/{po['pk']}/issue/")
    return {"reference": po.get("reference")}
