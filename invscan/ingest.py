"""Turn a parsed DigiKey scan into InvenTree stock in a given location."""
from dataclasses import dataclass
from datetime import date

from .enrich import enrich_part
from .locations import ensure_path
from .notes import set_note
from .params import mark_scanned
from .parser import Scan

UNSORTED = "Unsorted"


@dataclass
class Result:
    status: str  # created | duplicate | error
    part_id: int | None = None
    stock_id: int | None = None
    new_part: bool = False
    message: str = ""


def batch_key(scan: Scan) -> str:
    """One DigiKey bag = one (sales order, load id). Used to refuse double scans.

    Newer labels print a placeholder load id (all 9s) shared by every bag in the order, so
    for those the DigiKey part/MID id (12Z) is added to keep bags of different parts apart."""
    key = f"DK-{scan.sales_order}-{scan.load_id}"
    if scan.load_id and set(scan.load_id) == {"9"}:
        key += f"-{scan.digikey_part_id or scan.mpn}"
    return key


def find_part(inv, scan: Scan, product: dict | None):
    """Existing InvenTree part for this scan: (part_id, supplier_part_id), or (None, None)."""
    if scan.supplier_sku:
        sp = inv.list("company/part/", SKU=scan.supplier_sku)
        if sp:
            return sp[0]["part"], sp[0]["pk"]
    mp = inv.list("company/part/manufacturer/", MPN=scan.mpn)
    if product:  # same MPN from a different maker is a different part
        want = product["Manufacturer"]["Name"].lower()
        mp = [m for m in mp if (m.get("manufacturer_detail") or {}).get("name", "").lower() == want
              or str(m.get("manufacturer")) == str(_company_id(inv, want))]
    if mp:
        return mp[0]["part"], None
    if not product:
        for p in inv.list("part/", search=scan.mpn):
            if scan.mpn.lower() in (p["name"].lower(), (p.get("IPN") or "").lower()):
                return p["pk"], None
    return None, None


def _company_id(inv, name: str):
    for c in inv.list("company/", search=name):
        if c["name"].lower() == name.lower():
            return c["pk"]


def unsorted_category(inv) -> int:
    for c in inv.list("part/category/", search=UNSORTED):
        if c["name"] == UNSORTED and c["parent"] is None:
            return c["pk"]
    return inv.post("part/category/", name=UNSORTED, description="Auto-created by scan, sort later")["pk"]


def ingest(inv, scan: Scan, location_id: int | None, qty: int | None = None, dk=None, note: str | None = None) -> Result:
    if not location_id and not (note or "").strip():
        return Result("error", message="no bin and no note: say where it went")
    qty = qty if qty is not None else scan.qty
    if not qty:
        return Result("error", message="no quantity in scan; supply qty")
    key = batch_key(scan)
    if scan.sales_order and scan.load_id:
        dup = inv.list("stock/", batch=key)
        if dup:
            return Result("duplicate", dup[0]["part"], dup[0]["pk"], message=f"already scanned as stock #{dup[0]['pk']}")

    product = dk.lookup(scan.mpn, scan.supplier_sku) if dk else None
    part_id, supplier_part = find_part(inv, scan, product)
    new_part = part_id is None
    name = scan.mpn
    if new_part and product and inv.list("part/", search=scan.mpn) and any(
            p["name"].lower() == scan.mpn.lower() for p in inv.list("part/", search=scan.mpn)):
        name = f"{scan.mpn} ({product['Manufacturer']['Name']})"  # same MPN, different maker
    if new_part:
        part_id = inv.post(
            "part/",
            name=name, IPN=name, description="Imported from DigiKey scan",
            category=unsorted_category(inv), component=True, purchaseable=True,
        )["pk"]

    if product:
        skus = enrich_part(inv, part_id, product)["supplier_parts"]
        if scan.supplier_sku in skus:
            supplier_part = skus[scan.supplier_sku]
        elif len(skus) == 1:
            supplier_part = next(iter(skus.values()))

    if not location_id:  # no bin label available: park it as 'Unplaced' with the note saying where
        location_id = ensure_path(inv, "Unplaced")

    body = dict(
        part=part_id, quantity=qty, location=location_id,
        batch=key if scan.sales_order and scan.load_id else "",
        notes=set_note(" ".join(x for x in (
            f"DigiKey SO {scan.sales_order} invoice {scan.invoice} origin {scan.country}",
            f"lot {scan.lot_code}" if scan.lot_code else "",
            f"date code {scan.date_code}" if scan.date_code else "",
            f"ref {scan.customer_ref}" if scan.customer_ref else "") if x), note),
    )
    if supplier_part:
        body["supplier_part"] = supplier_part
    item = inv.post("stock/", **body)
    if isinstance(item, list):  # InvenTree >=1.x returns a list here
        item = item[0]
    try:
        mark_scanned(inv, part_id, date.today().isoformat())
    except RuntimeError:
        pass  # bookkeeping must never fail a scan
    msg = ""
    if dk and not product and getattr(dk, "ambiguous", None):
        msg = "Several makers use this part number and the label has no DigiKey PN, so details were not filled in."
    return Result("created", part_id, item["pk"], new_part, msg)
