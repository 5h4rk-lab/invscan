"""Builds: read a BOM spreadsheet (KiCad's CSV or XLSX export, or any similar sheet), match its lines to parts in InvenTree,
create the build (an InvenTree assembly with a BOM) and say whether the parts on hand are enough."""
import csv
import io
import math
import re
from concurrent.futures import ThreadPoolExecutor

from .categories import digikey_path, ensure_category_path, misc_category
from .enrich import add_supplier_part, enrich_part, ensure_manufacturer_part
from .ingest import find_part
from .parser import DK_PN, Scan

BUILDS = "Builds"
MAX_LINES = 400


class BomError(ValueError):
    """Something wrong with the sheet or the request: the message is safe to show."""


# header names people and tools use, per field. KiCad: Reference/Refs, Value, Footprint, Qty, DNP, plus any custom fields.
ALIASES = {
    "qty": {"qty", "quantity", "count", "qty per", "quantity per", "qnty", "amount", "qty per board"},
    "refs": {"reference", "references", "refs", "designator", "designators", "ref", "reference s", "ref des", "refdes"},
    "mpn": {"mpn", "manufacturer part number", "manufacturer part no", "manufacturer part", "mfr part number", "mfr part", "mfr part no",
            "mfg part number", "mfg part no", "mfg part", "manufacturer pn", "mfr pn", "mfg pn", "part number", "partnumber", "pn",
            "part no", "part", "manufacturerpartnumber", "manufacturer part number mpn", "mpn manufacturer part number"},
    "dkpn": {"digikey", "digi key", "digikey part number", "digi key part number", "digikey pn", "dk pn", "digikey part", "digikey part no",
             "digikey_pn", "supplier part number", "supplier pn", "supplier part no", "supplier part", "spn", "dk part number", "dk part no"},
    "maker": {"manufacturer", "mfr", "mfg", "manufacturer name", "mfr name", "maker", "manufacturer 1"},
    "value": {"value", "val", "comment"},
    "footprint": {"footprint", "package", "pattern"},
    "desc": {"description", "desc"},
    "dnp": {"dnp", "do not populate", "do not place", "dnf", "do not fit", "exclude from bom"},
    "fit": {"populate", "fitted", "fit", "populated"},
}
TRUE = {"yes", "y", "true", "1", "x", "dnp", "dnf", "do not place", "do not fit", "do not populate"}
FALSE = {"no", "n", "false", "0", "", "-", "dnp"}


def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9#]+", " ", (h or "").lower().replace("(s)", "s"))).strip()


def _field(header: str) -> str | None:
    n = _norm(header)
    for f, names in ALIASES.items():
        if n in names:
            return f
    if "digi" in n and "key" in n:
        return "dkpn"
    if ("manufacturer" in n or "mfr" in n or "mfg" in n) and ("part" in n or "number" in n or n.endswith(" pn")):
        return "mpn"
    return None


def read_table(data: bytes, filename: str = "") -> list[list[str]]:
    """Rows of text from an .xlsx, .csv or .tsv upload. Every sheet of a workbook is returned one after another."""
    name = (filename or "").lower()
    if name.endswith((".xls", ".ods", ".numbers")):
        raise BomError("Save the sheet as .xlsx or .csv first (Excel: File > Save As. Google Sheets: File > Download).")
    if name.endswith((".xlsx", ".xlsm")) or data[:2] == b"PK":
        try:
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as e:  # a corrupt or password-protected file
            raise BomError(f"Could not open that spreadsheet ({e.__class__.__name__}). Try saving it again as .xlsx or .csv.")
        rows: list[list[str]] = []
        for ws in wb.worksheets:
            for r in ws.iter_rows(values_only=True):
                rows.append([("" if c is None else (str(int(c)) if isinstance(c, float) and c == int(c) else str(c))).strip() for c in r])
            rows.append([])  # a blank row between sheets
        return rows
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    sample = "\n".join(text.splitlines()[:5])
    delim = max(",;\t", key=sample.count) if sample.strip() else ","
    return [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), delimiter=delim)]


def _header(rows: list[list[str]]):
    """(row index, {column: field}) of the header row: the first rows that name a quantity or references plus something to identify a part."""
    for i, r in enumerate(rows[:40]):
        cols = {}
        for j, cell in enumerate(r):
            f = _field(cell)
            if f and f not in cols.values():
                cols[j] = f
        found = set(cols.values())
        if len(found) >= 2 and found & {"qty", "refs"} and found & {"mpn", "dkpn", "value", "desc"}:
            return i, cols
    return None, {}


def _qty(text: str) -> float | None:
    m = re.match(r"^\s*(\d+(?:[.,]\d+)?)", text or "")
    return float(m.group(1).replace(",", ".")) if m else None


def parse_bom(data: bytes, filename: str = "") -> dict:
    rows = read_table(data, filename)
    at, cols = _header(rows)
    if at is None:
        raise BomError("Could not find the columns. The sheet needs a header row with a quantity (Qty) and a part number "
                       "(MPN or Digi-Key part number) or a value. KiCad: Tools > Generate BOM, or the BOM export in the schematic editor.")
    lines: dict[tuple, dict] = {}
    skipped, warnings = 0, []
    for n, r in enumerate(rows[at + 1:], start=at + 2):
        if not any(c for c in r):
            continue
        cell = {f: (r[j] if j < len(r) else "") for j, f in cols.items()}
        if (cell.get("dnp", "").strip().lower() in TRUE and cell.get("dnp")) or (cell.get("fit") and cell["fit"].strip().lower() in {"no", "n", "false", "0", "dnp"}):
            skipped += 1
            continue
        refs = [x for x in re.split(r"[,\s;]+", cell.get("refs", "")) if x]
        qty = _qty(cell.get("qty", "")) if cell.get("qty") else None
        if qty is None and refs:
            qty = float(len(refs))
        mpn, dk = cell.get("mpn", "").strip(), cell.get("dkpn", "").strip()
        if not DK_PN.match(dk):
            dk = next((t for c in r for t in re.split(r"[\s,;]+", c) if DK_PN.match(t)), "")  # a Digi-Key number anywhere in the row
        if DK_PN.match(mpn):  # the "part number" column holds a Digi-Key number
            dk, mpn = mpn, ""
        if not (mpn or dk or cell.get("value") or cell.get("desc")):
            continue  # a heading, a total, a note
        if not qty or qty <= 0:
            warnings.append(f"Row {n}: no quantity, left out.")
            continue
        ln = {"row": n, "qty": qty, "refs": refs, "mpn": mpn, "dk_pn": dk if DK_PN.match(dk) else "", "maker": cell.get("maker", ""),
              "value": cell.get("value", ""), "footprint": cell.get("footprint", ""), "desc": cell.get("desc", "")}
        key = (ln["dk_pn"].lower() or ln["mpn"].lower() or (ln["value"].lower(), ln["footprint"].lower()))
        if key in lines:  # the same part on several rows: one line, quantities added
            lines[key]["qty"] += qty
            lines[key]["refs"] += refs
        else:
            lines[key] = ln
    if not lines:
        raise BomError("No parts found under the header row.")
    if len(lines) > MAX_LINES:
        raise BomError(f"That BOM has {len(lines)} lines; the limit is {MAX_LINES}.")
    return {"lines": list(lines.values()), "skipped": skipped, "warnings": warnings[:20]}


def _match_one(inv, ln: dict) -> dict:
    pid, how = None, ""
    if ln["dk_pn"]:
        sp = inv.list("company/part/", SKU=ln["dk_pn"], limit=5)
        if sp:
            pid, how = sp[0]["part"], "Digi-Key number"
    # KiCad often puts the part number in the Value field (U1: MSP430F2012TN), so try that as a part number too
    for text, label in ((ln["mpn"], "manufacturer part number"), (ln["value"], "value")):
        if pid or not text:
            continue
        mp = inv.list("company/part/manufacturer/", MPN=text, limit=10)
        if mp:
            pid, how = mp[0]["part"], label
            break
        for p in inv.list("part/", search=text, limit=20):
            if text.lower() in (p["name"].lower(), (p.get("IPN") or "").lower()):
                pid, how = p["pk"], "part name" if label != "value" else "value"
                break
    out = {**ln, "part_id": pid, "how": how, "part_name": "", "thumbnail": None, "candidates": []}
    if pid:
        p = inv.get(f"part/{pid}/")
        out.update(part_name=p["name"], thumbnail=p.get("thumbnail"))
    else:  # no match: suggest parts that look like it (a 10k resistor for "10k"), for the person to pick
        seen: dict[int, dict] = {}
        for text in (ln["mpn"], ln["value"], ln["desc"]):
            if text.strip() and len(seen) < 5:
                for p in inv.list("part/", search=text.strip(), limit=5):
                    seen.setdefault(p["pk"], {"id": p["pk"], "name": p["name"], "description": p.get("description", "")})
        out["candidates"] = list(seen.values())[:5]
    return out


def match_lines(inv, lines: list[dict]) -> list[dict]:
    with ThreadPoolExecutor(6) as ex:
        return list(ex.map(lambda ln: _match_one(inv, ln), lines))


def create_component(inv, dk, mpn: str, maker: str = "", desc: str = "", dk_pn: str = "") -> tuple[int, bool]:
    """A part for this manufacturer part number, or for a Digi-Key number alone (made with DigiKey's details if they can
    be found). (id, newly created)."""
    product = None
    if dk and dk_pn:
        product = dk.lookup(dk_pn, dk_pn)
        if product:
            mpn = product["ManufacturerProductNumber"]
    if not mpn:
        raise BomError(f"{dk_pn} is not known at DigiKey, so there is no part number to create it from.")
    scan = Scan(mpn=mpn, manufacturer=maker or "")
    product = product or (dk.lookup(mpn, None, maker or None) if dk else None)
    pid, _ = find_part(inv, scan, product)
    if pid:
        return pid, False
    category = ensure_category_path(inv, digikey_path(product)) or misc_category(inv)
    pid = inv.post("part/", name=mpn, IPN=mpn, category=category, component=True, purchaseable=True,
                   description=(desc or "Added from a BOM")[:250])["pk"]
    if product:
        enrich_part(inv, pid, product)
    elif maker:
        ensure_manufacturer_part(inv, pid, maker, mpn)
    return pid, True


def create_build(inv, dk, name: str, lines: list[dict]) -> dict:
    """lines: [{part_id | create: true + mpn, qty, refs, value, footprint, skip}]. Parts are settled first, then the assembly is made."""
    name = " ".join((name or "").split())[:100]
    if not name:
        raise BomError("Give the build a name, for example Little Foot rev F.")
    if any(p["name"].lower() == name.lower() for p in inv.list("part/", search=name, limit=50)):
        raise BomError(f'"{name}" already exists. Use a new name for a new revision, for example "{name} rev B".')
    resolved, created, skipped = [], [], 0
    for ln in lines:
        if ln.get("skip"):
            skipped += 1
            continue
        pid = ln.get("part_id")
        if not pid and ln.get("create") and (ln.get("mpn") or ln.get("dk_pn")):
            pid, new = create_component(inv, dk, ln.get("mpn", ""), ln.get("maker", ""), ln.get("desc", ""), ln.get("dk_pn", ""))
            if new:
                created.append(ln.get("mpn") or ln["dk_pn"])
        if not pid:
            skipped += 1
            continue
        resolved.append((pid, ln))
    if not resolved:
        raise BomError("None of the lines has a part to use yet. Pick a part for each line, or create it from its part number.")
    asm = inv.post("part/", name=name, IPN=name, description=f"Build: {name}", assembly=True, component=False,
                   category=ensure_category_path(inv, [BUILDS]))["pk"]
    merged: dict[int, dict] = {}
    for pid, ln in resolved:  # two lines resolved to the same part are one BOM line
        e = merged.setdefault(pid, {"qty": 0.0, "refs": [], "note": ""})
        e["qty"] += float(ln["qty"])
        e["refs"] += ln.get("refs") or []
        e["note"] = e["note"] or " ".join(x for x in (ln.get("value"), ln.get("footprint")) if x)
    for pid, e in merged.items():
        inv.post("bom/", part=asm, sub_part=pid, quantity=e["qty"], reference=", ".join(e["refs"])[:5000], note=e["note"][:100])
    return {"id": asm, "name": name, "lines": len(merged), "created_parts": created, "skipped": skipped}


def build_status(inv, pk: int, n: int = 1) -> dict:
    """Can this build be made n times from what is on hand? Per line: needed, available, on order, short."""
    asm = inv.get(f"part/{pk}/")
    out, can = [], None
    for r in inv.list("bom/", part=pk, sub_part_detail="true", limit=1000):
        per = float(r["quantity"])
        sub = r.get("sub_part_detail") or {}
        have = float(r.get("available_stock") or 0) + float(r.get("available_substitute_stock") or 0) + float(r.get("available_variant_stock") or 0)
        need, ordered = per * n, float(r.get("on_order") or 0)
        short = max(0.0, need - have)
        optional = bool(r.get("optional"))
        status = "ok" if short <= 0 else ("optional" if optional else ("ordered" if ordered >= short else "short"))
        if not optional and per > 0:
            c = math.floor(have / per)
            can = c if can is None else min(can, c)
        out.append({"bom_id": r["pk"], "part_id": r["sub_part"], "name": sub.get("name", "?"), "description": sub.get("description", ""),
                    "thumbnail": sub.get("thumbnail"), "refs": r.get("reference", ""), "note": r.get("note", ""), "per": per, "need": need,
                    "have": have, "on_order": ordered, "short": short, "status": status, "optional": optional})
    out.sort(key=lambda x: ({"short": 0, "ordered": 1, "ok": 2, "optional": 3}[x["status"]], x["name"].lower()))
    missing = [x for x in out if x["status"] in ("short", "ordered")]
    return {"id": pk, "name": asm["name"], "description": asm.get("description", ""), "n": n, "lines": out, "can_build": can or 0,
            "complete": not missing, "missing": len(missing), "short": sum(1 for x in out if x["status"] == "short")}


def list_builds(inv) -> list[dict]:
    """Every assembly that has a BOM, with how many boards the parts on hand would make."""
    asms = [p for p in inv.list("part/", assembly="true", limit=500) if not p.get("is_template")]
    with ThreadPoolExecutor(6) as ex:
        stats = list(ex.map(lambda p: build_status(inv, p["pk"], 1), asms))
    return [{"id": s["id"], "name": s["name"], "lines": len(s["lines"]), "can_build": s["can_build"], "missing": s["missing"]}
            for s in sorted(stats, key=lambda s: s["name"].lower()) if s["lines"]]
