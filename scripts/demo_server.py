"""Preview the invscan pages with sample data: no InvenTree, DigiKey or PIN needed.

    python scripts/demo_server.py          # then open http://127.0.0.1:8800

Serves public/ exactly as the real server does, with a canned API behind it. Nothing is saved."""
import html
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="invscan demo")

CATS = [  # id, name, parent, path
    (1, "Integrated Circuits (ICs)", None, "Integrated Circuits (ICs)"), (2, "Embedded", 1, "Integrated Circuits (ICs)/Embedded"),
    (3, "Microcontrollers", 2, "Integrated Circuits (ICs)/Embedded/Microcontrollers"), (4, "Resistors", None, "Resistors"),
    (5, "Chip Resistor - Surface Mount", 4, "Resistors/Chip Resistor - Surface Mount"), (6, "Capacitors", None, "Capacitors"),
    (7, "Aluminum Organic Polymer Capacitors", 6, "Capacitors/Aluminum Organic Polymer Capacitors"),
    (8, "Circuit Protection", None, "Circuit Protection"), (9, "TVS Diodes", 8, "Circuit Protection/TVS Diodes"),
    (10, "Supplies", None, "Supplies"), (11, "Power Supplies", 10, "Supplies/Power Supplies"),
    (12, "AC-DC Enclosed", 11, "Supplies/Power Supplies/AC-DC Enclosed"), (13, "Miscellaneous", None, "Miscellaneous"),
]
BIN = "Room 127/Cabinet #3/Drawer 1"
PARTS = {  # id: name, description, category id, kind (thumbnail), specs, stock [(path, qty, note)]
    1: ("MC9S08PA60AVLF", "IC MCU 8BIT 60KB FLASH 48LQFP", 3, "ic", [("Core Processor", "S08"), ("Program Memory Size", "60KB"), ("Package", "48-LQFP")], [(BIN, 5, "")]),
    2: ("S9S12G192F0VLH", "IC MCU 16BIT 192KB FLASH 64LQFP", 3, "ic", [("Core Processor", "S12Z"), ("Program Memory Size", "192KB"), ("Package", "64-LQFP")], [("Room 127/Cabinet #3/Drawer 2", 5, "")]),
    3: ("MSP430F2012TN", "IC MCU 16BIT 2KB FLASH 14DIP", 3, "ic", [("Core Processor", "MSP430"), ("Program Memory Size", "2KB"), ("Package", "14-DIP")], [("Cabinet A/Drawer 3/Bin 2", 10, "")]),
    4: ("ERA-8AHD150V", "RES SMD 15 OHM 0.5% 1/4W 1206", 5, "res", [("Resistance", "15 Ohms"), ("Tolerance", "±0.5%"), ("Power (Watts)", "0.25W, 1/4W")], [(BIN, 25, "")]),
    5: ("RT1206DRE0715RL", "RES SMD 15 OHM 0.5% 1/4W 1206", 5, "res", [("Resistance", "15 Ohms"), ("Tolerance", "±0.5%"), ("Power (Watts)", "0.25W, 1/4W")], [("Room 127/Cabinet #2/Drawer 1", 100, "")]),
    6: ("RL81C221MDN1KX", "CAP ALUM POLY 220UF 20% 16V SMD", 7, "cap", [("Capacitance", "220 µF"), ("Voltage - Rated", "16V"), ("ESR (Equivalent Series Resistance)", "30mOhm")], [("Room 204/Shelf 1/Box A", 10, "")]),
    7: ("3SMAJ5939B-TP", "DIODE ZENER 39V 1.5W DO214AC", 9, "diode", [("Voltage - Zener (Nom) (Vz)", "39V"), ("Power - Max", "1.5W")], [(BIN, 15, "")]),
    8: ("LRS-350", "Mean Well LRS-350 power supply", 12, "psu", [], []),
    9: ("LRS-350 24V", "24V 14.6A 350W power supply", 12, "psu", [("Voltage - Output 1", "24V"), ("Current - Output (Max)", "14.6A"), ("Power (Watts)", "350W")], [("Room 127/Cabinet #1/Shelf 2", 2, "")]),
    10: ("LRS-350 12V", "12V 29A 348W power supply", 12, "psu", [("Voltage - Output 1", "12V"), ("Current - Output (Max)", "29A"), ("Power (Watts)", "348W")], [("Room 127/Cabinet #1/Shelf 2", 1, "")]),
    12: ("ERA-8AHD330V", "RES SMD 33 OHM 0.5% 1/4W 1206", 5, "res", [("Resistance", "33 Ohms"), ("Tolerance", "±0.5%"), ("Power (Watts)", "0.25W, 1/4W")], [("Room 127/Cabinet #2/Drawer 1", 40, "")]),
    13: ("ERA-8AHD4701V", "RES SMD 4.7K OHM 0.5% 1/4W 1206", 5, "res", [("Resistance", "4.7 kOhms"), ("Tolerance", "±0.5%"), ("Power (Watts)", "0.25W, 1/4W")], [("Room 127/Cabinet #2/Drawer 1", 0, "")]),
    14: ("RC1206FR-0710KL", "RES SMD 10K OHM 1% 1/4W 1206", 5, "res", [("Resistance", "10 kOhms"), ("Tolerance", "±1%"), ("Power (Watts)", "0.25W, 1/4W")], [("Room 127/Cabinet #2/Drawer 1", 500, "")]),
    15: ("CRCW1206100RFKEA", "RES SMD 100 OHM 1% 1/4W 1206", 5, "res", [("Resistance", "100 Ohms"), ("Tolerance", "±1%"), ("Power (Watts)", "0.25W, 1/4W")], [("Room 127/Cabinet #2/Drawer 1", 250, "")]),
    11: ("Dell Latitude laptop", "Spare laptop, charger in the bag", 13, "box", [], [("Unplaced", 1, "Bottom shelf of the grey rack, behind the printer")]),
}
INK, COPPER = "#0E4B3C", "#D08A3E"
LOCS: dict[int, str] = {}  # id -> path, for every place that holds stock and every place above it
for _p in PARTS.values():
    for _path, *_ in _p[5]:
        _segs = _path.split("/")
        for _i in range(1, len(_segs) + 1):
            _pp = "/".join(_segs[:_i])
            if _pp not in LOCS.values():
                LOCS[len(LOCS) + 1] = _pp
LOC_ID = {v: k for k, v in LOCS.items()}


def icon(kind: str) -> str:
    """A small flat drawing of the part, so the demo needs no photos."""
    g = {
        "ic": f'<rect x="22" y="22" width="36" height="36" rx="3" fill="#1b1f1e"/><circle cx="29" cy="29" r="2.4" fill="#555"/>' + "".join(
            f'<rect x="{26 + i * 7}" y="14" width="3" height="8" fill="{COPPER}"/><rect x="{26 + i * 7}" y="58" width="3" height="8" fill="{COPPER}"/>'
            f'<rect x="14" y="{26 + i * 7}" width="8" height="3" fill="{COPPER}"/><rect x="58" y="{26 + i * 7}" width="8" height="3" fill="{COPPER}"/>' for i in range(4)),
        "res": f'<rect x="14" y="30" width="52" height="20" rx="3" fill="#2a2a2a"/><rect x="14" y="30" width="10" height="20" fill="#c9c9c9"/><rect x="56" y="30" width="10" height="20" fill="#c9c9c9"/><text x="40" y="45" text-anchor="middle" font-size="11" fill="#eee" font-family="monospace">150</text>',
        "cap": f'<rect x="20" y="22" width="40" height="36" rx="4" fill="#2b2b2f"/><rect x="20" y="22" width="9" height="36" fill="#d9d9d9"/><rect x="14" y="36" width="8" height="8" fill="{COPPER}"/><rect x="58" y="36" width="8" height="8" fill="{COPPER}"/>',
        "diode": f'<rect x="18" y="28" width="44" height="24" rx="3" fill="#25272a"/><rect x="52" y="28" width="6" height="24" fill="#b7b7b7"/><rect x="10" y="37" width="8" height="6" fill="{COPPER}"/><rect x="62" y="37" width="8" height="6" fill="{COPPER}"/>',
        "psu": f'<rect x="12" y="20" width="56" height="40" rx="3" fill="#bfc6c8"/><rect x="12" y="20" width="56" height="8" fill="#9aa3a6"/>' + "".join(f'<circle cx="{20 + i * 8}" cy="50" r="2.4" fill="#444"/>' for i in range(6)),
        "box": '<rect x="14" y="26" width="52" height="30" rx="3" fill="#7a8a86"/><rect x="14" y="26" width="52" height="8" fill="#5d6b68"/>',
    }[kind]
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80"><rect width="80" height="80" fill="#EEF2F0"/>{g}</svg>'


def thumb(pid):
    return f"/demo/{PARTS[pid][3]}.svg"


def total(pid):
    return sum(q for _, q, _ in PARTS[pid][5]) + (sum(total(v) for v in (9, 10)) if pid == 8 else 0)


def row(pid):
    n, d, c, _, specs, _ = PARTS[pid]
    return {"id": pid, "name": n, "description": d, "thumbnail": thumb(pid), "total": total(pid), "category": CATS[c - 1][1], "category_id": c,
            "created": "2026-11-%02d" % (10 + pid), "specs": [{"name": a, "value": b} for a, b in specs[:3]]}


def where(pid):
    return [{"stock_id": pid * 10 + i, "path": p, "location_id": LOC_ID.get(p), "qty": q, "note": nt, "unplaced": p == "Unplaced"} for i, (p, q, nt) in enumerate(PARTS[pid][5])]


def under(cat, root):
    return cat == root or any(c[0] == cat and c[2] is not None and under(c[2], root) for c in CATS)


@app.get("/api/health")
def health():
    return {"ok": True, "digikey": True, "mouser": True, "mouser_key": "ok"}


@app.get("/api/home")
def home():
    ids = [p for p in PARTS if p != 8]
    return {"counts": {"parts": len(PARTS), "stock": sum(len(PARTS[p][5]) for p in PARTS), "bins": 9}, "unsorted": 0,
            "recent": [{**where(p)[0], "part_id": p, "name": PARTS[p][0], "description": PARTS[p][1], "thumbnail": thumb(p), "date": "2026-11-18"} for p in ids[::-1][:6]],
            "unplaced": [{**where(11)[0], "part_id": 11, "name": PARTS[11][0], "thumbnail": thumb(11)}]}


@app.get("/api/categories")
def categories():
    return [{"id": i, "name": n, "parent": p, "path": path, "count": sum(1 for k, v in PARTS.items() if under(v[2], i) and k != 8)} for i, n, p, path in CATS]


@app.get("/api/browse")
def browse(category: int | None = None, q: str = "", sort: str = "", wide: bool = False, f: list[str] = Query(default=[])):
    sel: dict[str, list[str]] = {}
    for item in f:
        n, _, v = item.partition("::")
        sel.setdefault(n, []).append(v)
    rows = [row(p) for p, v in PARTS.items() if (not category or under(v[2], category)) and (not q or q.lower() in v[0].lower() + v[1].lower())]
    specs_of = lambda r: {s["name"]: s["value"] for s in PARTS[r["id"]][4] and [{"name": a, "value": b} for a, b in PARTS[r["id"]][4]]}
    ok = lambda r, skip=None: all(specs_of(r).get(n) in vs for n, vs in sel.items() if vs and n != skip)
    kept = [r for r in rows if ok(r)]
    cover: dict = {}
    for r in kept:
        for n in specs_of(r):
            cover[n] = cover.get(n, 0) + 1
    columns = [n for n, _ in sorted(cover.items(), key=lambda kv: (-kv[1], kv[0]))][:5]
    for r in kept:
        r["cols"] = {n: specs_of(r).get(n, "") for n in columns}
    key = {"name": lambda r: r["name"].lower(), "stock": lambda r: -r["total"], "newest": lambda r: r["created"]}.get(sort)
    key and kept.sort(key=key, reverse=sort == "newest")
    facets = []
    for n in cover:
        counts: dict = {}
        for r in rows:
            if n in specs_of(r) and ok(r, skip=n):
                counts[specs_of(r)[n]] = counts.get(specs_of(r)[n], 0) + 1
        if len(counts) > 1 or sel.get(n):
            facets.append({"name": n, "coverage": cover[n], "values": [{"value": a, "count": c, "selected": a in sel.get(n, [])} for a, c in counts.items()]})
    return {"total": len(kept), "parts": kept, "facets": facets, "columns": columns}


@app.get("/api/find")
def find(q: str):
    words = q.lower().split()
    hay = lambda p: (PARTS[p][0] + " " + PARTS[p][1] + " " + " ".join(n for _, _, n in PARTS[p][5])).lower()  # names, descriptions and location notes
    return [{**row(p), "where": where(p)} for p in PARTS if p != 8 and all(w in hay(p) for w in words)]


@app.get("/api/part/{pk}")
def part(pk: int):
    n, d, c, _, specs, _ = PARTS[pk]
    variants = [{"id": v, "name": PARTS[v][0], "stock": total(v)} for v in (9, 10)] if pk == 8 else []
    return {"id": pk, "name": n, "description": d, "image": thumb(pk), "link": "https://example.com/datasheet.pdf", "category": CATS[c - 1][3],
            "category_id": c, "last_scanned": "2026-11-18", "total": total(pk), "variants": variants,
            "template": {"id": 8, "name": "LRS-350"} if pk in (9, 10) else None,
            "manufacturers": [{"name": "NXP USA Inc." if c == 3 else "Panasonic Industry", "mpn": n.split()[0]}],
            "suppliers": [{"sku": n + "-ND", "variant": "Cut Tape", "link": "https://www.digikey.com"}],
            "params": [{"name": a, "value": b} for a, b in specs],
            "stock": [{**w, "batch": "DK-12345678-999999", "details": "lot W39137.00 date code 2230", "date": "2026-11-18"} for w in where(pk)],
            "inventree_url": "https://inventree.example/web/part/%d/details" % pk}


@app.get("/api/peek/part/{pk}")
def peek_part(pk: int):
    n, d, c, _, specs, _ = PARTS[pk]
    return {"id": pk, "name": n, "description": d, "image": thumb(pk), "category": CATS[c - 1][1], "category_id": c, "total": total(pk), "link": None,
            "specs": [{"name": a, "value": b} for a, b in specs], "more_specs": 0, "where": where(pk)}


@app.get("/api/peek/category/{pk}")
def peek_category(pk: int):
    me = CATS[pk - 1]
    kids = [c for c in categories() if c["parent"] == pk and c["count"]]
    return {"id": pk, "name": me[1], "path": me[3], "count": sum(1 for v in PARTS.values() if under(v[2], pk)), "children": kids,
            "parts": [{"id": p, "name": v[0], "thumbnail": thumb(p), "total": total(p)} for p, v in PARTS.items() if under(v[2], pk) and p != 8][:8]}


@app.get("/api/places")
def places():
    out = []
    for i, p in LOCS.items():
        segs = p.split("/")
        out.append({"id": i, "name": segs[-1], "parent": LOC_ID.get("/".join(segs[:-1])), "path": p,
                    "items": sum(1 for v in PARTS.values() for q in v[5] if q[0] == p or q[0].startswith(p + "/"))})
    return out


@app.get("/api/location/{pk}")
def location(pk: int):
    path = LOCS.get(pk, "Room 127")
    inside = lambda p: p == path or p.startswith(path + "/")
    parts = []
    for pid, v in PARTS.items():
        lines = [{"stock_id": pid * 10 + i, "path": p, "location_id": LOC_ID.get(p), "qty": q, "note": nt, "here": p == path}
                 for i, (p, q, nt) in enumerate(v[5]) if inside(p)]
        if lines:
            parts.append({"part_id": pid, "name": v[0], "description": v[1], "thumbnail": thumb(pid), "total": sum(l["qty"] for l in lines), "lines": lines})
    kids = [{"id": i, "name": p.split("/")[-1], "path": p, "items": sum(1 for v in PARTS.values() for q in v[5] if q[0] == p or q[0].startswith(p + "/")), "places": 0}
            for i, p in LOCS.items() if p.rsplit("/", 1)[0] == path and "/" in p]
    segs = path.split("/")
    return {"id": pk, "name": segs[-1], "path": path, "ancestors": [{"id": LOC_ID["/".join(segs[:i])], "name": segs[i - 1]} for i in range(1, len(segs))],
            "children": sorted(kids, key=lambda k: k["name"]), "parts": parts, "lines": sum(len(p["lines"]) for p in parts)}


@app.get("/api/supplies")
def supplies():
    return {"models": [{"id": 8, "name": "LRS-350", "description": "", "category": 12, "variants": [{"id": 9, "name": "LRS-350 24V", "stock": 2}, {"id": 10, "name": "LRS-350 12V", "stock": 1}]}],
            "kinds": ["AC-DC Enclosed", "DIN Rail", "Wall Adapters", "Bench Supplies", "DC-DC Modules", "USB Chargers"]}


@app.get("/api/printing")
def printing():
    return {"templates": {"location": [], "stockitem": [], "part": []}, "printers": []}


@app.post("/api/{rest:path}")
async def anything(rest: str, request: Request):
    return Response('{"detail": "This is the demo: nothing is saved."}', status_code=422, media_type="application/json")


@app.get("/demo/{kind}.svg")
def demo_icon(kind: str):
    return Response(icon(html.escape(kind)), media_type="image/svg+xml")


app.mount("/static", StaticFiles(directory=ROOT / "public"), name="static")


@app.get("/")
def index():
    return Response((ROOT / "public" / "index.html").read_text(), media_type="text/html")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8800, log_level="warning")
