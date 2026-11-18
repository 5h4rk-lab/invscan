"""Parse ECIA / ISO 15434 (format 06) labels as printed on DigiKey and Mouser bags."""
import re
from dataclasses import dataclass, field

GLYPHS = {"␝": "\x1d", "␞": "\x1e", "␄": "\x04"}
_PRINTED = {"<GS>": "\x1d", "<RS>": "\x1e", "<EOT>": "\x04"}  # some decoders print control characters like this
_FIELD = re.compile(r"^(\d{0,2}[A-Z])(.*)$", re.S)
DK_PN = re.compile(r"^(?=[^-]*\d|.*-.*\d)[A-Z0-9][A-Z0-9._/+%()\-]{2,}-ND$", re.I)  # 296-19733-5-ND, 2521-IS32CG5317EVK_KIT-ND, P15BQCT-ND


class ScanError(ValueError):
    pass


@dataclass
class Scan:
    mpn: str
    vendor: str = ""  # "digikey", "mouser" or "" when unknown
    manufacturer: str = ""  # 1V (Mouser labels)
    line_item: str = ""  # 14K (Mouser labels)
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
    order_code: str = ""  # 1P on NXP labels: the 12-digit order code (12NC), not the part number
    puid: str = ""  # 33T on NXP labels: unique to one bag
    fields: dict[str, str] = field(default_factory=dict)


def _is_nxp(fields: dict[str, str]) -> bool:
    """NXP factory bags: 33T (bag id) is theirs alone; or a 12-digit order code in 1P next to a plain 30P type.
    DigiKey labels put a -ND part number in 30P and carry 12Z/13Z/1K, so they never match."""
    if "33T" in fields:
        return True
    return bool(re.fullmatch(r"\d{12}", fields.get("1P", "").replace(" ", "")) and fields.get("30P")
                and not DK_PN.match(fields["30P"]) and not any(k in fields for k in ("12Z", "13Z", "1K", "10K", "14K")))


def _nxp_scan(fields: dict[str, str]) -> Scan:
    mpn = fields.get("30P", "")
    if not mpn:
        raise ScanError("no part type (30P) in NXP label")
    q = fields.get("Q", "")
    return Scan(mpn=mpn, vendor="nxp", manufacturer="NXP", qty=int(q) if q.isdigit() else None,
                order_code=fields.get("1P", "").replace(" ", ""), puid=fields.get("33T", ""),
                lot_code=fields.get("1T", ""), date_code=fields.get("9D", ""), fields=fields)


def parse_scan(raw: str) -> Scan:
    for g, c in GLYPHS.items():
        raw = raw.replace(g, c)
    for g, c in _PRINTED.items():
        raw = re.sub(re.escape(g), c, raw, flags=re.I)
    raw = raw.strip("\x04\x1e\x1d \r\n")
    if raw.startswith(">[)>"):  # Mouser prints a literal '>' before the ISO 15434 header
        raw = raw[1:]
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
    if _is_nxp(fields):  # the part number is the type (30P); 1P is NXP's own order code
        return _nxp_scan(fields)
    vendor = "mouser" if ("14K" in fields or ("1V" in fields and not mpn)) else ("digikey" if ("12Z" in fields or "30P" in fields or "13Z" in fields) else "")
    if not mpn and vendor != "mouser":
        raise ScanError("no manufacturer part number (1P) in scan")
    q = fields.get("Q", "")
    cust = fields.get("P", "")
    sku = fields.get("30P") or None
    if not sku and DK_PN.match(cust):  # some labels carry DigiKey's own PN in the customer-part field
        sku, cust = cust, ""
    return Scan(
        mpn=mpn,
        vendor=vendor,
        manufacturer=fields.get("1V", ""),
        line_item=fields.get("14K", ""),
        qty=int(q) if q.isdigit() else None,
        supplier_sku=sku,
        customer_ref=cust,
        po=fields.get("K", ""),
        sales_order=fields.get("1K", ""),
        invoice=fields.get("11K", "") if vendor == "mouser" else fields.get("10K", ""),
        country=fields.get("4L", ""),
        digikey_part_id=fields.get("12Z", ""),
        load_id=fields.get("13Z", ""),
        lot_code=fields.get("1T", ""),
        date_code=fields.get("9D", ""),
        fields=fields,
    )
