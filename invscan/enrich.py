"""Fill an InvenTree part with supplier data (DigiKey or Mouser): description, manufacturer, SKUs, image, links."""
import requests

from .categories import digikey_path, ensure_category_path
from .params import set_digikey_params


def _company(inv, name, **flags):
    for c in inv.list("company/", search=name):
        if c["name"].lower() == name.lower():
            if not all(c.get(k) for k in flags):
                inv.patch(f"company/{c['pk']}/", **flags)
            return c["pk"]
    return inv.post("company/", name=name, **flags)["pk"]


def _params(product, limit=40) -> list[tuple[str, str]]:
    return [(x["ParameterText"], x["ValueText"]) for x in product.get("Parameters", [])][:limit]


def pick_description(product: dict) -> str:
    """DigiKey cuts ProductDescription at 32 chars; when that happened prefer the detailed text."""
    d = product.get("Description", {})
    short, long = d.get("ProductDescription", ""), d.get("DetailedDescription", "")
    return (long if len(short) >= 32 and long else short)[:250]


def fetch_image(url: str) -> tuple[bytes, str] | None:
    """(bytes, file extension) of the picture at url, or None when it is not really a picture. Some sites, Mouser's
    among them, answer 'OK' with a bot-check web page when a script downloads an image; that is never stored, and we
    do not try to get around it."""
    if not url or not url.startswith("http"):
        return None
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    except requests.RequestException:
        return None
    if not r.ok:
        return None
    for magic, ext in ((b"\xff\xd8\xff", "jpg"), (b"\x89PNG\r\n\x1a\n", "png"), (b"GIF8", "gif")):
        if r.content.startswith(magic):
            return r.content, ext
    return None


def set_image(inv, part_id: int, name: str, url: str) -> bool:
    """Give the part this picture if it can be fetched and InvenTree accepts it. True when it worked."""
    got = fetch_image(url)
    if not got:
        return False
    try:
        inv.patch_file(f"part/{part_id}/", "image", f"{name}.{got[1]}", got[0])
    except RuntimeError:
        return False
    return True


def ensure_manufacturer_part(inv, part_id: int, manufacturer: str, mpn: str) -> int:
    """The manufacturer part (company + MPN) for this part, created if missing."""
    mfr = _company(inv, manufacturer, is_manufacturer=True)
    mp = inv.list("company/part/manufacturer/", part=part_id, MPN=mpn)
    return mp[0]["pk"] if mp else inv.post("company/part/manufacturer/", part=part_id, manufacturer=mfr, MPN=mpn)["pk"]


def add_supplier_part(inv, part_id: int, supplier_name: str, sku: str, link: str = "", description: str = "",
                      manufacturer_part: int | None = None) -> int:
    """A supplier part (supplier + SKU) for this part, created if missing. Returns its id."""
    sp = inv.list("company/part/", part=part_id, SKU=sku)
    if sp:
        return sp[0]["pk"]
    body = dict(part=part_id, supplier=_company(inv, supplier_name, is_supplier=True), SKU=sku, link=link, description=description)
    if manufacturer_part:
        body["manufacturer_part"] = manufacturer_part
    return inv.post("company/part/", **body)["pk"]


def enrich_part(inv, part_id: int, product: dict, supplier: str = "Digi-Key", variations: bool = True) -> dict:
    """Returns {'supplier_parts': {sku: pk}, 'manufacturer_part': pk}. Safe to call repeatedly.

    `product` has DigiKey's shape (Mouser results are converted to it). With variations=False no supplier
    parts are created from it (used when its data comes from a different supplier than the bag)."""
    part = inv.get(f"part/{part_id}/")
    mpn = product["ManufacturerProductNumber"]
    desc = pick_description(product)
    cat = product.get("Category", {}).get("Name", "")
    kw = " ".join(dict.fromkeys([mpn, product["Manufacturer"]["Name"], cat, *(v for _, v in _params(product, 8))]))

    upd = {}
    path = digikey_path(product)
    if path and part.get("category_name") in (None, "", "Unsorted"):  # never move a part you filed yourself
        cat = ensure_category_path(inv, path)
        if cat:
            upd["category"] = cat
    if not part.get("description") or part["description"].startswith(("Imported from", "Added by hand")):
        upd["description"] = desc[:250]
    if not part.get("keywords"):
        upd["keywords"] = kw[:250]
    if not part.get("link") and product.get("DatasheetUrl", "").startswith("http"):
        upd["link"] = product["DatasheetUrl"]
    if upd:
        inv.patch(f"part/{part_id}/", **upd)

    if not part.get("image") and product.get("PhotoUrl"):
        set_image(inv, part_id, mpn, product["PhotoUrl"])

    mp_id = ensure_manufacturer_part(inv, part_id, product["Manufacturer"]["Name"], mpn)

    skus = {}
    for v in (product.get("ProductVariations", []) if variations else []):
        sku = v["DigiKeyProductNumber"]
        skus[sku] = add_supplier_part(inv, part_id, supplier, sku, product.get("ProductUrl", ""),
                                      v.get("PackageType", {}).get("Name", ""), mp_id)
    set_digikey_params(inv, part_id, product)
    return {"supplier_parts": skus, "manufacturer_part": mp_id}
