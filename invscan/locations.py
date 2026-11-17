"""Bin paths like 'Cabinet A / Drawer 3 / Bin 2' <-> InvenTree stock location tree."""

import re

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


_INVENTREE_LOC = re.compile(r"^INV-SL(\d+)$")  # InvenTree's own short barcode for a stock location


def parse_label(text: str) -> int | None:
    """Location id from an invscan bin label or an InvenTree-printed location label, else None."""
    t = text.strip()
    if t.startswith(LABEL_PREFIX) and t[len(LABEL_PREFIX):].isdigit():
        return int(t[len(LABEL_PREFIX):])
    m = _INVENTREE_LOC.match(t)
    return int(m.group(1)) if m else None
