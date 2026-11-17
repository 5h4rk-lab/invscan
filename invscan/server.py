import hmac
import io
import os
import time
from pathlib import Path

import segno
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .browse import browse as browse_parts, param_index
from .browse import invalidate as invalidate_index
from .categories import list_categories
from .client import InvenTree
from .digikey import DigiKey
from .mouser import MOUSER_PN, Mouser, mpn_from_pn
from .ingest import add_manual, ingest
from .locations import LABEL_PREFIX, add_room, ensure_path, has_room, parse_label, place_path
from .notes import get_note, set_note
from .organise import organise
from .parser import ScanError, parse_scan
from .printing import MODELS, plan_print, printers, run_print, templates_by_model

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
app = FastAPI(title="invscan")
if PUBLIC.is_dir():  # on Vercel the CDN serves public/ and it is not bundled into the function
    app.mount("/static", StaticFiles(directory=PUBLIC), name="static")
_inv, _dk, _mouser = None, None, None


def inv() -> InvenTree:
    global _inv
    _inv = _inv or InvenTree()
    return _inv


def mouser() -> Mouser:
    global _mouser
    _mouser = _mouser or Mouser()
    return _mouser


def dk() -> DigiKey:
    global _dk
    _dk = _dk or DigiKey()
    return _dk


_fails: dict[str, list[float]] = {}
MAX_BAD_PINS, WINDOW = 8, 60.0


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


def auth(request: Request, x_pin: str | None = Header(default=None),
         pin_cookie: str | None = Cookie(default=None, alias="pin")):
    """PIN gate. A PIN is required unless INVSCAN_ALLOW_NO_PIN=1 (local development only)."""
    pin = os.environ.get("SCAN_PIN")
    if not pin:
        if os.environ.get("INVSCAN_ALLOW_NO_PIN") == "1":
            return
        raise HTTPException(503, "Set SCAN_PIN (or INVSCAN_ALLOW_NO_PIN=1 for local development).")
    given = x_pin or pin_cookie or ""
    ip, now = _client_ip(request), time.time()
    recent = [t for t in _fails.get(ip, []) if now - t < WINDOW]
    if len(recent) >= MAX_BAD_PINS:
        raise HTTPException(429, "Too many wrong PINs. Wait a minute and try again.")
    if not hmac.compare_digest(given.encode(), pin.encode()):
        if given:  # an empty PIN is just the page asking for one; only real guesses count
            _fails[ip] = recent + [now]
        raise HTTPException(401, "bad pin")


class ScanIn(BaseModel):
    raw: str
    location_id: int | None = None
    qty: int | None = None
    note: str | None = None
    mouser_pn: str | None = None  # Mouser's part number, read from the label's P/N barcode


class PathIn(BaseModel):
    path: str | None = None
    room: str | None = None
    cabinet: str | None = None
    drawer: str | None = None
    bin: str | None = None


class RoomIn(BaseModel):
    room: str


class QtyIn(BaseModel):
    qty: float


class OrganiseIn(BaseModel):
    limit: int = 10
    dry_run: bool = False


class PartEditIn(BaseModel):
    name: str | None = None
    description: str | None = None
    category: int | None = None


class PrintIn(BaseModel):
    model: str
    ids: list[int]
    template: int | None = None
    machine: str | None = None


class NewPartIn(BaseModel):
    name: str
    description: str | None = None
    qty: int
    location_id: int | None = None
    note: str | None = None


class PlaceIn(BaseModel):
    path: str | None = None
    note: str | None = None


def unplaced_id() -> int | None:
    """Existing 'Unplaced' location, or None (never creates)."""
    for l in inv().list("stock/location/", search="Unplaced", limit=50):
        if l["name"] == "Unplaced" and l["parent"] is None:
            return l["pk"]
    return None


def _where(s: dict) -> dict:
    loc = (s.get("location_detail") or {}).get("pathstring") or "No location"
    return {"stock_id": s["pk"], "path": loc, "qty": s["quantity"], "note": get_note(s.get("notes")),
            "unplaced": loc == "Unplaced"}


@app.get("/")
def index():
    return FileResponse(PUBLIC / "index.html", headers={"Cache-Control": "no-store"})


def _inventree_barcode(raw: str) -> dict | None:
    """Resolve a barcode InvenTree itself knows (part, stock item, location), or None."""
    try:
        r = inv().post("barcode/", barcode=raw)
    except RuntimeError:
        return None
    if r.get("stocklocation"):
        return {"kind": "bin", **location(r["stocklocation"]["pk"])}
    if r.get("part"):
        return {"kind": "part", "part_id": r["part"]["pk"]}
    if r.get("stockitem"):
        return {"kind": "part", "part_id": inv().get(f"stock/{r['stockitem']['pk']}/")["part"]}
    return None


@app.get("/api/health")
def health():
    return {"ok": True, "digikey": dk().enabled, "mouser": mouser().enabled}


@app.get("/api/home", dependencies=[Depends(auth)])
def home():
    i = inv()
    out = {
        "counts": {"parts": i.get("part/", limit=1)["count"], "stock": i.get("stock/", limit=1)["count"],
                   "bins": i.get("stock/location/", limit=1)["count"]},
        "recent": [], "unplaced": [], "unsorted": 0,
    }
    for c in i.list("part/category/", search="Unsorted", limit=20):
        if c["name"] == "Unsorted" and c["parent"] is None:
            out["unsorted"] = i.get("part/", category=c["pk"], limit=1)["count"]
    for s in i.list("stock/", ordering="-updated", limit=8, part_detail=True, location_detail=True):
        out["recent"].append({**_where(s), "part_id": s["part"], "name": s["part_detail"]["name"],
                              "description": s["part_detail"]["description"], "thumbnail": s["part_detail"].get("thumbnail"),
                              "date": s.get("updated", "")[:10]})
    up = unplaced_id()
    if up:
        for s in i.list("stock/", location=up, limit=100, part_detail=True, location_detail=True):
            out["unplaced"].append({**_where(s), "part_id": s["part"], "name": s["part_detail"]["name"],
                                    "thumbnail": s["part_detail"].get("thumbnail")})
    return out


@app.get("/api/location/{pk}", dependencies=[Depends(auth)])
def location(pk: int):
    l = inv().get(f"stock/location/{pk}/")
    return {"id": l["pk"], "path": l["pathstring"]}


@app.post("/api/bin", dependencies=[Depends(auth)])
def make_bin(body: PathIn):
    path = (body.path or "").strip() or place_path(body.room or "", body.cabinet or "", body.drawer or "", body.bin or "")
    if not path:
        raise HTTPException(422, "fill in at least the bin or box")
    pk = ensure_path(inv(), path)
    return {"id": pk, "path": inv().get(f"stock/location/{pk}/")["pathstring"]}


@app.post("/api/bin/{pk}/room", dependencies=[Depends(auth)])
def bin_room(pk: int, body: RoomIn):
    try:
        return add_room(inv(), pk, body.room)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/scan", dependencies=[Depends(auth)])
def scan(body: ScanIn):
    loc = parse_label(body.raw)
    if loc is not None:  # a bin label, not a bag
        return {"kind": "bin", **location(loc)}
    try:
        s = parse_scan(body.raw)
    except ScanError as e:
        hit = _inventree_barcode(body.raw)  # maybe a label printed by InvenTree for a part or stock item
        if hit:
            return hit
        raise HTTPException(422, str(e))
    if s.vendor == "mouser":
        pn = (body.mouser_pn or "").strip()
        if not MOUSER_PN.match(pn):  # the square code has no part number; it is in the long P/N barcode
            return {"kind": "need_pn", "vendor": "mouser", "qty": s.qty, "manufacturer": s.manufacturer}
        s.supplier_sku, s.mpn = pn, mpn_from_pn(pn)
    r = ingest(inv(), s, body.location_id, body.qty, dk(), body.note, mouser=mouser())
    return _bag_response(r, s.mpn, body.qty or s.qty)


def _bag_response(r, mpn: str, qty) -> dict:
    part = inv().get(f"part/{r.part_id}/") if r.part_id else {}
    where = _where(inv().get(f"stock/{r.stock_id}/", location_detail=True)) if r.stock_id else {}
    return {"kind": "bag", **r.__dict__, "mpn": mpn, "qty": where.get("qty", qty),
            "name": part.get("name"), "description": part.get("description"),
            "thumbnail": part.get("thumbnail"), "path": where.get("path"), "note": where.get("note", "")}


@app.post("/api/part/new", dependencies=[Depends(auth)])
def new_part(body: NewPartIn):
    """Add a part that has no DigiKey code (by part number or DigiKey PN). A photo can be attached afterwards."""
    r = add_manual(inv(), dk(), body.name, body.description or "", body.qty, body.location_id, body.note)
    if r.status == "error":
        raise HTTPException(422, r.message)
    return _bag_response(r, body.name.strip(), body.qty)


@app.post("/api/part/{pk}/image", dependencies=[Depends(auth)])
async def part_image(pk: int, request: Request):
    """Replace the part photo. Body is the raw image (the page sends a downscaled JPEG)."""
    data = await request.body()
    if not data or len(data) > 4_000_000:
        raise HTTPException(413, "photo is empty or too large")
    if not (data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(415, "send a JPEG or PNG")
    inv().patch_file(f"part/{pk}/", "image", f"part-{pk}.jpg" if data[:2] == b"\xff\xd8" else f"part-{pk}.png", data)
    p = inv().get(f"part/{pk}/")
    return {"image": p.get("image"), "thumbnail": p.get("thumbnail")}


@app.get("/api/categories", dependencies=[Depends(auth)])
def categories():
    return list_categories(inv())


@app.get("/api/browse", dependencies=[Depends(auth)])
def browse(category: int | None = None, q: str = "", sort: str = "", f: list[str] = Query(default=[])):
    """Parts in a category (and below) with DigiKey-style filters. f is repeated as 'Spec name::value'."""
    selected: dict[str, list[str]] = {}
    for item in f:
        if "::" in item:
            n, v = item.split("::", 1)
            selected.setdefault(n, []).append(v)
    return browse_parts(inv(), category, q.strip(), sort, selected)


@app.get("/api/peek/part/{pk}", dependencies=[Depends(auth)])
def peek_part(pk: int):
    """Everything a hover preview needs for one part, in one small response."""
    i = inv()
    p = i.get(f"part/{pk}/")
    specs = list(param_index(i).get(pk, {}).items())
    stock = i.list("stock/", part=pk, in_stock=True, location_detail=True, limit=20)
    return {"id": pk, "name": p["name"], "description": p["description"], "image": p.get("image") or p.get("thumbnail"),
            "category": p.get("category_name"), "category_id": p.get("category"),
            "total": sum(s["quantity"] for s in stock), "link": p.get("link"),
            "specs": [{"name": n, "value": v} for n, v in specs[:12]], "more_specs": max(0, len(specs) - 12),
            "where": [_where(s) for s in stock]}


@app.get("/api/peek/category/{pk}", dependencies=[Depends(auth)])
def peek_category(pk: int):
    """Sub-categories and a few parts, for the hover preview on a category."""
    cats = list_categories(inv())
    me = next((c for c in cats if c["id"] == pk), None)
    if not me:
        raise HTTPException(404, "no such category")
    page = inv().get("part/", category=pk, cascade="true", limit=8, ordering="-creation_date")
    parts = page["results"] if isinstance(page, dict) else page
    return {"id": pk, "name": me["name"], "path": me["path"], "count": me["count"],
            "children": sorted([c for c in cats if c["parent"] == pk and c["count"]], key=lambda c: c["name"].lower()),
            "parts": [{"id": p["pk"], "name": p["name"], "thumbnail": p.get("thumbnail"), "total": p.get("total_in_stock") or 0}
                      for p in parts]}


@app.post("/api/organise", dependencies=[Depends(auth)])
def organise_parts(body: OrganiseIn):
    """File parts that are still in Unsorted using DigiKey's categories. A few per call; call again for the rest."""
    return organise(inv(), dk(), min(max(body.limit, 1), 25), body.dry_run)


@app.get("/api/find", dependencies=[Depends(auth)])
def find(q: str):
    q = q.strip()
    parts: dict[int, dict] = {p["pk"]: p for p in inv().list("part/", search=q, limit=20)}
    up = unplaced_id()
    if up:  # InvenTree can't search stock notes, so match our own notes on the (small) Unplaced set
        words = q.lower().split()
        for s in inv().list("stock/", location=up, limit=200):
            hay = (get_note(s.get("notes")) + " " + str(s["part"])).lower()
            if words and all(w in hay for w in words) and s["part"] not in parts:
                parts[s["part"]] = inv().get(f"part/{s['part']}/")
    out = []
    for pid, p in parts.items():
        stock = inv().list("stock/", part=pid, in_stock=True, location_detail=True)
        out.append({"id": pid, "name": p["name"], "description": p["description"], "thumbnail": p.get("thumbnail"),
                    "category": p.get("category_name"), "category_id": p.get("category"),
                    "total": sum(s["quantity"] for s in stock), "where": [_where(s) for s in stock]})
    return out


@app.post("/api/stock/{pk}/place", dependencies=[Depends(auth)])
def place(pk: int, body: PlaceIn):
    """Move an item to a bin (by path) and/or set its location note."""
    item = inv().get(f"stock/{pk}/")
    notes = item.get("notes") or ""
    if body.path and body.path.strip():
        loc = ensure_path(inv(), body.path)
        inv().post("stock/transfer/", items=[{"pk": pk, "quantity": item["quantity"]}], location=loc,
                   notes="Moved with scanner")
        if body.note is None:  # a real bin replaces the 'where is it' note
            notes = set_note(notes, "")
    if body.note is not None:
        notes = set_note(notes, body.note)
    if notes != (item.get("notes") or ""):
        inv().patch(f"stock/{pk}/", notes=notes)
    return _where(inv().get(f"stock/{pk}/", location_detail=True))


@app.post("/api/stock/{pk}/qty", dependencies=[Depends(auth)])
def set_qty(pk: int, body: QtyIn):
    """Set the exact on-hand quantity (recorded as a stock count in InvenTree's history)."""
    if body.qty < 0:
        raise HTTPException(422, "quantity cannot be negative")
    inv().post("stock/count/", items=[{"pk": pk, "quantity": body.qty}], notes="Corrected with scanner")
    return _where(inv().get(f"stock/{pk}/", location_detail=True))


@app.get("/api/part/{pk}", dependencies=[Depends(auth)])
def part_detail(pk: int):
    i = inv()
    p = i.get(f"part/{pk}/")
    cat = ""
    if p.get("category"):
        cat = i.get(f"part/category/{p['category']}/").get("pathstring", "")
    tpl = {t["pk"]: t["name"] for t in i.list("parameter/template/", limit=500)}
    params, last = [], ""
    for x in i.list("parameter/", model_type="part.part", model_id=pk, limit=200):
        n = tpl.get(x["template"], "?")
        if n == "Last Scanned":
            last = x["data"]
        else:
            params.append({"name": n, "value": x["data"]})
    stock = i.list("stock/", part=pk, location_detail=True, limit=200)
    lines = []
    for s in stock:
        w = _where(s)
        raw = "\n".join(l for l in (s.get("notes") or "").splitlines() if not l.startswith("NOTE:"))
        lines.append({**w, "batch": s.get("batch", ""), "details": raw, "date": (s.get("creation_date") or "")[:10]})
    return {
        "id": pk, "name": p["name"], "description": p["description"], "image": p.get("image"), "link": p.get("link"),
        "category": cat, "category_id": p.get("category"), "last_scanned": last, "total": sum(s["quantity"] for s in stock if s.get("in_stock", True)),
        "manufacturers": [{"name": (m.get("manufacturer_detail") or {}).get("name", ""), "mpn": m["MPN"]}
                          for m in i.list("company/part/manufacturer/", part=pk, manufacturer_detail=True)],
        "suppliers": [{"sku": s["SKU"], "variant": s.get("description", ""), "link": s.get("link", "")}
                      for s in i.list("company/part/", part=pk)],
        "params": params, "stock": lines,
        "inventree_url": f"{i.url}/web/part/{pk}/details",
    }


@app.post("/api/part/{pk}/edit", dependencies=[Depends(auth)])
def part_edit(pk: int, body: PartEditIn):
    upd = {k: v.strip() for k, v in body.dict().items() if isinstance(v, str)}
    if body.category:
        upd["category"] = body.category
    if "name" in upd and not upd["name"]:
        raise HTTPException(422, "name cannot be empty")
    if upd:
        inv().patch(f"part/{pk}/", **upd)
    return part_detail(pk)


@app.get("/api/printing", dependencies=[Depends(auth)])
def printing_info():
    return {"templates": templates_by_model(inv()), "printers": printers(inv())}


@app.post("/api/print", dependencies=[Depends(auth)])
def print_labels(body: PrintIn):
    if body.model not in MODELS or not body.ids:
        raise HTTPException(422, "nothing to print")
    plan = plan_print(body.model, templates_by_model(inv()), printers(inv()), body.machine, body.template)
    if plan["template"] is None:
        raise HTTPException(422, f"no enabled label template for {body.model} in InvenTree")
    try:
        return run_print(inv(), body.model, body.ids, plan)
    except RuntimeError as e:
        raise HTTPException(502, str(e))


@app.get("/labels", response_class=HTMLResponse, dependencies=[Depends(auth)])
def labels(ids: str):
    cells = []
    for pk in [int(i) for i in ids.split(",") if i.strip().isdigit()]:
        l = inv().get(f"stock/location/{pk}/")
        buf = io.BytesIO()
        segno.make(f"{LABEL_PREFIX}{pk}", error="m").save(buf, kind="svg", scale=4, border=1)
        cells.append(f"<div class=c>{buf.getvalue().decode()}<b>{l['pathstring']}</b></div>")
    return ("<!doctype html><style>body{font:14px sans-serif}.c{display:inline-block;width:5cm;margin:4px;padding:6px;"
            "border:1px dashed #999;text-align:center;page-break-inside:avoid}.c svg{width:3.5cm;height:3.5cm}</style>"
            + "".join(cells))


@app.get("/media/{path:path}", dependencies=[Depends(auth)])
def media(path: str):
    """InvenTree serves images at /media; proxy them so the phone page needn't reach InvenTree directly."""
    r = inv().s.get(f"{inv().url}/media/{path}", timeout=20)
    return Response(r.content, status_code=r.status_code, media_type=r.headers.get("content-type"))
