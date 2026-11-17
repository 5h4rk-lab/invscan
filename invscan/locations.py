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


def normalize_room(text: str) -> str:
    """'204' -> 'Room 204'; anything already worded ('Room 204', 'Lab') is left alone."""
    t = (text or "").strip()
    return f"Room {t}" if re.fullmatch(r"\d+[A-Za-z]?", t) else t


def place_path(room: str = "", cabinet: str = "", drawer: str = "", bin_: str = "") -> str:
    parts = [normalize_room(room), (cabinet or "").strip(), (drawer or "").strip(), (bin_ or "").strip()]
    return " / ".join(p for p in parts if p)


def has_room(path: str) -> bool:
    return any(seg.strip().lower().startswith("room") for seg in path.split("/"))


def add_room(inv, location_id: int, room: str) -> dict:
    """Put the top-level place of this location (e.g. its cabinet) inside a room, creating the room if needed."""
    room = normalize_room(room)
    if not room:
        raise ValueError("room is required")
    loc = inv.get(f"stock/location/{location_id}/")
    if has_room(loc["pathstring"]):
        raise ValueError("this place is already inside a room")
    root = loc
    while root["parent"]:
        root = inv.get(f"stock/location/{root['parent']}/")
    room_id = ensure_path(inv, room)
    inv.patch(f"stock/location/{root['pk']}/", parent=room_id)
    return {"id": location_id, "path": inv.get(f"stock/location/{location_id}/")["pathstring"]}
