"""Fill an InvenTree part with DigiKey data: description, manufacturer, SKUs, image, links."""
import requests

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


def enrich_part(inv, part_id: int, product: dict) -> dict:
    """Returns {'supplier_parts': {sku: pk}}. Safe to call repeatedly."""
    part = inv.get(f"part/{part_id}/")
    mpn = product["ManufacturerProductNumber"]
    desc = pick_description(product)
    cat = product.get("Category", {}).get("Name", "")
    kw = " ".join(dict.fromkeys([mpn, product["Manufacturer"]["Name"], cat, *(v for _, v in _params(product, 8))]))

    upd = {}
    if not part.get("description") or part["description"].startswith("Imported from"):
        upd["description"] = desc[:250]
    if not part.get("keywords"):
        upd["keywords"] = kw[:250]
    if not part.get("link") and product.get("DatasheetUrl", "").startswith("http"):
        upd["link"] = product["DatasheetUrl"]
    if upd:
        inv.patch(f"part/{part_id}/", **upd)

    if not part.get("image") and product.get("PhotoUrl"):
        try:
            img = requests.get(product["PhotoUrl"], timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            img.raise_for_status()
            inv.patch_file(f"part/{part_id}/", "image", f"{mpn}.jpg", img.content)
        except (requests.RequestException, RuntimeError):
            pass  # picture is a nicety

    mfr = _company(inv, product["Manufacturer"]["Name"], is_manufacturer=True)
    mp = inv.list("company/part/manufacturer/", part=part_id, MPN=mpn)
    mp_id = mp[0]["pk"] if mp else inv.post("company/part/manufacturer/", part=part_id, manufacturer=mfr, MPN=mpn)["pk"]

    supplier = _company(inv, "Digi-Key", is_supplier=True)
    skus = {}
    for v in product.get("ProductVariations", []):
        sku = v["DigiKeyProductNumber"]
        sp = inv.list("company/part/", part=part_id, SKU=sku)
        skus[sku] = sp[0]["pk"] if sp else inv.post(
            "company/part/", part=part_id, supplier=supplier, SKU=sku, manufacturer_part=mp_id,
            link=product.get("ProductUrl", ""), description=v.get("PackageType", {}).get("Name", ""))["pk"]
    set_digikey_params(inv, part_id, product)
    return {"supplier_parts": skus}
