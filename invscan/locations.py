"""Bin paths like 'Cabinet A / Drawer 3 / Bin 2' <-> InvenTree stock location tree."""

LABEL_PREFIX = "INVSCAN:LOC:"


def ensure_path(inv, path: str) -> int:
    parts = [p.strip() for p in path.split("/") if p.strip()]
    if not parts:
        raise ValueError("empty location path")
    parent = None
    for i, name in enumerate(parts):
        found = [l for l in inv.list("stock/location/", search=name, limit=200)
                 if l["name"].lower() == name.lower() and l["parent"] == parent]
        if found:
            parent = found[0]["pk"]
        else:
            body = dict(name=name, description="Created by invscan")
            if parent:
                body["parent"] = parent
            # only the last segment holds stock; leave intermediates non-structural to stay flexible
            parent = inv.post("stock/location/", **body)["pk"]
    return parent


def parse_label(text: str) -> int | None:
    t = text.strip()
    return int(t[len(LABEL_PREFIX):]) if t.startswith(LABEL_PREFIX) and t[len(LABEL_PREFIX):].isdigit() else None
