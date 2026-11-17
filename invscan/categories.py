"""Mirror a supplier's category tree (DigiKey's, e.g. Capacitors > Aluminum - Polymer Capacitors) in InvenTree."""


def digikey_path(product: dict | None) -> list[str]:
    """Category names from the top level down. DigiKey nests the chain in ChildCategories; Mouser results are flat."""
    names, c = [], (product or {}).get("Category")
    while c:
        if c.get("Name"):
            names.append(c["Name"])
        kids = c.get("ChildCategories") or []
        c = kids[0] if kids else None
    return names


def _clean(name: str) -> str:
    return " ".join(name.replace("/", "-").split())[:100]  # '/' separates levels in InvenTree paths


def ensure_category_path(inv, names: list[str]) -> int | None:
    """The id of the deepest category in `names`, creating any that are missing. None for an empty path."""
    names = [_clean(n) for n in names if n and n.strip()]
    if not names:
        return None
    existing = {(c["parent"], c["name"].lower()): c["pk"] for c in inv.list("part/category/", limit=1000)}
    parent = None
    for n in names:
        key = (parent, n.lower())
        if key not in existing:
            body = {"name": n, "description": "From the supplier's category tree"}
            if parent:
                body["parent"] = parent
            existing[key] = inv.post("part/category/", **body)["pk"]
        parent = existing[key]
    return parent


def list_categories(inv) -> list[dict]:
    return [{"id": c["pk"], "name": c["name"], "parent": c["parent"], "count": c.get("part_count", 0),
             "path": c.get("pathstring", c["name"])} for c in inv.list("part/category/", limit=1000)]
