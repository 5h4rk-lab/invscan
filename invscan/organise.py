"""File parts that are still in 'Unsorted' using the supplier's category tree."""
from .browse import invalidate
from .categories import digikey_path, misc_category
from .enrich import enrich_part
from .params import _template, set_param
from .parser import DK_PN

TRIED = "Category lookup"  # remembered so parts with no supplier data are not looked up again and again


def _unsorted(inv):
    return next((c for c in inv.list("part/category/", search="Unsorted", limit=50)
                 if c["name"] == "Unsorted" and not c["parent"]), None)


def _tried(inv, part_id: int) -> bool:
    tpl = _template(inv, TRIED, "Set when invscan has already tried to find a category")
    return any(p["template"] == tpl for p in inv.list("parameter/", model_type="part.part", model_id=part_id, limit=100))


def organise(inv, dk, limit: int = 10, dry_run: bool = False) -> dict:
    """File up to `limit` Unsorted parts. A part with a DigiKey record goes into DigiKey's category (looked up by
    DigiKey PN, else MPN plus manufacturer). A part with no supplier record at all (a laptop, a hand-made board) goes
    to Miscellaneous. A supplier part DigiKey does not know is remembered so it is not looked up again and again.
    Returns {moved, misc, skipped, remaining, unsorted, changes:[{part, to}]}."""
    uns = _unsorted(inv)
    if not uns:
        return {"moved": 0, "misc": 0, "skipped": 0, "remaining": 0, "unsorted": 0, "changes": []}
    page = inv.get("part/", category=uns["pk"], cascade="false", limit=500)
    parts = page["results"] if isinstance(page, dict) else page
    moved = misc = skipped = done = 0
    changes, makers = [], {}
    for idx, p in enumerate(parts):
        if done >= limit:
            break
        mps = inv.list("company/part/manufacturer/", part=p["pk"])
        skus = [s["SKU"] for s in inv.list("company/part/", part=p["pk"]) if DK_PN.match(s["SKU"])]
        if not mps and not skus:
            done += 1
            misc += 1
            changes.append({"part": p["name"], "to": "Miscellaneous"})
            if not dry_run:
                inv.patch(f"part/{p['pk']}/", category=misc_category(inv))
            continue
        if _tried(inv, p["pk"]):
            continue
        done += 1
        product = None
        if dk:
            mpn = mps[0]["MPN"] if mps else p["name"]
            maker = None
            if mps:
                mid = mps[0]["manufacturer"]
                maker = makers.setdefault(mid, inv.get(f"company/{mid}/")["name"])
            product = dk.lookup(mpn, skus[0] if skus else None, maker)
        path = digikey_path(product)
        if path:
            moved += 1
            changes.append({"part": p["name"], "to": " / ".join(path)})
            if not dry_run:
                enrich_part(inv, p["pk"], product, variations=False)  # also files it, and fills any blanks
        else:
            skipped += 1
            if not dry_run:
                set_param(inv, p["pk"], TRIED, "no supplier match")
    remaining = max(0, len(parts) - (idx + 1)) if done >= limit else 0
    if not dry_run:
        invalidate()
    return {"moved": moved, "misc": misc, "skipped": skipped, "remaining": remaining, "changes": changes, "unsorted": len(parts)}
