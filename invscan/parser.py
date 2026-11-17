"""Parse ECIA / ISO 15434 (format 06) labels as printed on DigiKey bags."""
import re
from dataclasses import dataclass, field

GLYPHS = {"␝": "\x1d", "␞": "\x1e", "␄": "\x04"}
_FIELD = re.compile(r"^(\d{0,2}[A-Z])(.*)$", re.S)
_DK_PN = re.compile(r"^\d{1,6}-[A-Z0-9][A-Z0-9./\-]*-ND$", re.I)  # e.g. 296-19733-5-ND


class ScanError(ValueError):
    pass


@dataclass
class Scan:
    mpn: str
    qty: int | None = None
    supplier_sku: str | None = None  # DigiKey PN (30P) - absent on older labels
    customer_ref: str = ""
    po: str = ""
    sales_order: str = ""
    invoice: str = ""
    country: str = ""
    digikey_part_id: str = ""
    load_id: str = ""
    lot_code: str = ""
    date_code: str = ""
    fields: dict[str, str] = field(default_factory=dict)


def parse_scan(raw: str) -> Scan:
    for g, c in GLYPHS.items():
        raw = raw.replace(g, c)
    raw = raw.strip("\x04\x1e\x1d \r\n")
    if raw.startswith("[)>"):
        raw = raw[3:].lstrip("\x1e")
        if raw.startswith("06"):
            raw = raw[2:]
    elif "\x1d" not in raw and not re.match(r"^\d{0,2}[A-Z]", raw):
        raise ScanError("not an ECIA label")

    fields: dict[str, str] = {}
    for part in raw.split("\x1d"):
        if not part:
            continue
        m = _FIELD.match(part)
        if m:
            fields.setdefault(m.group(1), m.group(2).strip("\x00").strip())
    if not fields:
        raise ScanError("no fields found")

    mpn = fields.get("1P", "")
    if not mpn:
        raise ScanError("no manufacturer part number (1P) in scan")
    q = fields.get("Q", "")
    cust = fields.get("P", "")
    sku = fields.get("30P") or None
    if not sku and _DK_PN.match(cust):  # some labels carry DigiKey's own PN in the customer-part field
        sku, cust = cust, ""
    return Scan(
        mpn=mpn,
        qty=int(q) if q.isdigit() else None,
        supplier_sku=sku,
        customer_ref=cust,
        po=fields.get("K", ""),
        sales_order=fields.get("1K", ""),
        invoice=fields.get("10K", ""),
        country=fields.get("4L", ""),
        digikey_part_id=fields.get("12Z", ""),
        load_id=fields.get("13Z", ""),
        lot_code=fields.get("1T", ""),
        date_code=fields.get("9D", ""),
        fields=fields,
    )
