"""File parts that are still in 'Unsorted' using the supplier's category tree."""
from .browse import invalidate
from .categories import digikey_path
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
    """Look up to `limit` unsorted parts at DigiKey (by DigiKey PN, else MPN plus manufacturer) and file them.
    Returns {moved, skipped, remaining, changes:[{part, to}]}."""
    uns = _unsorted(inv)
    if not uns:
        return {"moved": 0, "skipped": 0, "remaining": 0, "changes": []}
    page = inv.get("part/", category=uns["pk"], cascade="false", limit=500)
    parts = page["results"] if isinstance(page, dict) else page
    todo = [p for p in parts if not _tried(inv, p["pk"])]
    moved = skipped = 0
    changes, makers = [], {}
    for p in todo[:limit]:
        mps = inv.list("company/part/manufacturer/", part=p["pk"])
        skus = [s["SKU"] for s in inv.list("company/part/", part=p["pk"]) if DK_PN.match(s["SKU"])]
        product = None
        if (mps or skus) and dk:
            mpn = mps[0]["MPN"] if mps else p["name"]
            maker = None
            if mps:
                mid = mps[0]["manufacturer"]
                maker = makers.setdefault(mid, inv.get(f"company/{mid}/")["name"])
            product = dk.lookup(mpn, skus[0] if skus else None, maker)
        path = digikey_path(product)
        if path:
            changes.append({"part": p["name"], "to": " / ".join(path)})
            if not dry_run:
                enrich_part(inv, p["pk"], product, variations=False)  # also files it, and fills any blanks
            moved += 1
        else:
            skipped += 1
            if not dry_run:
                set_param(inv, p["pk"], TRIED, "no supplier match")
    if not dry_run:
        invalidate()
    return {"moved": moved, "skipped": skipped, "remaining": max(0, len(todo) - limit), "changes": changes, "unsorted": len(parts)}
