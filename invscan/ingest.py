"""Turn a parsed DigiKey or Mouser scan into InvenTree stock in a given location."""
from dataclasses import dataclass, field
from datetime import date

from .categories import digikey_path, ensure_category_path, misc_category
from .digikey import _norm
from .enrich import add_supplier_part, enrich_part, ensure_manufacturer_part
from .locations import ensure_path
from .notes import set_note
from .params import mark_scanned
from .parser import DK_PN, Scan

UNSORTED = "Unsorted"


@dataclass
class Result:
    status: str  # created | duplicate | error
    part_id: int | None = None
    stock_id: int | None = None
    new_part: bool = False
    message: str = ""
    others: list = field(default_factory=list)  # the same part already in stock elsewhere


def batch_key(scan: Scan) -> str:
    """One bag = one purchase line. Used to refuse double scans; empty when the label cannot tell bags apart.

    DigiKey: (sales order, load id). Newer labels print a placeholder load id (all 9s) shared by every bag in the
    order, so the DigiKey part/MID id (12Z) is added to keep bags of different parts apart.
    Mouser: (invoice, line item, PO). NXP: the bag's own id (33T)."""
    if scan.vendor == "nxp":
        return f"NXP-{scan.puid}" if scan.puid else ""
    if scan.vendor == "mouser":
        return f"MO-{scan.invoice}-{scan.line_item}-{scan.po}" if scan.invoice and scan.line_item else ""
    if not (scan.sales_order and scan.load_id):
        return ""
    key = f"DK-{scan.sales_order}-{scan.load_id}"
    if set(scan.load_id) == {"9"}:
        key += f"-{scan.digikey_part_id or scan.mpn}"
    return key


def elsewhere(inv, part_id: int, exclude: int | None = None) -> list[dict]:
    """Stock lines of this part already on hand, so you know you have it and where it lives."""
    out = []
    for s in inv.list("stock/", part=part_id, in_stock="true", location_detail="true", limit=50):
        if s["pk"] == exclude or not s.get("quantity"):
            continue
        loc = s.get("location_detail") or {}
        out.append({"stock_id": s["pk"], "path": loc.get("pathstring") or "No location", "qty": s["quantity"],
                    "location_id": s.get("location"), "unplaced": loc.get("pathstring") == "Unplaced"})
    return out


def find_part(inv, scan: Scan, product: dict | None):
    """Existing InvenTree part for this scan: (part_id, supplier_part_id), or (None, None)."""
    if scan.supplier_sku:
        sp = inv.list("company/part/", SKU=scan.supplier_sku)
        if sp:
            return sp[0]["part"], sp[0]["pk"]
    mp = inv.list("company/part/manufacturer/", MPN=scan.mpn)
    maker = product["Manufacturer"]["Name"] if product else scan.manufacturer
    if maker:  # same MPN from a different maker is a different part
        mp = [m for m in mp if _same_maker((m.get("manufacturer_detail") or {}).get("name", ""), maker)
              or str(m.get("manufacturer")) == str(_company_id(inv, maker))]
    if mp:
        return mp[0]["part"], None
    if not product and not maker:
        for p in inv.list("part/", search=scan.mpn):
            if scan.mpn.lower() in (p["name"].lower(), (p.get("IPN") or "").lower()):
                return p["pk"], None
    return None, None


def _same_maker(a: str, b: str) -> bool:
    """'NXP' and 'NXP USA Inc.' are one maker; 'Adafruit' and 'Adafruit Industries LLC' too."""
    a, b = _norm(a), _norm(b)
    return bool(a and b and (a in b or b in a))


def _company_id(inv, name: str):
    for c in inv.list("company/", search=name):
        if c["name"].lower() == name.lower():
            return c["pk"]


def unsorted_category(inv) -> int:
    for c in inv.list("part/category/", search=UNSORTED):
        if c["name"] == UNSORTED and c["parent"] is None:
            return c["pk"]
    return inv.post("part/category/", name=UNSORTED, description="Auto-created by scan, sort later")["pk"]


def ingest(inv, scan: Scan, location_id: int | None, qty: int | None = None, dk=None, note: str | None = None,
           description: str | None = None, mouser=None, category: int | None = None, manual: bool = False) -> Result:
    if not location_id and not (note or "").strip():
        return Result("error", message="no bin and no note: say where it went")
    qty = qty if qty is not None else scan.qty
    if not qty:
        return Result("error", message="no quantity in scan; supply qty")
    key = batch_key(scan)
    if key:
        dup = inv.list("stock/", batch=key)
        if dup:
            return Result("duplicate", dup[0]["part"], dup[0]["pk"], message=f"already scanned as stock #{dup[0]['pk']}")

    mouser_label, nxp_label = scan.vendor == "mouser", scan.vendor == "nxp"
    product, from_mouser = None, False
    if mouser_label and mouser is not None and getattr(mouser, "enabled", False):
        product = mouser.lookup(scan.supplier_sku or "")  # Mouser's own details for its part number
        if product:
            from_mouser = True
            scan.mpn = product["ManufacturerProductNumber"]
    if product is None and dk:
        # a Mouser PN means nothing to DigiKey, but the manufacturer name on the label settles shared MPNs
        product = dk.lookup(scan.mpn, None if mouser_label or nxp_label else scan.supplier_sku, scan.manufacturer or None)
    part_id, supplier_part = find_part(inv, scan, product)
    new_part = part_id is None
    name = scan.mpn
    maker = product["Manufacturer"]["Name"] if product else scan.manufacturer
    if new_part and maker and any(p["name"].lower() == scan.mpn.lower() for p in inv.list("part/", search=scan.mpn)):
        name = f"{scan.mpn} ({maker})"  # same MPN, different maker
    if new_part:
        origin = "Mouser" if mouser_label else "NXP" if nxp_label else "DigiKey"
        part_id = inv.post(
            "part/",
            name=name, IPN=name,
            description=description or (f"Imported from {origin} scan" if (scan.sales_order or mouser_label or nxp_label) else "Added by hand"),
            category=category or ensure_category_path(inv, digikey_path(product))
            or (misc_category(inv) if manual else unsorted_category(inv)), component=True, purchaseable=True,
        )["pk"]

    mp_id = None
    if product:
        res = enrich_part(inv, part_id, product, supplier="Mouser" if from_mouser else "Digi-Key",
                          variations=not (mouser_label or nxp_label) or from_mouser)
        skus, mp_id = res["supplier_parts"], res["manufacturer_part"]
        if scan.supplier_sku in skus:
            supplier_part = skus[scan.supplier_sku]
        elif len(skus) == 1 and not (mouser_label or nxp_label):
            supplier_part = next(iter(skus.values()))
    if nxp_label and not mp_id:
        mp_id = ensure_manufacturer_part(inv, part_id, scan.manufacturer, scan.mpn)
    if mouser_label and scan.supplier_sku:
        if not mp_id and scan.manufacturer:
            mp_id = ensure_manufacturer_part(inv, part_id, scan.manufacturer, scan.mpn)
        supplier_part = add_supplier_part(inv, part_id, "Mouser", scan.supplier_sku, "", "", mp_id)

    if not location_id:  # no bin label available: park it as 'Unplaced' with the note saying where
        location_id = ensure_path(inv, "Unplaced")

    body = dict(
        part=part_id, quantity=qty, location=location_id,
        batch=key,
        notes=set_note(" ".join(x for x in (
            f"Mouser PO {scan.po} invoice {scan.invoice} line {scan.line_item} origin {scan.country}" if mouser_label else "",
            f"DigiKey SO {scan.sales_order} invoice {scan.invoice} origin {scan.country}" if scan.sales_order and not mouser_label else "",
            f"NXP order code {scan.order_code} bag {scan.puid}" if nxp_label else "",
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
    if dk and not product and not mouser_label and getattr(dk, "ambiguous", None):
        msg = "Several makers use this part number and the label has no DigiKey PN, so details were not filled in."
    return Result("created", part_id, item["pk"], new_part, msg, [] if new_part else elsewhere(inv, part_id, item["pk"]))


def add_manual(inv, dk, name: str, description: str, qty: int, location_id: int | None, note: str | None,
               category: int | None = None, lot_code: str = "", date_code: str = "") -> Result:
    """Add a part that has no DigiKey code: by part number, or by a DigiKey part number (looked up for you).
    It is filed in `category` if given, else by DigiKey's category if the number is found there, else in
    Miscellaneous."""
    name = (name or "").strip()
    if not name:
        return Result("error", message="enter a part number")
    if not qty or qty <= 0:
        return Result("error", message="enter a quantity")
    sku = name if DK_PN.match(name) else None
    mpn = name
    if sku and dk:  # a DigiKey PN tells us the real manufacturer part number
        product = dk.lookup(sku, sku)
        if product:
            mpn = product["ManufacturerProductNumber"]
    scan = Scan(mpn=mpn, qty=int(qty), supplier_sku=sku, lot_code=(lot_code or "").strip(), date_code=(date_code or "").strip())
    return ingest(inv, scan, location_id, int(qty), dk, note, description=(description or "").strip() or None,
                  category=category, manual=True)
